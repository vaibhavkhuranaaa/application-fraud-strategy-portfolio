import json
from pathlib import Path


def load(name: str) -> dict:
    return json.loads(Path(name).read_text(encoding="utf-8"))


def test_versioned_m3_evidence_preserves_the_governance_refusal() -> None:
    model = load("evaluation/model_evaluation.json")
    assert model["selected_challenger"] == "catboost_hybrid"
    assert model["approval_state"] == "rejected"
    assert model["champion"] == "incumbent_proxy"
    assert model["champion_approval_state"] == "retained_baseline"
    assert model["strategy_frontier"]["recommendation"] == "no robust recommendation"
    assert not model["promotion_gates"]["calibration_intercept_abs_at_most_0_10"]
    assert not model["promotion_gates"]["no_automatic_promotion_psi_blocks"]
    assert "application_id" not in json.dumps(model["explanations"])
    # The refusal must survive the fairness acceptance of 2026-08-10. Two gates still fail
    # independently, so the challenger stays rejected and the incumbent stays champion.
    assert len(model["strategy_frontier"]["refusal_reasons"]) >= 2
    assert sum(model["promotion_gates"].values()) == 9


def test_retained_baseline_is_a_controlled_temporary_disposition() -> None:
    governance = load("evaluation/risk_governance.json")
    disposition = governance["incumbent_disposition"]

    assert governance["decision"] == "no robust recommendation"
    assert governance["production_readiness"] == "not established"
    assert disposition["status"] == "temporary ranking baseline"
    assert "not approved" in disposition["approval_state"]
    assert disposition["permitted_use"] and disposition["prohibited_use"]
    assert disposition["owner_role"] and disposition["review_cadence"]
    assert disposition["compensating_controls"] and disposition["escalation_triggers"]
    assert disposition["exit_criteria"]
    prohibited = " ".join(disposition["prohibited_use"]).lower()
    assert "automatic" in prohibited and "probability" in prohibited


def test_decision_uncertainty_is_paired_and_positive_in_every_temporal_fold() -> None:
    uncertainty = load("evaluation/risk_governance.json")["uncertainty"]

    assert uncertainty["capacity"] == 0.05
    assert uncertainty["fraud_caught_delta"]["estimate"] == 472
    assert uncertainty["good_reviewed_delta"]["estimate"] == -472
    assert uncertainty["fraud_caught_delta"]["paired_interval_95"][0] > 0
    assert uncertainty["positive_temporal_folds"] == 5
    assert len(uncertainty["temporal_folds"]) == 5
    assert all(row["incremental_caught"] > 0 for row in uncertainty["temporal_folds"])
    assert "paired row bootstrap" in uncertainty["method"].lower()
    assert uncertainty["status"] == "decision evidence, not a promotion gate"


def test_every_concentration_rule_has_incrementality_and_a_safe_disposition() -> None:
    rows = load("evaluation/risk_governance.json")["rule_dispositions"]

    assert len(rows) == 4
    assert {row["disposition"] for row in rows} <= {"keep", "refer", "reject"}
    assert all(row["incremental_fraud_caught"] < 0 for row in rows)
    assert all(row["unique_fraud_added"] >= 0 for row in rows)
    assert all(row["fraud_displaced"] >= row["unique_fraud_added"] for row in rows)
    assert all(row["overlap_with_model_queue"] >= 0 for row in rows)
    assert all(row["overlap_with_other_rules"] >= 0 for row in rows)
    assert all("never automatic decline" in row["policy_boundary"].lower() for row in rows)
    assert next(row for row in rows if row["key"] == "dob_email_concentration")["queue_overflow"] > 0


def test_monitoring_map_has_seven_role_assigned_controls_and_honest_data_states() -> None:
    governance = load("evaluation/risk_governance.json")
    controls = governance["monitoring_controls"]
    required = {
        "availability",
        "owner_role",
        "cadence",
        "threshold_basis",
        "trigger",
        "action",
        "evidence_source",
        "limitation",
    }

    assert {row["key"] for row in controls} == {
        "calibration",
        "stability",
        "review_yield",
        "capacity",
        "friction",
        "label_maturity",
        "segments",
    }
    assert all(required <= row.keys() for row in controls)
    assert all(row["owner_role"] for row in controls)
    assert sum(row["availability"] == "needs production data" for row in controls) == 3
    assert len(governance["reopen_decision_when"]) == 4


