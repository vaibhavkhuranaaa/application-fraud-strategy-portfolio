"""Capacity-aware, non-binding fraud strategy simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any

import numpy as np
import pandas as pd

from .config import CAPACITIES


@dataclass(frozen=True)
class QueueOutcome:
    actions: np.ndarray
    ranks: np.ndarray
    review_mask: np.ndarray
    referral_mask: np.ndarray
    forced_mask: np.ndarray
    capacity_count: int
    overflow: int


def concentration_rule_flags(frame: pd.DataFrame, branch_cut: float | None = None) -> dict[str, np.ndarray]:
    if branch_cut is None:
        branch_cut = float(frame["bank_branch_count_8w"].quantile(0.99))
    return {
        "dob_email_concentration": frame["date_of_birth_distinct_emails_4w"].to_numpy() >= 8,
        "device_email_concentration": frame["device_distinct_emails_8w"].fillna(-1).to_numpy() >= 2,
        "foreign_low_identity_similarity": (
            frame["foreign_request"].to_numpy().astype(bool)
            & (frame["name_email_similarity"].to_numpy() < 0.20)
        ),
        "branch_concentration": frame["bank_branch_count_8w"].to_numpy() >= branch_cut,
    }


def combine_rule_flags(flags: dict[str, np.ndarray], toggles: dict[str, bool] | None = None) -> np.ndarray:
    if not flags:
        return np.array([], dtype=bool)
    toggles = toggles or {name: True for name in flags}
    active = [values for name, values in flags.items() if toggles.get(name, False)]
    if not active:
        return np.zeros(len(next(iter(flags.values()))), dtype=bool)
    return np.logical_or.reduce(active)


def rank_review_queue(
    scores: np.ndarray,
    review_capacity: float,
    *,
    forced_review: np.ndarray | None = None,
) -> QueueOutcome:
    scores = np.asarray(scores, dtype=float)
    if scores.ndim != 1 or not len(scores):
        raise ValueError("scores must be a non-empty one-dimensional array")
    if not 0 < review_capacity <= 1:
        raise ValueError("review_capacity must be in (0, 1]")
    if np.any(~np.isfinite(scores)) or np.any((scores < 0) | (scores > 1)):
        raise ValueError("scores must be finite probabilities")
    forced = (
        np.zeros(len(scores), dtype=bool) if forced_review is None else np.asarray(forced_review, dtype=bool)
    )
    if len(forced) != len(scores):
        raise ValueError("forced_review length must match scores")

    capacity_count = max(1, int(np.floor(len(scores) * review_capacity)))
    order = np.lexsort((-scores, ~forced))
    ranks = np.empty(len(scores), dtype=np.int64)
    ranks[order] = np.arange(1, len(scores) + 1)
    selected = order[:capacity_count]
    review_mask = np.zeros(len(scores), dtype=bool)
    review_mask[selected] = True
    referral_mask = forced & ~review_mask
    actions = np.full(len(scores), "clear", dtype=object)
    actions[review_mask] = "manual_review"
    actions[referral_mask] = "governance_referral"
    return QueueOutcome(
        actions=actions,
        ranks=ranks,
        review_mask=review_mask,
        referral_mask=referral_mask,
        forced_mask=forced,
        capacity_count=capacity_count,
        overflow=int(referral_mask.sum()),
    )


def policy_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    review_capacity: float,
    *,
    forced_review: np.ndarray | None = None,
) -> dict[str, Any]:
    labels = np.asarray(labels, dtype=np.int8)
    outcome = rank_review_queue(scores, review_capacity, forced_review=forced_review)
    actioned = outcome.review_mask | outcome.referral_mask
    positives = labels == 1
    negatives = ~positives
    caught = int((actioned & positives).sum())
    false_positives = int((actioned & negatives).sum())
    return {
        "capacity": review_capacity,
        "capacity_count": outcome.capacity_count,
        "queue_size": int(outcome.review_mask.sum()),
        "governance_referrals": int(outcome.referral_mask.sum()),
        "overflow": outcome.overflow,
        "fraud_caught": caught,
        "catch_rate": caught / max(int(positives.sum()), 1),
        "false_positive_count": false_positives,
        "false_positive_rate": false_positives / max(int(negatives.sum()), 1),
        "precision": caught / max(int(actioned.sum()), 1),
        "review_rate": float(actioned.mean()),
    }


def expected_utility(
    metrics: dict[str, Any],
    *,
    fraud_exposure: float,
    review_cost: float,
    friction_cost: float,
    review_effectiveness: float = 1.0,
    loss_given_fraud: float = 1.0,
) -> float:
    """Net position under one set of assumptions.

    `review_effectiveness` is the share of fraud routed to review that the review actually
    stops, and `loss_given_fraud` is the share of exposure that would actually have been
    lost. Both default to 1.0, which is the behaviour every recorded figure was produced
    under: review prevents everything it touches and prevention saves the whole balance.
    Neither is true, and neither has a source that meets this project's citation bar, so
    they are sensitivity dimensions rather than contract values. See
    `economic_sensitivity_surface`.
    """
    prevented = metrics["fraud_caught"] * review_effectiveness * loss_given_fraud
    return (
        prevented * fraud_exposure
        - metrics["false_positive_count"] * friction_cost
        - metrics["queue_size"] * review_cost
    )


def economic_grid() -> list[dict[str, float]]:
    exposures = (5_000.0, 8_900.0, 12_500.0, 16_900.0, 20_000.0)
    review_costs = (7.0, 17.0, 27.0)
    friction_costs = (0.0, 50.0, 150.0, 300.0)
    return [
        {"fraud_exposure": exposure, "review_cost": review, "friction_cost": friction}
        for exposure, review, friction in product(exposures, review_costs, friction_costs)
    ]


def compare_utility_grid(
    challenger_metrics: dict[str, Any],
    incumbent_metrics: dict[str, Any],
    grid: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    grid = grid or economic_grid()
    increments = [
        expected_utility(challenger_metrics, **assumptions)
        - expected_utility(incumbent_metrics, **assumptions)
        for assumptions in grid
    ]
    positive = int(sum(value > 0 for value in increments))
    return {
        "grid_points": len(grid),
        "positive_points": positive,
        "positive_share": positive / len(grid),
        "incremental_utility_min": float(min(increments)),
        "incremental_utility_median": float(np.median(increments)),
        "incremental_utility_max": float(max(increments)),
    }


# Declared sensitivity ranges, not sourced values. Recorded here so the reason travels with
# the numbers.
#
# Review effectiveness. A manual review does not stop every fraud it touches: a cultivated
# synthetic identity is built to survive verification, and reviewer accuracy falls with
# volume and fatigue. No public benchmark for loan-origination review effectiveness meets
# the bar the OneMain 10-K and BLS figures cleared. The available material is vendor
# marketing about e-commerce chargeback review, which is a different population, a
# different decision, and commercially motivated. It is therefore a sensitivity input with
# no observed source, exactly as customer-friction cost already is.
#
# Loss given fraud. The approved exposure grid is described in the evaluation contract as
# outstanding-balance anchors and explicitly "not observed fraud losses", so the contract
# already names this gap. Recovery on a fraudulent origination is structurally worse than
# portfolio recovery, because there is no genuine borrower to collect from, and on auto
# there is collateral where on an unsecured personal loan there is not. A portfolio
# recovery rate would therefore overstate fraud recovery, and quoting one as loss given
# fraud would be a category error of exactly the kind this project refuses elsewhere.
REVIEW_EFFECTIVENESS_RANGE = (0.60, 0.75, 0.90, 1.00)
LOSS_GIVEN_FRAUD_RANGE = (0.40, 0.60, 0.80, 1.00)


def economic_sensitivity_surface(
    challenger_metrics: dict[str, Any],
    incumbent_metrics: dict[str, Any],
    grid: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Sweep the approved grid across review effectiveness and loss given fraud.

    This is evidence, not a gate. The promotion gate keeps the approved 60-point grid at
    both factors equal to 1.0, unchanged and byte-identical, because widening the grid a
    gate is measured against would change what "positive for at least 80% of the approved
    assumption grid" means, and that needs a newly approved evaluation contract. The same
    standard M6 applied to the calibration intercept: measure the problem, record it, leave
    the pre-registered gate alone.
    """
    grid = grid or economic_grid()
    cells: list[dict[str, Any]] = []
    for effectiveness, severity in product(REVIEW_EFFECTIVENESS_RANGE, LOSS_GIVEN_FRAUD_RANGE):
        increments = [
            expected_utility(
                challenger_metrics,
                **assumptions,
                review_effectiveness=effectiveness,
                loss_given_fraud=severity,
            )
            - expected_utility(
                incumbent_metrics,
                **assumptions,
                review_effectiveness=effectiveness,
                loss_given_fraud=severity,
            )
            for assumptions in grid
        ]
        positive = int(sum(value > 0 for value in increments))
        cells.append(
            {
                "review_effectiveness": effectiveness,
                "loss_given_fraud": severity,
                "grid_points": len(grid),
                "positive_points": positive,
                "positive_share": positive / len(grid),
                "incremental_utility_min": float(min(increments)),
                "incremental_utility_median": float(np.median(increments)),
                "incremental_utility_max": float(max(increments)),
            }
        )
    worst = min(cells, key=lambda cell: cell["incremental_utility_min"])
    unadjusted = next(
        cell for cell in cells if cell["review_effectiveness"] == 1.0 and cell["loss_given_fraud"] == 1.0
    )
    return {
        "basis": "the approved 60-point grid, swept across both factors",
        "status": "sensitivity evidence, not a promotion gate",
        "review_effectiveness_range": list(REVIEW_EFFECTIVENESS_RANGE),
        "loss_given_fraud_range": list(LOSS_GIVEN_FRAUD_RANGE),
        "sourcing": (
            "Neither factor has a source meeting this project's citation bar. Both are declared "
            "sensitivity inputs, as customer-friction cost already is, and no figure derived from "
            "them may be presented as an observed result."
        ),
        "cells": cells,
        "sign_holds_everywhere": all(cell["positive_share"] == 1.0 for cell in cells),
        "reported_band": {
            "min": worst["incremental_utility_min"],
            "max": unadjusted["incremental_utility_max"],
        },
        "inflation_factor_at_worst_case": (
            unadjusted["incremental_utility_median"] / worst["incremental_utility_median"]
            if worst["incremental_utility_median"]
            else None
        ),
    }


