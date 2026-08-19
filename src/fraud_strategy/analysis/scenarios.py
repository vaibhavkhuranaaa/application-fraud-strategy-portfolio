"""Non-binding policy scenarios over the recorded month-7 evidence.

Scenarios reuse the M3 strategy engine unchanged. Nothing here retrains, retunes, or
rewrites evidence: a capacity, a set of concentration rules, and three economic
assumptions are applied to the recorded scores, and the result is what those scores
would have produced.

The dashboard precomputes its own grid in `scripts/build_dashboard_data.py`. This
module exists for the release gate, which checks that a scenario computed live still
reproduces the recorded month-7 policies exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..strategy import (
    combine_rule_flags,
    concentration_rule_flags,
    expected_utility,
    policy_metrics,
)

RULE_LABELS = {
    "dob_email_concentration": "Eight or more recent emails share the birth-date signal",
    "device_email_concentration": "Two or more recent emails share the device",
    "foreign_low_identity_similarity": "Foreign request with weak name-and-email similarity",
    "branch_concentration": "Selected-branch application concentration in the top 1%",
}

ASSUMPTION_BOUNDS = {
    "fraud_exposure": (5_000.0, 20_000.0, 12_500.0),
    "review_cost": (7.0, 27.0, 17.0),
    "friction_cost": (0.0, 300.0, 150.0),
}


@dataclass(frozen=True)
class Assumptions:
    """Analyst-entered economic inputs. These are assumptions, never observed P&L."""

    fraud_exposure: float = ASSUMPTION_BOUNDS["fraud_exposure"][2]
    review_cost: float = ASSUMPTION_BOUNDS["review_cost"][2]
    friction_cost: float = ASSUMPTION_BOUNDS["friction_cost"][2]

    def as_kwargs(self) -> dict[str, float]:
        return {
            "fraud_exposure": self.fraud_exposure,
            "review_cost": self.review_cost,
            "friction_cost": self.friction_cost,
        }


@dataclass(frozen=True)
class ScenarioResult:
    """One capacity/rule/assumption combination evaluated against month-7 evidence."""

    capacity: float
    model: str
    candidate: dict[str, Any]
    incumbent: dict[str, Any]
    candidate_utility: float
    assumptions: Assumptions

    @property
    def overflow(self) -> int:
        return int(self.candidate["overflow"])

    @property
    def feasible(self) -> bool:
        """A scenario is operationally feasible only when nothing overflows capacity."""
        return self.overflow == 0


def available_rule_flags(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    return concentration_rule_flags(frame)


def forced_review_mask(frame: pd.DataFrame, rules: tuple[str, ...] | list[str]) -> np.ndarray | None:
    """Applications a rule forces into review, or None when no rule is active."""
    flags = available_rule_flags(frame)
    toggles = {name: name in set(rules) for name in flags}
    return combine_rule_flags(flags, toggles) if any(toggles.values()) else None


def evaluate_scenario(
    frame: pd.DataFrame,
    *,
    model: str,
    capacity: float,
    rules: tuple[str, ...] | list[str],
    assumptions: Assumptions,
    incumbent: str = "incumbent_proxy",
) -> ScenarioResult:
    labels = frame["fraud_bool"].to_numpy()
    forced = forced_review_mask(frame, rules)
    candidate = policy_metrics(labels, frame[model].to_numpy(), capacity, forced_review=forced)
    return ScenarioResult(
        capacity=capacity,
        model=model,
        candidate=candidate,
        incumbent=policy_metrics(labels, frame[incumbent].to_numpy(), capacity),
        candidate_utility=expected_utility(candidate, **assumptions.as_kwargs()),
        assumptions=assumptions,
    )