def test_risk_product_review_meets_the_pre_registered_threshold_without_a_production_claim() -> None:
    review = load("evaluation/risk_product_review.json")

    assert review["total_score"] >= review["target"] == 9.0
    assert min(row["score"] for row in review["dimensions"]) >= review["minimum_dimension"]
    assert {row["name"] for row in review["dimensions"]} == {
        "Decision integrity",
        "Model evidence",
        "Risk disposition",
        "Operational utility",
        "Evidence honesty",
    }
    assert review["production_readiness"] == "not established"
    assert review["production_evidence_needed"]


def test_the_fairness_gate_passes_by_acceptance_not_by_the_disparity_vanishing() -> None:
    """The dangerous failure mode after a governance acceptance is a silent green tick.

    A reader must still be able to see the gaps that were accepted, who accepted them, and
    when. If the acceptance ever starts working by suppressing the warnings rather than by
    recording a judgment over them, this fails.
    """
    fairness = load("evaluation/model_evaluation.json")["fairness"]
    assert fairness["governance_review"] is False
    assert len(fairness["reasons"]) == 5, "the measured warnings must still be reported"
    assert set(fairness["accepted_reasons"]) == set(fairness["reasons"])
    assert fairness["outstanding_reasons"] == []
    assert fairness["lapsed_reasons"] == []

    acceptance = fairness["governance_acceptance"]
    assert acceptance["accountable"] and acceptance["date"]
    assert "retained" in acceptance["feature_decision"]

    # The disparities themselves are unchanged by the acceptance.
    housing = next(s for s in fairness["segments"] if s["segment"] == "housing_status")
    assert housing["max_min_tpr_gap"] > 0.10
    assert not 0.80 <= housing["review_rate_ratio"] <= 1.25


def test_the_stakeholder_surface_says_the_differences_were_accepted() -> None:
    payload = load("dashboard/data/dashboard.json")
    assert payload["decision"]["status"] == "refused"
    assert payload["decision"]["checks_passed"] == 9
    acceptance = payload["analyst"]["fairness_acceptance"]
    assert acceptance and acceptance["date"] and acceptance["decision"] == "accepted"


def test_dashboard_interactions_preserve_the_refusal_and_progressively_disclose_evidence() -> None:
    page = Path("dashboard/index.html").read_text(encoding="utf-8")
    script = Path("dashboard/app.js").read_text(encoding="utf-8")

    assert "Governance position stays unchanged" in page
    assert "Scenario arithmetic cannot turn the recorded refusal into approval" in page
    assert '<details class="operational"' in page
    assert '<details class="analyst"' in page
    assert '<details class="operational" id="risk-controls"' in page
    assert 'id="risk-disposition-heading"' in page
    assert 'id="scenario-uncertainty"' in page
    assert "cases.slice(0, STATE.queueLimit)" in script
    assert "renderRiskDisposition" in script and "renderRiskControls" in script
    assert "Data unavailable" in script and "Retry loading evidence" in script


def test_dashboard_payload_carries_the_complete_director_of_risk_view() -> None:
    payload = load("dashboard/data/dashboard.json")
    governance = payload["governance"]

    assert payload["decision"]["status"] == "refused"
    assert governance["incumbent_disposition"]["status"] == "temporary ranking baseline"
    assert governance["uncertainty"]["fraud_caught_delta"]["paired_interval_95"][0] > 0
    assert len(governance["rule_dispositions"]) == 4
    assert len(governance["monitoring_controls"]) == 7
    assert governance["reopen_decision_when"]


def test_dashboard_embeds_the_reviewed_payload_before_using_the_network_fallback() -> None:
    """The static exhibit must also work when index.html is opened directly from disk."""
    page = Path("dashboard/index.html").read_text(encoding="utf-8")
    script = Path("dashboard/app.js").read_text(encoding="utf-8")
    start = page.index('<script type="application/json" id="dashboard-data">')
    start = page.index(">", start) + 1
    end = page.index("</script><!--data:end-->", start)

    assert json.loads(page[start:end]) == load("dashboard/data/dashboard.json")
    assert script.index('document.getElementById("dashboard-data")') < script.index(
        'fetch("data/dashboard.json")'
    )
    assert 'rel="preload" href="data/dashboard.json"' not in page