def pareto_frontier(rows: list[dict[str, Any]]) -> list[int]:
    """Return indices not dominated on catch, friction, volume, and utility."""
    frontier: list[int] = []
    for index, row in enumerate(rows):
        dominated = False
        for other_index, other in enumerate(rows):
            if other_index == index:
                continue
            no_worse = (
                other["catch_rate"] >= row["catch_rate"]
                and other["false_positive_rate"] <= row["false_positive_rate"]
                and other["review_rate"] <= row["review_rate"]
                and other["utility"] >= row["utility"]
            )
            strictly_better = (
                other["catch_rate"] > row["catch_rate"]
                or other["false_positive_rate"] < row["false_positive_rate"]
                or other["review_rate"] < row["review_rate"]
                or other["utility"] > row["utility"]
            )
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(index)
    return frontier


def evaluate_strategy_frontier(
    labels: np.ndarray,
    challenger_scores: np.ndarray,
    incumbent_scores: np.ndarray,
    rule_flags: dict[str, np.ndarray],
    capacities: tuple[float, ...] = CAPACITIES,
) -> dict[str, Any]:
    policies: list[dict[str, Any]] = []
    incumbent_by_capacity: dict[float, dict[str, Any]] = {}
    for capacity in capacities:
        incumbent_by_capacity[capacity] = policy_metrics(labels, incumbent_scores, capacity)
        for rules_enabled in (False, True):
            forced = combine_rule_flags(rule_flags) if rules_enabled else None
            metrics = policy_metrics(labels, challenger_scores, capacity, forced_review=forced)
            utility = expected_utility(
                metrics, fraud_exposure=12_500.0, review_cost=17.0, friction_cost=150.0
            )
            grid = compare_utility_grid(metrics, incumbent_by_capacity[capacity])
            policies.append(
                {
                    "policy_id": f"capacity-{capacity:.2f}-rules-{str(rules_enabled).lower()}",
                    "rules_enabled": rules_enabled,
                    **metrics,
                    "utility": utility,
                    "economic_grid": grid,
                }
            )
    frontier = pareto_frontier(policies)
    for index, policy in enumerate(policies):
        policy["frontier"] = index in frontier

    eligible = [
        row for row in policies if row["overflow"] == 0 and row["economic_grid"]["positive_share"] >= 0.80
    ]
    recommended = max(eligible, key=lambda row: (row["utility"], row["catch_rate"]), default=None)
    refusal_reasons: list[str] = []
    if recommended is None:
        refusal_reasons.append(
            "No policy beats the incumbent proxy across at least 80% of the economic grid."
        )
        if all(row["overflow"] for row in policies if row["rules_enabled"]):
            refusal_reasons.append("Every rule-enabled policy exceeds the manual-review capacity.")
    return {
        "policies": policies,
        "frontier_policy_ids": [policies[index]["policy_id"] for index in frontier],
        "recommendation": recommended["policy_id"] if recommended else "no robust recommendation",
        "refusal_reasons": refusal_reasons,
        "assumption_notice": "Economic values are scenario assumptions, not observed profit or loss.",
    }


def enforce_governance_refusal(
    frontier: dict[str, Any],
    promotion_gates: dict[str, bool],
    *,
    fairness_review_required: bool,
    drift_blocks: int,
) -> dict[str, Any]:
    """Prevent a policy recommendation when its model/governance evidence is unresolved."""
    result = dict(frontier)
    result["candidate_frontier_recommendation"] = frontier["recommendation"]
    reasons = list(frontier["refusal_reasons"])
    failed_gates = sorted(name for name, passed in promotion_gates.items() if not passed)
    if failed_gates:
        reasons.append("Model promotion gates failed: " + ", ".join(failed_gates) + ".")
    if fairness_review_required:
        reasons.append("Segment evidence requires unresolved governance review.")
    if drift_blocks:
        reasons.append(f"{drift_blocks} PSI results meet the automatic-promotion block threshold.")
    if reasons:
        result["recommendation"] = "no robust recommendation"
        result["refusal_reasons"] = list(dict.fromkeys(reasons))
    return result


def queue_outcome_dict(outcome: QueueOutcome) -> dict[str, Any]:
    value = asdict(outcome)
    return {key: item.tolist() if isinstance(item, np.ndarray) else item for key, item in value.items()}
