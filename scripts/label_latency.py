"""Label latency, and what it does to the M6 recalibration trigger.

The whole temporal design assumes a period's labels are complete when the period closes.
They are not. Application fraud surfaces through first-payment default at roughly 30 to 45
days, never-pay at 60 to 90, and confirmed identity theft at 60 to 180 and beyond. At the
moment a period closes, none of its applications have had a payment fall due, so that
period's fraud rate is very nearly unobservable.

M6 added an operating control on top of that assumption: recalibrate at period close, and
raise a review when the observed prior moves more than 0.10 in logit from the calibration
prior. This measures what censoring does to that control.

The maturity curve here is stated, not measured. BAF carries no label timestamps, so no
vintage curve can be derived from it, and inventing one from the data would be worse than
declaring one. The shape below is structured on the documented mechanisms rather than
fitted, and every conclusion is a conditional statement about that shape.

One distinction the arithmetic depends on. Latency is a delay: the label arrives eventually.
Under-labelling is different: synthetic identity fraud frequently never receives a fraud
label at all and charges off as credit loss, so a share of true fraud is permanently
recorded as a good customer. That is target misclassification, not delay, and it behaves
differently in the trigger. A constant under-labelling share scales both priors in a
comparison by the same factor and cancels out of their difference, so it biases the level
without biasing the move. Maturity does not cancel, because the two periods being compared
are at different ages.

    PYTHONPATH=src uv run python scripts/label_latency.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.config import DATASET_VERSION, DEFAULT_EVIDENCE_DIR  # noqa: E402
from fraud_strategy.io import write_json  # noqa: E402
from fraud_strategy.modeling import code_sha  # noqa: E402

# Cumulative share of a cohort's eventually-labelled fraud that is known by this many
# periods after the cohort closes. Stated from the documented mechanisms, not fitted:
# nothing is due at close, first-payment default lands in the first period after, never-pay
# and straight-rollers through the second and third, and confirmed identity theft trails for
# months behind that.
MATURITY_CURVE = {0: 0.00, 1: 0.35, 2: 0.60, 3: 0.78, 4: 0.86, 6: 0.92, 12: 1.00}

# Share of true fraud that never receives a fraud label and charges off as credit loss.
# Declared, like the maturity curve. It is carried separately because it is a different
# failure with different behaviour.
NEVER_LABELLED_SHARE = 0.15

TRIGGER_LOGIT = 0.10


def maturity(periods_after_close: int) -> float:
    known = sorted(MATURITY_CURVE)
    if periods_after_close >= known[-1]:
        return MATURITY_CURVE[known[-1]]
    lower = max(point for point in known if point <= periods_after_close)
    upper = min(point for point in known if point >= periods_after_close)
    if lower == upper:
        return MATURITY_CURVE[lower]
    span = upper - lower
    weight = (periods_after_close - lower) / span
    return MATURITY_CURVE[lower] + weight * (MATURITY_CURVE[upper] - MATURITY_CURVE[lower])


def logit(value: float) -> float:
    return float(np.log(value / (1 - value)))


def observed_prior(true_prior: float, periods_after_close: int) -> float:
    """What the desk can actually see for a cohort of this age."""
    return true_prior * maturity(periods_after_close) * (1 - NEVER_LABELLED_SHARE)


def trigger_analysis(priors: list[float], lag: int) -> dict[str, Any]:
    """Run the M6 trigger on censored priors at a given reporting lag.

    At lag L the desk compares the cohort that closed L periods ago against the one before
    it, so the two cohorts are L and L+1 periods old and carry different maturity.
    """
    rows: list[dict[str, Any]] = []
    for index in range(1, len(priors)):
        true_move = logit(priors[index]) - logit(priors[index - 1])
        newer = observed_prior(priors[index], lag)
        older = observed_prior(priors[index - 1], lag + 1)
        if newer <= 0 or older <= 0:
            observed_move = None
            fires = None
        else:
            observed_move = logit(newer) - logit(older)
            fires = abs(observed_move) > TRIGGER_LOGIT
        rows.append(
            {
                "transition": f"{index - 1} to {index}",
                "true_move_logit": true_move,
                "true_fires": abs(true_move) > TRIGGER_LOGIT,
                "observed_move_logit": observed_move,
                "observed_fires": fires,
                "agrees": None if fires is None else fires == (abs(true_move) > TRIGGER_LOGIT),
            }
        )
    decided = [row for row in rows if row["agrees"] is not None]
    ratio = maturity(lag) / maturity(lag + 1) if maturity(lag + 1) else None
    return {
        "reporting_lag_periods": lag,
        "cohort_maturity": maturity(lag),
        "comparison_cohort_maturity": maturity(lag + 1),
        # Under-labelling scales both cohorts identically and cancels here. Maturity does
        # not, because the two cohorts are different ages. This is the whole bias.
        "differential_bias_logit": float(np.log(ratio)) if ratio else None,
        "bias_versus_trigger_threshold": (abs(float(np.log(ratio))) / TRIGGER_LOGIT if ratio else None),
        "transitions": rows,
        "decisions_available": len(decided),
        "decisions_agreeing_with_true_priors": sum(1 for row in decided if row["agrees"]),
    }


def corrected_trigger(priors: list[float], lag: int) -> dict[str, Any]:
    """The repair: divide the observed rate by the maturity the curve says it has.

    This recovers the true prior exactly when the curve is right, which is the whole
    caveat. It converts an unstated assumption that labels are complete into a stated
    assumption about how they arrive, which is the improvement available without label
    timestamps.
    """
    agree = 0
    rows: list[dict[str, Any]] = []
    for index in range(1, len(priors)):
        true_move = logit(priors[index]) - logit(priors[index - 1])
        newer_raw, older_raw = observed_prior(priors[index], lag), observed_prior(priors[index - 1], lag + 1)
        newer_factor = maturity(lag) * (1 - NEVER_LABELLED_SHARE)
        older_factor = maturity(lag + 1) * (1 - NEVER_LABELLED_SHARE)
        if newer_raw <= 0 or older_raw <= 0 or not newer_factor or not older_factor:
            rows.append(
                {"transition": f"{index - 1} to {index}", "corrected_move_logit": None, "agrees": None}
            )
            continue
        corrected_move = logit(newer_raw / newer_factor) - logit(older_raw / older_factor)
        agrees = (abs(corrected_move) > TRIGGER_LOGIT) == (abs(true_move) > TRIGGER_LOGIT)
        agree += int(agrees)
        rows.append(
            {
                "transition": f"{index - 1} to {index}",
                "corrected_move_logit": corrected_move,
                "true_move_logit": true_move,
                "agrees": agrees,
            }
        )
    decided = [row for row in rows if row["agrees"] is not None]
    return {
        "reporting_lag_periods": lag,
        "transitions": rows,
        "decisions_available": len(decided),
        "decisions_agreeing_with_true_priors": agree,
    }


def build(evidence_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    kpi = json.loads((evidence_dir / "monthly_kpi.json").read_text(encoding="utf-8"))
    rows = [row for row in kpi["monthly"] if not row["model_version"].startswith("incumbent")]
    priors = [row["fraud_attempts"] / row["applications"] for row in rows]

    lags = [0, 1, 2, 3, 6]
    censored = [trigger_analysis(priors, lag) for lag in lags]
    corrected = [corrected_trigger(priors, lag) for lag in lags if maturity(lag) > 0]
    usable = next(
        (
            item["reporting_lag_periods"]
            for item in censored
            if item["differential_bias_logit"] is not None
            and abs(item["differential_bias_logit"]) < TRIGGER_LOGIT
        ),
        None,
    )
    return {
        "evidence_id": "m8-label-latency-v1",
        "dataset_version": DATASET_VERSION,
        "code_sha": code_sha(),
        "status": "stated model, not measured. BAF carries no label timestamps.",
        "assumptions": {
            "maturity_curve": {str(key): value for key, value in MATURITY_CURVE.items()},
            "maturity_basis": (
                "First-payment default at roughly 30 to 45 days, never-pay and straight-rollers "
                "through 60 to 90, confirmed identity theft trailing from 60 to 180 days and beyond. "
                "Nothing is due at period close, so a just-closed cohort is unobservable."
            ),
            "never_labelled_share": NEVER_LABELLED_SHARE,
            "never_labelled_basis": (
                "Synthetic identity fraud frequently never receives a fraud label and charges off as "
                "credit loss. This is target misclassification rather than delay."
            ),
            "trigger_threshold_logit": TRIGGER_LOGIT,
        },
        "observed_priors": priors,
        "censored_trigger": censored,
        "corrected_trigger": corrected,
        "minimum_lag_where_bias_is_below_the_threshold": usable,
        "observable_inside_the_latency_window": [
            {
                "signal": "Score distribution stability",
                "latency": "immediate",
                "why": "computed from scores alone and needs no label.",
            },
            {
                "signal": "Review rate and queue composition",
                "latency": "immediate",
                "why": "a property of the policy and the score, not of outcomes.",
            },
            {
                "signal": "Reviewer hit rate, confirmed fraud per case worked",
                "latency": "days",
                "why": (
                    "a review confirms fraud at review time. This is the leading indicator, and the "
                    "monthly pack already reports it."
                ),
            },
            {
                "signal": "Catch rate",
                "latency": "30 to 90 days and longer",
                "why": (
                    "its numerator is review-confirmed and fast, but its denominator is all fraud "
                    "including what slipped through, which is exactly the slow part. Catch rate is a "
                    "lagging indicator and the monthly pack should not be read as current."
                ),
            },
            {
                "signal": "Observed prior, and therefore the recalibration trigger",
                "latency": "30 to 90 days and longer",
                "why": "it is the same denominator problem as catch rate.",
            },
        ],
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    arguments = parser.parse_args()
    result = build(arguments.evidence_dir)
    write_json(arguments.evidence_dir / "label_latency.json", result)

    print(f"{'lag':>5}{'maturity':>10}{'vs prior':>10}{'bias logit':>12}{'x threshold':>13}{'agree':>10}")
    for item in result["censored_trigger"]:
        bias = item["differential_bias_logit"]
        ratio = item["bias_versus_trigger_threshold"]
        agree = f"{item['decisions_agreeing_with_true_priors']}/{item['decisions_available']}"
        print(
            f"{item['reporting_lag_periods']:>5}{item['cohort_maturity']:>10.2f}"
            f"{item['comparison_cohort_maturity']:>10.2f}"
            f"{'n/a' if bias is None else f'{bias:>12.4f}'}"
            f"{'n/a' if ratio is None else f'{ratio:>13.2f}'}{agree:>10}"
        )
    print("\nafter dividing by the maturity the curve states:")
    for item in result["corrected_trigger"]:
        print(
            f"  lag {item['reporting_lag_periods']}: "
            f"{item['decisions_agreeing_with_true_priors']}/{item['decisions_available']} agree"
        )
    print(
        f"\nminimum lag with bias below the trigger threshold: {result['minimum_lag_where_bias_is_below_the_threshold']}"
    )


if __name__ == "__main__":
    main()
