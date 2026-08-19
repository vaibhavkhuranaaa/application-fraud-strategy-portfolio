import numpy as np
import pandas as pd

from fraud_strategy.calibration import PriorShift, select_calibrator, select_prior_forecast
from fraud_strategy.metrics import (
    expected_calibration_error,
    metric_summary,
    population_stability_index,
    wilson_interval,
)


def test_calibrator_returns_bounded_probabilities() -> None:
    labels = np.array([0] * 90 + [1] * 10)
    raw = np.linspace(0.01, 0.99, 100)
    calibrator, record = select_calibrator(labels, raw)
    calibrated = calibrator.predict(raw)
    assert record["selected"] in {"sigmoid", "isotonic"}
    assert np.all((calibrated >= 0) & (calibrated <= 1))
    assert expected_calibration_error(labels, calibrated) <= 0.1


def test_metric_summary_and_wilson_interval() -> None:
    labels = np.array([0, 0, 0, 1, 1])
    probabilities = np.array([0.01, 0.1, 0.2, 0.7, 0.9])
    metrics = metric_summary(labels, probabilities)
    assert metrics["pr_auc"] == 1.0
    lower, upper = wilson_interval(8, 10)
    assert 0 < lower < 0.8 < upper < 1


def test_prior_forecast_keeps_the_simpler_rule_without_a_material_gain() -> None:
    # A flat prior history gives every rule the same answer, so the margin must protect
    # the simpler rule rather than let a tie promote extra machinery.
    priors = [0.010, 0.011, 0.0105, 0.011, 0.0108, 0.011, 0.0109]
    record = select_prior_forecast(priors, backtest_from=3)
    assert record["selected"] == "carry_forward"
    assert record["forecast_prior"] == priors[-1]
    assert set(record["rules"]) == {"carry_forward", "damped_trend_3_period", "trend_3_period"}


def test_prior_forecast_adopts_a_trend_when_it_earns_the_margin() -> None:
    # A steadily rising prior is exactly the case carrying forward gets wrong every period.
    priors = [float(np.round(0.005 * 1.6**period, 6)) for period in range(7)]
    record = select_prior_forecast(priors, backtest_from=3)
    assert record["selected"] != "carry_forward"
    assert record["forecast_prior"] > priors[-1]


def test_prior_shift_moves_the_level_without_reordering_applications() -> None:
    probabilities = np.array([0.002, 0.05, 0.2, 0.4])
    shift = PriorShift(rule="trend_3_period", calibration_prior=0.010, forecast_prior=0.013)
    moved = shift.apply(probabilities)
    assert shift.shift > 0
    assert np.all(moved > probabilities)
    assert list(np.argsort(moved)) == list(np.argsort(probabilities))
    unchanged = PriorShift(rule="carry_forward", calibration_prior=0.010, forecast_prior=0.010)
    assert np.array_equal(unchanged.apply(probabilities), probabilities)


def test_psi_handles_numeric_null_bins_without_mixed_type_failure() -> None:
    reference = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0] * 10)
    comparison = pd.Series([1.0, np.nan, 3.0, 4.0, 7.0] * 10)
    value = population_stability_index(reference, comparison, bins=3)
    assert np.isfinite(value)
    assert value >= 0