def test_linear_comparator_is_not_sitting_on_the_base_rate_solution() -> None:
    """Guard the M6 correction.

    The comparator this replaces returned AUROC 0.5156 and a PR-AUC at the prevalence floor
    for five milestones, and nothing in the suite would have noticed. A baseline that cannot
    separate the classes silently flatters every challenger measured against it.
    """
    model = load("evaluation/model_evaluation.json")
    linear = model["month_7_metrics"]["regularized_logistic"]
    assert linear["auroc"] > 0.80
    assert linear["pr_auc"] > 5 * linear["prevalence"]
    folds = model["fold_selection"]["regularized_logistic"]
    assert all(fold["converged"] for fold in folds["folds"])
    assert all(fold["pr_auc"] > 0.05 for fold in folds["folds"])


def test_stability_is_measured_against_the_pooled_training_window() -> None:
    drift = load("evaluation/model_evaluation.json")["drift"]
    assert drift["reference_window"] == [0, 1, 2, 3, 4, 5]
    assert all("in_training_window" in row for row in drift["rows"])


def test_calibration_schedule_forecasts_only_from_periods_the_model_may_read() -> None:
    schedule = load("evaluation/model_evaluation.json")["calibration_schedule"]
    assert schedule["fitted_on"] == [6]
    assert max(schedule["backtest_periods"]) < 7
    assert schedule["selected"] in schedule["rules"]
    assert schedule["applied"]["rule"] == schedule["selected"]


def test_versioned_linking_and_curation_evidence_meets_m3_contract() -> None:
    linking = load("evaluation/linking_evaluation.json")
    curation = load("evaluation/data_curation.json")
    assert linking["evidence_source"] == "synthetic_link_fixture"
    assert linking["all_gates_pass"]
    assert linking["summary"]["0.15"]["pairwise_f1_min"] >= 0.80
    assert linking["summary"]["0.15"]["false_merge_rate_max"] <= 0.02
    assert curation["total_rows"] == 6_000_000
    assert len(curation["files"]) == 6
    assert all(item["rows"] == 1_000_000 for item in curation["files"])


def test_small_groups_are_withheld_in_the_public_payload_not_only_in_the_page() -> None:
    """Guard the M7 finding.

    The renderer hid the rate and printed the count, so a six-application group read as
    zero fraud, and the payload is a public static file that shipped both regardless.
    Withholding has to happen where the number is written, not where it is displayed.
    """
    payload = load("dashboard/data/dashboard.json")
    withheld = [
        group for segment in payload["segments"] for group in segment["groups"] if not group["publishable"]
    ]
    assert withheld, "the payload contains groups below the publication threshold"
    for group in withheld:
        assert group["fraud"] is None
        assert group["fraud_rate"] is None
    for segment in payload["segments"]:
        for group in segment["groups"]:
            if group["publishable"]:
                assert group["fraud"] >= 200


def test_housing_ablation_measures_both_the_cost_and_the_residual_disparity() -> None:
    """Guard the M7 measurement.

    A cost figure on its own would have justified either decision. The residual disparity
    is what shows removal is a partial mitigation rather than a fix, and the proxy result
    is what explains why it stays partial.
    """
    ablation = load("evaluation/fairness_ablation.json")
    assert ablation["ablated_feature"] == "housing_status"
    assert ablation["pre_registered_materiality"]["fixed_before_execution"]
    assert ablation["protocol"]["decision_basis"] == "rolling-origin folds only"

    kept, dropped = ablation["arms"]["with_housing"], ablation["arms"]["without_housing"]
    assert len(kept["features"]) - len(dropped["features"]) == 1
    assert "housing_status" not in dropped["features"]

    # Both arms still trigger governance review, so no engineering path closes the check.
    assert kept["governance_review"] and dropped["governance_review"]

    cost = ablation["cost"]
    assert cost["material"] is True
    assert cost["catch_rate_cost_at_5_percent"] > cost["rolling_mean_pr_auc_delta"] > 0

    housing_kept = kept["segments"]["housing_status"]
    housing_dropped = dropped["segments"]["housing_status"]
    assert housing_dropped["review_rate_ratio"] > housing_kept["review_rate_ratio"]
    assert housing_dropped["max_min_tpr_gap"] < housing_kept["max_min_tpr_gap"]
    # Removal is not a fix: the review-rate ratio is still outside the contract band.
    assert not 0.80 <= housing_dropped["review_rate_ratio"] <= 1.25

    # Group membership survives the removal, which is why the disparity does too.
    for values in ablation["proxy_recoverability"]["groups"].values():
        assert values["auroc"] > 0.70


def test_ci_runs_the_public_repository_quality_contract() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    for command in (
        "uv sync --locked",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run pytest",
    ):
        assert command in workflow
