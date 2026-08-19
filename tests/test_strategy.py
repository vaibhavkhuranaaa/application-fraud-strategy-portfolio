import numpy as np

from fraud_strategy.strategy import (
    compare_utility_grid,
    enforce_governance_refusal,
    pareto_frontier,
    policy_metrics,
    rank_review_queue,
)


def test_forced_rules_never_decline_and_surface_overflow() -> None:
    scores = np.array([0.1, 0.9, 0.8, 0.2])
    forced = np.array([True, True, False, False])
    outcome = rank_review_queue(scores, 0.25, forced_review=forced)
    assert set(outcome.actions) <= {"clear", "manual_review", "governance_referral"}
    assert outcome.actions[1] == "manual_review"
    assert outcome.actions[0] == "governance_referral"
    assert outcome.overflow == 1


def test_economic_grid_and_pareto_frontier() -> None:
    labels = np.array([1, 1, 0, 0, 0, 0])
    challenger = policy_metrics(labels, np.array([0.9, 0.8, 0.7, 0.1, 0.1, 0.1]), 0.5)
    incumbent = policy_metrics(labels, np.array([0.9, 0.1, 0.8, 0.7, 0.1, 0.1]), 0.5)
    comparison = compare_utility_grid(challenger, incumbent)
    assert comparison["positive_share"] > 0.8
    rows = [
        {"catch_rate": 0.8, "false_positive_rate": 0.1, "review_rate": 0.1, "utility": 100},
        {"catch_rate": 0.7, "false_positive_rate": 0.2, "review_rate": 0.2, "utility": 50},
    ]
    assert pareto_frontier(rows) == [0]


def test_governance_gates_override_an_economic_frontier_recommendation() -> None:
    result = enforce_governance_refusal(
        {"recommendation": "candidate-policy", "refusal_reasons": []},
        {"calibration": False},
        fairness_review_required=True,
        drift_blocks=2,
    )
    assert result["candidate_frontier_recommendation"] == "candidate-policy"
    assert result["recommendation"] == "no robust recommendation"
    assert len(result["refusal_reasons"]) == 3
