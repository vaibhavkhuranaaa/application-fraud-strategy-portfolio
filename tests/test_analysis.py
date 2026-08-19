from pathlib import Path

import pytest

from fraud_strategy.analysis.evidence import (
    EvidencePaths,
    analysis_frame,
    humanize_reason,
    load_bundle,
    source_label,
)
from fraud_strategy.analysis.scenarios import Assumptions, evaluate_scenario, forced_review_mask

EVIDENCE = EvidencePaths()


def _bundle():
    bundle = load_bundle(EVIDENCE)
    if bundle.gaps:
        pytest.skip(f"local evidence artifacts absent: {[gap.path for gap in bundle.gaps]}")
    return bundle


def _frame():
    _bundle()
    try:
        return analysis_frame(EVIDENCE)
    except FileNotFoundError as error:
        pytest.skip(str(error))


def test_missing_evidence_reports_a_gap_with_a_recovery_command(tmp_path: Path) -> None:
    bundle = load_bundle(EvidencePaths(evidence_dir=tmp_path, artifact_dir=tmp_path, curated_dir=tmp_path))
    assert not bundle.complete
    assert {gap.label for gap in bundle.gaps} >= {"Model and strategy evidence"}
    assert all(gap.recovery for gap in bundle.gaps)
    # A missing artifact must never be reported as a passing or recommended state.
    assert bundle.recommendation == "unavailable"
    assert bundle.champion == "unavailable"


def test_bundle_preserves_the_recorded_refusal_and_retained_champion() -> None:
    bundle = _bundle()
    assert bundle.refused
    assert bundle.recommendation == "no robust recommendation"
    assert bundle.champion == "incumbent_proxy"
    assert bundle.challenger == "catboost_hybrid"
    assert bundle.failed_gates, "a refusal must be explained by at least one failed gate"
    assert bundle.refusal_reasons


def test_refusal_reasons_are_rendered_without_raw_gate_identifiers() -> None:
    bundle = _bundle()
    for reason in bundle.refusal_reasons:
        assert "calibration_intercept_abs_at_most_0_10" not in reason
        assert "_" not in reason.replace("non-binding", ""), reason


def test_humanize_reason_keeps_the_statement_and_replaces_the_identifier() -> None:
    reason = "Model promotion gates failed: calibration_intercept_abs_at_most_0_10."
    humanized = humanize_reason(reason)
    assert humanized.startswith("Model promotion gates failed:")
    assert "calibration intercept within 0.10 of zero" in humanized


def test_scenarios_reproduce_the_recorded_month_seven_policies() -> None:
    frame = _frame()
    bundle = _bundle()
    recorded = {policy["policy_id"]: policy for policy in bundle.model["strategy_frontier"]["policies"]}
    all_rules = (
        "dob_email_concentration",
        "device_email_concentration",
        "foreign_low_identity_similarity",
        "branch_concentration",
    )
    for capacity, rules in ((0.01, ()), (0.05, ()), (0.05, all_rules), (0.10, ())):
        result = evaluate_scenario(
            frame,
            model="catboost_hybrid",
            capacity=capacity,
            rules=rules,
            assumptions=Assumptions(),
        )
        policy = recorded[f"capacity-{capacity:.2f}-rules-{str(bool(rules)).lower()}"]
        assert result.candidate["catch_rate"] == pytest.approx(policy["catch_rate"])
        assert result.candidate["false_positive_count"] == policy["false_positive_count"]
        assert result.overflow == policy["overflow"]
        assert result.candidate_utility == pytest.approx(policy["utility"])


def test_rule_enabled_policy_overflows_and_stays_infeasible() -> None:
    frame = _frame()
    result = evaluate_scenario(
        frame,
        model="catboost_hybrid",
        capacity=0.05,
        rules=(
            "dob_email_concentration",
            "device_email_concentration",
            "foreign_low_identity_similarity",
            "branch_concentration",
        ),
        assumptions=Assumptions(),
    )
    assert result.overflow > 0
    assert not result.feasible


def test_rules_only_force_review_and_never_decline() -> None:
    """A concentration rule may pull a case into review. It has no other power."""
    frame = _frame()
    assert forced_review_mask(frame, ()) is None
    forced = forced_review_mask(frame, ("branch_concentration",))
    assert forced is not None
    assert forced.dtype == bool
    assert 0 < int(forced.sum()) < len(frame)


def test_assumptions_change_scenario_value_but_not_observed_counts() -> None:
    frame = _frame()
    base = evaluate_scenario(
        frame,
        model="catboost_hybrid",
        capacity=0.05,
        rules=(),
        assumptions=Assumptions(),
    )
    altered = evaluate_scenario(
        frame,
        model="catboost_hybrid",
        capacity=0.05,
        rules=(),
        assumptions=Assumptions(fraud_exposure=5_000.0, review_cost=27.0, friction_cost=300.0),
    )
    assert altered.candidate["fraud_caught"] == base.candidate["fraud_caught"]
    assert altered.candidate["catch_rate"] == base.candidate["catch_rate"]
    assert altered.candidate_utility != base.candidate_utility


def test_confidence_intervals_exist_only_for_the_approved_capacities() -> None:
    """Intervals were bootstrapped for score-only policies at four capacities.

    Anything else has none, and a surface must say so rather than borrow one that
    describes a different policy.
    """
    bundle = _bundle()
    recorded = bundle.model["month_7_capacity"]["catboost_hybrid"]
    assert set(recorded) == {"0.01", "0.03", "0.05", "0.10"}
    for level, entry in recorded.items():
        lower, upper = entry["catch_rate_ci95"]
        assert lower < entry["catch_rate"] < upper, level


def test_source_labels_cover_every_evidence_source_in_the_record() -> None:
    bundle = _bundle()
    sources = {variant["evidence_source"] for variant in bundle.model["variant_stress_tests"]}
    sources.add(bundle.linking["evidence_source"])
    sources.update(record["evidence_source"] for record in bundle.curation["files"])
    for source in sources:
        assert source_label(source) != source, f"{source} has no plain-language label"
