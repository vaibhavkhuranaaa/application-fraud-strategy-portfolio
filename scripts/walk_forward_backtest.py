"""Walk-forward backtest: catch rate by period, not one period.

The headline result rests on a single month and 1,428 positives, reported with a bootstrap
interval of 51.0% to 56.2%. That interval answers how much the figure would move on a
resample of that month. It is not the uncertainty a deployment decision needs, which is how
much the figure moves between months, and the two are not close.

Protocol. Each fold tests one period, trains on everything up to two periods before it, and
calibrates on the period immediately before it:

    test 3, train 0-1, calibrate 2
    test 4, train 0-2, calibrate 3
    test 5, train 0-3, calibrate 4
    test 6, train 0-4, calibrate 5
    test 7, train 0-5, calibrate 6

The last fold is the recorded evaluation protocol exactly, so it must reproduce the recorded
month-7 figures. That is the harness validating itself: if fold 7 disagrees with
`evaluation/model_evaluation.json`, this backtest is wrong and not the other way round.

No fold trains on month 7 and no fold selects anything, so the untouched test period stays
untouched in the sense the evaluation contract means. Nothing here is tuned.

Two things are measured per fold rather than one. Catch rate at each capacity, which is the
operating number. And calibration, because the recorded intercept failure has only ever been
observed on one period, and whether it is a period effect or a structural property of how the
gate is parameterised is a different question with a different remedy.

    PYTHONPATH=src uv run python scripts/walk_forward_backtest.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.calibration import (  # noqa: E402
    PriorShift,
    fit_score_reference,
    score_to_probability,
    select_prior_forecast,
)
from fraud_strategy.config import (  # noqa: E402
    CAPACITIES,
    DATASET_VERSION,
    DEFAULT_CURATED_DIR,
    DEFAULT_EVIDENCE_DIR,
    HYBRID_FEATURES,
    INCUMBENT_FEATURE,
)
from fraud_strategy.io import write_json  # noqa: E402
from fraud_strategy.metrics import capacity_summary, metric_summary  # noqa: E402
from fraud_strategy.modeling import (  # noqa: E402
    calibrated_predict,
    code_sha,
    fit_and_select_calibration,
    fit_candidate,
    incumbent_calibration,
    load_base,
)

# Test period, and the periods it may read. The calibration period is the one immediately
# before the test, so the last fold reproduces the recorded protocol.
FOLDS = [
    {"test": 3, "train": [0, 1], "calibrate": 2},
    {"test": 4, "train": [0, 1, 2], "calibrate": 3},
    {"test": 5, "train": [0, 1, 2, 3], "calibrate": 4},
    {"test": 6, "train": [0, 1, 2, 3, 4], "calibrate": 5},
    {"test": 7, "train": [0, 1, 2, 3, 4, 5], "calibrate": 6},
]
OPERATING_CAPACITY = "0.05"


def prior_shift_for(frame: pd.DataFrame, calibrate_month: int) -> PriorShift:
    """The same schedule the program uses, restricted to periods this fold may read."""
    observed = [
        float(frame.loc[frame["month"] == month, "fraud_bool"].mean())
        for month in range(0, calibrate_month + 1)
    ]
    if len(observed) < 4:
        # Too few closed periods to backtest a forecast rule. Carry the last prior forward,
        # which is what the backtest selects on this data anyway.
        return PriorShift(rule="carry_forward", calibration_prior=observed[-1], forecast_prior=observed[-1])
    forecast = select_prior_forecast(observed, backtest_from=3)
    return PriorShift(
        rule=forecast["selected"],
        calibration_prior=observed[-1],
        forecast_prior=forecast["forecast_prior"],
    )


def run_fold(frame: pd.DataFrame, fold: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    train = frame[frame["month"].isin(fold["train"])]
    calibration = frame[frame["month"] == fold["calibrate"]]
    test = frame[frame["month"] == fold["test"]]
    labels = test["fraud_bool"].to_numpy(dtype=np.int8)
    shift = prior_shift_for(frame, fold["calibrate"])

    candidate = fit_candidate("catboost_hybrid", train, HYBRID_FEATURES, parameters)
    calibrator, _, _ = fit_and_select_calibration(candidate, calibration)
    challenger = shift.apply(calibrated_predict(candidate, calibrator, test))

    reference = fit_score_reference(calibration[INCUMBENT_FEATURE].to_numpy())
    incumbent_calibrator, _ = incumbent_calibration(calibration, reference)
    incumbent = shift.apply(
        incumbent_calibrator.predict(score_to_probability(test[INCUMBENT_FEATURE].to_numpy(), reference))
    )

    results: dict[str, Any] = {
        "test_period": fold["test"],
        "train_periods": fold["train"],
        "calibration_period": fold["calibrate"],
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "positives": int(labels.sum()),
        "prevalence": float(labels.mean()),
        "prior_shift": {"rule": shift.rule, "applied_logit_shift": float(shift.shift)},
    }
    for name, probabilities in (("catboost_hybrid", challenger), ("incumbent_proxy", incumbent)):
        capacity = capacity_summary(labels, probabilities)
        metrics = metric_summary(labels, probabilities)
        results[name] = {
            "catch_rate": {key: float(value["catch_rate"]) for key, value in capacity.items()},
            "catch_rate_ci95": {
                key: [float(bound) for bound in value["catch_rate_ci95"]] for key, value in capacity.items()
            },
            "fraud_caught": {key: int(value["fraud_caught"]) for key, value in capacity.items()},
            "pr_auc": metrics["pr_auc"],
            "auroc": metrics["auroc"],
            "calibration_slope": metrics["calibration_slope"],
            "calibration_intercept": metrics["calibration_intercept"],
            "ece": metrics["ece"],
        }
    return results


def summarise(folds: list[dict[str, Any]], recorded: dict[str, Any]) -> dict[str, Any]:
    catch = [fold["catboost_hybrid"]["catch_rate"][OPERATING_CAPACITY] for fold in folds]
    incumbent_catch = [fold["incumbent_proxy"]["catch_rate"][OPERATING_CAPACITY] for fold in folds]
    final = folds[-1]

    recorded_capacity = recorded["month_7_capacity"]["catboost_hybrid"][OPERATING_CAPACITY]
    recorded_catch = float(recorded_capacity["catch_rate"])
    recorded_interval = [float(bound) for bound in recorded_capacity["catch_rate_ci95"]]
    within_width = recorded_interval[1] - recorded_interval[0]
    between_range = max(catch) - min(catch)

    # Two intervals, because they answer different questions and only one of them is the
    # question a deployment decision asks.
    #
    # The confidence interval is for the long-run mean catch rate: "on average, across many
    # periods, where does this land". The prediction interval is for one future period:
    # "what will next month be". A desk forecasting next month's caught-fraud count needs
    # the second, and it is wider by the factor sqrt(1 + 1/n) because a single period varies
    # around the mean as well as the mean being uncertain. Reporting only the confidence
    # interval would understate next-period risk, which is the same class of error as
    # reporting only the within-period bootstrap.
    mean_catch = float(np.mean(catch))
    sd_catch = float(np.std(catch, ddof=1))
    critical = 2.776  # t(0.975, df=4)
    half_width = critical * sd_catch / np.sqrt(len(catch))
    prediction_half_width = critical * sd_catch * np.sqrt(1 + 1 / len(catch))

    reproduces = abs(final["catboost_hybrid"]["catch_rate"][OPERATING_CAPACITY] - recorded_catch) < 1e-9
    intercepts = [fold["catboost_hybrid"]["calibration_intercept"] for fold in folds]
    return {
        "operating_capacity": float(OPERATING_CAPACITY),
        "periods_tested": [fold["test_period"] for fold in folds],
        "catch_rate_by_period": {
            str(fold["test_period"]): value for fold, value in zip(folds, catch, strict=True)
        },
        "incumbent_catch_rate_by_period": {
            str(fold["test_period"]): value for fold, value in zip(folds, incumbent_catch, strict=True)
        },
        "mean_catch_rate": mean_catch,
        "sd_catch_rate": sd_catch,
        "worst_period": {
            "period": folds[int(np.argmin(catch))]["test_period"],
            "catch_rate": float(min(catch)),
        },
        "best_period": {
            "period": folds[int(np.argmax(catch))]["test_period"],
            "catch_rate": float(max(catch)),
        },
        "between_period_range": between_range,
        "mean_catch_rate_interval_95": [mean_catch - half_width, mean_catch + half_width],
        "next_period_prediction_interval_95": [
            mean_catch - prediction_half_width,
            mean_catch + prediction_half_width,
        ],
        "interval_note": (
            "The prediction interval is the one a next-period forecast needs. The confidence "
            "interval describes the long-run mean and is narrower for that reason."
        ),
        "recorded_single_period": {
            "catch_rate": recorded_catch,
            "within_period_interval_95": recorded_interval,
            "within_period_interval_width": within_width,
        },
        "between_over_within": between_range / within_width if within_width else None,
        "final_fold_reproduces_recorded_protocol": reproduces,
        "calibration_intercept_by_period": {
            str(fold["test_period"]): value for fold, value in zip(folds, intercepts, strict=True)
        },
        "calibration_intercept_fails_in_every_period": all(abs(value) > 0.10 for value in intercepts),
    }


def build(curated_dir: Path, evidence_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    frame = load_base(curated_dir)
    recorded = json.loads((evidence_dir / "model_evaluation.json").read_text(encoding="utf-8"))
    parameters = json.loads(
        (Path("artifacts") / "models" / "candidate_model_manifest.json").read_text(encoding="utf-8")
    )["parameters"]

    folds = [run_fold(frame, fold, parameters) for fold in FOLDS]
    summary = summarise(folds, recorded)
    return {
        "evidence_id": "m8-walk-forward-backtest-v1",
        "dataset_version": DATASET_VERSION,
        "code_sha": code_sha(),
        "protocol": {
            "design": "test period t, train periods 0 to t-2, calibrate on t-1",
            "folds": FOLDS,
            "no_fold_trains_on_the_untouched_period": True,
            "final_fold_is_the_recorded_protocol": "train 0-5, calibrate 6, test 7",
            "nothing_selected": "no model, parameter, or threshold is chosen from these results",
        },
        "capacities": [f"{capacity:.2f}" for capacity in CAPACITIES],
        "folds": folds,
        "summary": summary,
        "limitations": [
            "Five test periods on one synthetic dataset. The between-period interval rests on five "
            "observations and is wide for that reason, which is the honest position rather than a defect.",
            "Early folds train on fewer periods than the shipped model, so their results are not a "
            "like-for-like statement about the shipped model's quality in those periods.",
            "Labels are treated as complete at period close. In production they mature over 30 to 90 "
            "days and longer, so a real walk-forward would have less information at each fold than this "
            "one does. See the label-latency record.",
        ],
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated-dir", type=Path, default=DEFAULT_CURATED_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    arguments = parser.parse_args()

    result = build(arguments.curated_dir, arguments.evidence_dir)
    destination = arguments.evidence_dir / "walk_forward_backtest.json"
    write_json(destination, result)
    summary = result["summary"]
    print(f"wrote {destination}")
    print(f"final fold reproduces recorded protocol: {summary['final_fold_reproduces_recorded_protocol']}")
    print(
        f"catch by period: {json.dumps({k: round(v, 4) for k, v in summary['catch_rate_by_period'].items()})}"
    )
    print(f"mean {summary['mean_catch_rate']:.4f}  sd {summary['sd_catch_rate']:.4f}")
    print(
        f"between-period range {summary['between_period_range']:.4f} vs within-period width "
        f"{summary['recorded_single_period']['within_period_interval_width']:.4f} "
        f"({summary['between_over_within']:.2f}x)"
    )
    print(f"intercept fails every period: {summary['calibration_intercept_fails_in_every_period']}")


if __name__ == "__main__":
    main()
