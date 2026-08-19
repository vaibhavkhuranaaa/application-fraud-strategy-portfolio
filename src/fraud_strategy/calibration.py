"""Independent probability calibration and the schedule that keeps it current."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.special import expit, logit
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from .metrics import expected_calibration_error

# A rule has to beat carrying the last observed prior forward by this much mean absolute
# logit error before it is worth the extra moving part. Fixed before the backtest ran.
PRIOR_FORECAST_MARGIN = 0.02

# The operating trigger for a recalibration, in logit. Set to the promotion gate's own
# absolute intercept limit, so it fires exactly when observed prior movement is large
# enough to push an otherwise compliant model outside that gate.
RECALIBRATION_TRIGGER_LOGIT = 0.10


@dataclass
class ProbabilityCalibrator:
    method: str
    estimator: LogisticRegression | IsotonicRegression

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
        if self.method == "sigmoid":
            return self.estimator.predict_proba(logit(probabilities).reshape(-1, 1))[:, 1]
        return np.clip(self.estimator.predict(probabilities), 0, 1)


def fit_calibrator(method: str, labels: np.ndarray, probabilities: np.ndarray) -> ProbabilityCalibrator:
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    if method == "sigmoid":
        estimator = LogisticRegression(C=1e6, solver="lbfgs", max_iter=500)
        estimator.fit(logit(probabilities).reshape(-1, 1), labels)
    elif method == "isotonic":
        estimator = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)
        estimator.fit(probabilities, labels)
    else:
        raise ValueError(f"unsupported calibrator: {method}")
    return ProbabilityCalibrator(method=method, estimator=estimator)


def select_calibrator(labels: np.ndarray, probabilities: np.ndarray) -> tuple[ProbabilityCalibrator, dict]:
    """Choose by Brier/ECE, preferring sigmoid within a one-percent Brier tolerance."""
    candidates: dict[str, tuple[ProbabilityCalibrator, dict[str, float]]] = {}
    for method in ("sigmoid", "isotonic"):
        calibrator = fit_calibrator(method, labels, probabilities)
        calibrated = calibrator.predict(probabilities)
        candidates[method] = (
            calibrator,
            {
                "brier_score": float(brier_score_loss(labels, calibrated)),
                "ece": expected_calibration_error(labels, calibrated),
            },
        )
    sigmoid_brier = candidates["sigmoid"][1]["brier_score"]
    isotonic_brier = candidates["isotonic"][1]["brier_score"]
    if sigmoid_brier <= isotonic_brier * 1.01:
        selected = "sigmoid"
    else:
        selected = min(
            candidates, key=lambda name: (candidates[name][1]["brier_score"], candidates[name][1]["ece"])
        )
    return candidates[selected][0], {
        "selected": selected,
        "selection_rule": "minimum Brier/ECE; sigmoid preferred within 1% Brier tolerance",
        "candidates": {name: metrics for name, (_, metrics) in candidates.items()},
    }


def _damped_logit_trend(history: Sequence[float], *, damping: float, window: int) -> float:
    """Extrapolate one period from the recent logit priors, damped toward the last one."""
    recent = np.asarray(history[-window:], dtype=float)
    if len(recent) < 2:
        return float(recent[-1])
    slope = float(np.polyfit(np.arange(len(recent), dtype=float), recent, 1)[0])
    return float(recent[-1] + damping * slope)


PRIOR_FORECAST_RULES: dict[str, Callable[[Sequence[float]], float]] = {
    "carry_forward": lambda history: float(history[-1]),
    "damped_trend_3_period": lambda history: _damped_logit_trend(history, damping=0.5, window=3),
    "trend_3_period": lambda history: _damped_logit_trend(history, damping=1.0, window=3),
}


@dataclass(frozen=True)
class PriorShift:
    """The prior correction applied between the calibration period and the scoring period.

    A calibrator fitted on the last closed period carries that period's fraud rate with it.
    When the rate moves, every probability it produces is level-shifted, and the shift is a
    property of the schedule rather than of the model. This moves the calibrated log-odds by
    the difference between the calibration-period prior and a forecast of the scoring-period
    prior, where the forecast reads only periods the model has already been allowed to see.
    """

    rule: str
    calibration_prior: float
    forecast_prior: float

    @property
    def shift(self) -> float:
        return float(logit(self.forecast_prior) - logit(self.calibration_prior))

    def apply(self, probabilities: np.ndarray) -> np.ndarray:
        values = np.asarray(probabilities, dtype=float)
        if self.shift == 0.0:
            return values
        return expit(logit(np.clip(values, 1e-6, 1 - 1e-6)) + self.shift)

    def as_dict(self) -> dict[str, float | str]:
        return {
            "rule": self.rule,
            "calibration_prior": self.calibration_prior,
            "forecast_prior": self.forecast_prior,
            "applied_logit_shift": self.shift,
        }


def select_prior_forecast(priors: Sequence[float], *, backtest_from: int) -> dict:
    """Backtest one-period-ahead prior forecasts on observed periods and pick a rule.

    `priors` holds the observed fraud rate of every period the model is allowed to read,
    in order. The untouched test period is never among them: each rule forecasts a period
    it has not seen, and is scored against what that period turned out to be.
    """
    logits = [float(logit(value)) for value in priors]
    targets = list(range(backtest_from, len(logits)))
    scored: dict[str, dict] = {}
    for name, rule in PRIOR_FORECAST_RULES.items():
        errors = [rule(logits[:target]) - logits[target] for target in targets]
        scored[name] = {
            "mean_absolute_logit_error": float(np.mean(np.abs(errors))),
            "logit_errors": [float(value) for value in errors],
        }
    baseline = scored["carry_forward"]["mean_absolute_logit_error"]
    best = min(scored, key=lambda name: scored[name]["mean_absolute_logit_error"])
    selected = (
        best
        if baseline - scored[best]["mean_absolute_logit_error"] > PRIOR_FORECAST_MARGIN
        else "carry_forward"
    )
    # Carrying the prior forward returns the observed value itself rather than a round trip
    # through the logit, so the resulting shift is exactly zero and leaves scores untouched.
    forecast_prior = (
        float(priors[-1])
        if selected == "carry_forward"
        else float(expit(PRIOR_FORECAST_RULES[selected](logits)))
    )
    moves = [abs(logits[index] - logits[index - 1]) for index in range(1, len(logits))]
    return {
        "backtest_periods": targets,
        "rules": scored,
        "selected": selected,
        "selection_rule": (
            "lowest mean absolute one-period-ahead logit error on observed periods; "
            f"a rule must beat carrying the last prior forward by more than {PRIOR_FORECAST_MARGIN} "
            "to be adopted, otherwise the simpler rule stands"
        ),
        "forecast_prior": forecast_prior,
        "observed_prior_moves_logit": [float(value) for value in moves],
        "median_absolute_prior_move_logit": float(np.median(moves)) if moves else 0.0,
        "recalibration_trigger_logit": RECALIBRATION_TRIGGER_LOGIT,
        "recalibration_trigger_hits": int(sum(value > RECALIBRATION_TRIGGER_LOGIT for value in moves)),
    }


@dataclass(frozen=True)
class ScoreReference:
    """Fixed standardisation statistics for the incumbent-score proxy mapping.

    These are fitted once on the calibration period and then reused unchanged. The
    reference must never be re-derived from the data being scored: doing so would make
    the mapping depend on the batch, which both moves a single application's score
    depending on who it is scored alongside and lets the evaluation period's own
    distribution influence its scores.
    """

    median: float
    scale: float

    def as_dict(self) -> dict[str, float]:
        return {"reference_median": self.median, "reference_scale": self.scale}


def fit_score_reference(values: np.ndarray) -> ScoreReference:
    values = np.asarray(values, dtype=float)
    return ScoreReference(median=float(np.median(values)), scale=float(max(np.std(values), 1e-9)))


def score_to_probability(values: np.ndarray, reference: ScoreReference) -> np.ndarray:
    """Monotonic incumbent-score proxy mapping before independent calibration.

    `reference` is required so that one application scores identically alone and inside
    any batch.
    """
    values = np.asarray(values, dtype=float)
    return expit((values - reference.median) / reference.scale)
