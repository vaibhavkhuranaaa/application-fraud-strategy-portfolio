import pytest
from pydantic import ValidationError

from fraud_strategy.contracts import StrategyResult


def test_overflow_requires_explicit_refusal() -> None:
    with pytest.raises(ValidationError):
        StrategyResult(
            model_version="model-v1",
            policy_version="policy-v1",
            catch_rate=0.5,
            false_positive_rate=0.01,
            review_rate=0.03,
            queue_size=30,
            overflow=2,
            expected_utility_interval=(1.0, 2.0),
            segment_impacts={},
            frontier_position=None,
            recommendation="use policy",
            refusal_reasons=[],
            evidence_source="baf_base",
        )


def test_strategy_result_accepts_bounded_refusal() -> None:
    result = StrategyResult(
        model_version="model-v1",
        policy_version="policy-v1",
        catch_rate=0.5,
        false_positive_rate=0.01,
        review_rate=0.03,
        queue_size=30,
        overflow=2,
        expected_utility_interval=(1.0, 2.0),
        segment_impacts={},
        frontier_position=None,
        recommendation="no robust recommendation",
        refusal_reasons=["capacity exceeded"],
        evidence_source="baf_base",
    )
    assert result.overflow == 2
