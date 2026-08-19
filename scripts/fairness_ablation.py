"""M7 feature ablation: the measured cost of removing `housing_status`.

`housing_status` is one of the 33 eligible inputs and it carries the largest segment
disparity in the program: a 0.073 review-rate ratio between the two publishable groups,
BA reviewed at 19.13% with 67.4% catch against BC at 1.40% with 29.7%. M7 asks what
removing it costs, and then asks a human to accept or reject the segment findings.

Two things are measured, because either one alone would mislead.

1. The cost. Both arms are fitted on the same months, the same rows, the same seeds and
   the same tuned parameters, so the difference between them is the feature and nothing
   else.
2. The residual disparity. Removing a feature only helps if the disparity goes with it.
   If the remaining inputs recover housing status, removal is cosmetic: the model keeps
   the same behaviour and the program loses the ability to audit the segment it is
   pretending not to use. That is why the proxy-recoverability arm exists.

Protocol. The decision is taken on the rolling-origin folds, which is the evidence the
selection contract already ranks on. Month 7 is computed for the record and is not
allowed to move the decision, exactly as the pre-approved evaluation contract requires. The
materiality thresholds below are fixed in this file before it was first run.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from fraud_strategy.calibration import PriorShift, select_prior_forecast
from fraud_strategy.config import (
    CAPACITIES,
    DATASET_VERSION,
    DEFAULT_CURATED_DIR,
    DEFAULT_EVIDENCE_DIR,
    HYBRID_FEATURES,
    SEED,
)
from fraud_strategy.io import write_json
from fraud_strategy.metrics import capacity_summary, metric_summary, wilson_interval
from fraud_strategy.modeling import (
    CALIBRATION_MONTH,
    ROLLING_FOLDS,
    TEST_MONTH,
    TRAINING_MONTHS,
    calibrated_predict,
    catboost_estimator,
    code_sha,
    deterministic_stratified_sample,
    fairness_report,
    fit_and_select_calibration,
    fit_candidate,
    load_base,
    model_frame,
)

ABLATED_FEATURE = "housing_status"

# Fixed before the first run, and stated so a reviewer can see it was not chosen after
# the result. A loss is "small" only when it is smaller than the program's own ability to
# measure it.
#
# 1.0 percentage point of catch at 5% capacity is about 14 fraud cases on a month-7
# positive count of 1,428. The recorded catch interval at that capacity is 51.0% to
# 56.2%, a half-width of 2.6 points, so a loss under one point cannot be separated from
# sampling noise at the sample size this program has.
#
# 0.005 PR-AUC is under 3% of the hybrid's 0.1727 rolling mean, and smaller than the
# 0.0247 spread across its own three folds.
CATCH_MATERIALITY_AT_5_PERCENT = 0.010
PR_AUC_MATERIALITY = 0.005

# The review-rate ratio gate from the evaluation contract. Reported for both arms so the
# residual disparity is visible next to the cost.
REVIEW_RATE_BAND = (0.80, 1.25)
GAP_TRIGGER = 0.10


def arm_features(include_housing: bool) -> list[str]:
    if include_housing:
        return list(HYBRID_FEATURES)
    return [feature for feature in HYBRID_FEATURES if feature != ABLATED_FEATURE]


def fold_evaluation(
    frame: pd.DataFrame, features: list[str], parameters: dict[str, Any], *, max_train_rows: int = 350_000
) -> dict[str, Any]:
    """Rolling-origin folds with catch rate, not only PR-AUC.

    Seeds match `rolling_catboost_evaluation`, so the with-housing arm reproduces the
    recorded hybrid folds and the two arms see identical rows.
    """
    folds: list[dict[str, Any]] = []
    for index, (train_months, test_months) in enumerate(ROLLING_FOLDS):
        train = deterministic_stratified_sample(
            frame[frame["month"].isin(train_months)], max_train_rows, SEED + 500 + index
        )
        test = frame[frame["month"].isin(test_months)]
        estimator = catboost_estimator(features, parameters)
        estimator.fit(model_frame(train, features), train["fraud_bool"])
        probabilities = np.asarray(estimator.predict_proba(model_frame(test, features))[:, 1], dtype=float)
        labels = test["fraud_bool"].to_numpy(dtype=np.int8)
        capacity = capacity_summary(labels, probabilities)
        folds.append(
            {
                "fold": index + 1,
                "train_months": train_months,
                "test_months": test_months,
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "positives": int(labels.sum()),
                "pr_auc": float(average_precision_score(labels, probabilities)),
                "auroc": float(roc_auc_score(labels, probabilities)),
                "catch_rate": {key: float(value["catch_rate"]) for key, value in capacity.items()},
            }
        )
    pr_aucs = [fold["pr_auc"] for fold in folds]
    return {
        "folds": folds,
        "mean_pr_auc": float(np.mean(pr_aucs)),
        "worst_pr_auc": float(min(pr_aucs)),
        "mean_catch_rate": {
            f"{capacity:.2f}": float(np.mean([fold["catch_rate"][f"{capacity:.2f}"] for fold in folds]))
            for capacity in CAPACITIES
        },
    }


def month_seven_evaluation(
    frame: pd.DataFrame, features: list[str], parameters: dict[str, Any], prior_shift: PriorShift
) -> dict[str, Any]:
    """Confirmatory only. Recorded for the file, never read by the decision rule."""
    train = frame[frame["month"].isin(TRAINING_MONTHS)]
    calibration = frame[frame["month"] == CALIBRATION_MONTH]
    test = frame[frame["month"] == TEST_MONTH]
    candidate = fit_candidate("catboost_hybrid", train, features, parameters)
    calibrator, calibration_record, _ = fit_and_select_calibration(candidate, calibration)
    probabilities = prior_shift.apply(calibrated_predict(candidate, calibrator, test))
    labels = test["fraud_bool"].to_numpy(dtype=np.int8)
    capacity = capacity_summary(labels, probabilities)
    return {
        "calibrator": calibration_record.get("selected", calibration_record.get("method")),
        "metrics": metric_summary(labels, probabilities),
        "capacity": {
            key: {
                "catch_rate": float(value["catch_rate"]),
                "catch_rate_ci95": [float(bound) for bound in value["catch_rate_ci95"]],
                "precision": float(value["precision"]),
                "review_rate": float(value["review_rate"]),
                "fraud_caught": int(value["fraud_caught"]),
            }
            for key, value in capacity.items()
        },
        "fairness": fairness_report(test, labels, probabilities),
    }


def disparity_summary(fairness: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for report in fairness["segments"]:
        published = [row for row in report["groups"] if row["publishable"]]
        summary[report["segment"]] = {
            "published_groups": [row["group"] for row in published],
            "max_min_tpr_gap": report["max_min_tpr_gap"],
            "max_min_fpr_gap": report["max_min_fpr_gap"],
            "review_rate_ratio": report["review_rate_ratio"],
            "group_rows": [
                {
                    "group": row["group"],
                    "positive_labels": row["positive_labels"],
                    "prevalence": row["positive_labels"] / row["rows"] if row["rows"] else None,
                    "tpr": row["tpr"],
                    "fpr": row["fpr"],
                    "review_rate": row["review_rate"],
                }
                for row in published
            ],
        }
    return summary


def proxy_recoverability(
    frame: pd.DataFrame, parameters: dict[str, Any], *, sample_rows: int = 200_000
) -> dict[str, Any]:
    """Can the remaining inputs recover housing status?

    This is the question a less-discriminatory-alternative search has to answer. If a
    group indicator is recoverable from the features that stay, dropping the column
    removes the audit handle and not the behaviour.
    """
    features = arm_features(include_housing=False)
    train = deterministic_stratified_sample(
        frame[frame["month"].isin(TRAINING_MONTHS)], sample_rows, SEED + 700
    )
    test = frame[frame["month"] == TEST_MONTH]
    results: dict[str, Any] = {}
    for group in ("BA", "BC"):
        target = (train[ABLATED_FEATURE] == group).astype(int)
        estimator = catboost_estimator(features, {**parameters, "iterations": 250})
        estimator.fit(model_frame(train, features), target)
        scores = np.asarray(estimator.predict_proba(model_frame(test, features))[:, 1], dtype=float)
        truth = (test[ABLATED_FEATURE] == group).astype(int).to_numpy()
        results[group] = {
            "auroc": float(roc_auc_score(truth, scores)),
            "pr_auc": float(average_precision_score(truth, scores)),
            "base_rate": float(truth.mean()),
        }
    return {
        "target": f"{ABLATED_FEATURE} membership",
        "predictors": "the 32 remaining hybrid inputs",
        "train_rows": int(len(train)),
        "test_month": TEST_MONTH,
        "groups": results,
    }


def build(curated_dir: Path, evidence_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    frame = load_base(curated_dir)

    checkpoint = joblib.load(evidence_dir / "work" / "model_selection.joblib")
    parameters = checkpoint["best_parameters"]

    observed_priors = [
        float(frame.loc[frame["month"] == month, "fraud_bool"].mean())
        for month in range(0, CALIBRATION_MONTH + 1)
    ]
    forecast = select_prior_forecast(observed_priors, backtest_from=ROLLING_FOLDS[0][1][0])
    prior_shift = PriorShift(
        rule=forecast["selected"],
        calibration_prior=observed_priors[-1],
        forecast_prior=forecast["forecast_prior"],
    )

    arms: dict[str, Any] = {}
    for label, include in (("with_housing", True), ("without_housing", False)):
        features = arm_features(include)
        rolling = fold_evaluation(frame, features, parameters)
        month_seven = month_seven_evaluation(frame, features, parameters, prior_shift)
        arms[label] = {
            "features": features,
            "feature_count": len(features),
            "rolling": rolling,
            "month_7": {
                "calibrator": month_seven["calibrator"],
                "metrics": month_seven["metrics"],
                "capacity": month_seven["capacity"],
            },
            "segments": disparity_summary(month_seven["fairness"]),
            "governance_review": month_seven["fairness"]["governance_review"],
            "governance_reasons": month_seven["fairness"]["reasons"],
        }

    kept, dropped = arms["with_housing"], arms["without_housing"]
    catch_delta = {
        key: kept["rolling"]["mean_catch_rate"][key] - dropped["rolling"]["mean_catch_rate"][key]
        for key in kept["rolling"]["mean_catch_rate"]
    }
    pr_auc_delta = kept["rolling"]["mean_pr_auc"] - dropped["rolling"]["mean_pr_auc"]
    catch_cost_at_5 = catch_delta["0.05"]
    material = catch_cost_at_5 > CATCH_MATERIALITY_AT_5_PERCENT or pr_auc_delta > PR_AUC_MATERIALITY

    month_7_catch_delta = {
        key: kept["month_7"]["capacity"][key]["catch_rate"]
        - dropped["month_7"]["capacity"][key]["catch_rate"]
        for key in kept["month_7"]["capacity"]
    }
    month_7_positives = int(
        round(
            kept["month_7"]["capacity"]["0.05"]["fraud_caught"]
            / max(kept["month_7"]["capacity"]["0.05"]["catch_rate"], 1e-9)
        )
    )

    return {
        "evidence_id": "m7-fairness-ablation-v1",
        "dataset_version": DATASET_VERSION,
        "code_sha": code_sha(),
        "ablated_feature": ABLATED_FEATURE,
        "protocol": {
            "decision_basis": "rolling-origin folds only",
            "confirmatory_only": f"month {TEST_MONTH}",
            "paired": "identical months, rows, seeds, and tuned parameters across both arms",
            "tuning_reused": "the M6 selection checkpoint; no retuning against any period",
        },
        "pre_registered_materiality": {
            "catch_rate_at_5_percent_capacity": CATCH_MATERIALITY_AT_5_PERCENT,
            "mean_rolling_pr_auc": PR_AUC_MATERIALITY,
            "fixed_before_execution": True,
            "rationale": (
                "One point of catch at 5% capacity is about 14 month-7 fraud cases against a "
                "recorded catch interval half-width of 2.6 points, so a smaller loss is not "
                "separable from sampling noise. 0.005 PR-AUC is under 3% of the hybrid's rolling "
                "mean and smaller than its own across-fold spread."
            ),
        },
        "arms": arms,
        "cost": {
            "rolling_mean_pr_auc_delta": pr_auc_delta,
            "rolling_mean_catch_rate_delta": catch_delta,
            "catch_rate_cost_at_5_percent": catch_cost_at_5,
            "month_7_catch_rate_delta": month_7_catch_delta,
            "month_7_fraud_cases_at_5_percent": (
                kept["month_7"]["capacity"]["0.05"]["fraud_caught"]
                - dropped["month_7"]["capacity"]["0.05"]["fraud_caught"]
            ),
            "month_7_positive_labels": month_7_positives,
            "month_7_catch_delta_ci95_at_5_percent": [
                float(bound)
                for bound in wilson_interval(
                    abs(
                        kept["month_7"]["capacity"]["0.05"]["fraud_caught"]
                        - dropped["month_7"]["capacity"]["0.05"]["fraud_caught"]
                    ),
                    month_7_positives,
                )
            ],
            "material": bool(material),
        },
        "proxy_recoverability": proxy_recoverability(frame, parameters),
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated-dir", type=Path, default=DEFAULT_CURATED_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    arguments = parser.parse_args()

    result = build(arguments.curated_dir, arguments.evidence_dir)
    destination = arguments.evidence_dir / "fairness_ablation.json"
    write_json(destination, result)

    cost = result["cost"]
    print(f"wrote {destination}")
    print(f"rolling catch cost at 5% capacity: {cost['catch_rate_cost_at_5_percent']:+.4f}")
    print(f"rolling mean PR-AUC cost:          {cost['rolling_mean_pr_auc_delta']:+.4f}")
    print(f"material under pre-registered thresholds: {cost['material']}")
    for label, arm in result["arms"].items():
        housing = arm["segments"].get("housing_status", {})
        print(
            f"{label:16s} review-rate ratio {housing.get('review_rate_ratio')} "
            f"tpr gap {housing.get('max_min_tpr_gap')}"
        )
    for group, values in result["proxy_recoverability"]["groups"].items():
        print(f"proxy recoverability {group}: AUROC {values['auroc']:.4f}")


if __name__ == "__main__":
    main()
