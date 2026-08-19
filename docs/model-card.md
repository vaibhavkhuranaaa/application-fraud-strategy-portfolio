# Model card: application fraud strategy scorer

Status: `rejected`. Evidence source: `baf_base`.

## Intended use

Rank synthetic BAF application records for bounded manual-review strategy analysis. The model does not approve, deny, or execute a lending decision.

## Selection

- Selected challenger before untouched testing: `catboost_hybrid`.
- Resulting champion: `incumbent_proxy`.
- Rolling-origin folds: train 0-2/test 3, train 0-3/test 4, train 0-4/test 5.
- Final fit months 0-5; calibration selection month 6; one-time test month 7.
- Linear comparator `regularized_logistic` reaches 49.4% of the fraud at 5% review capacity against 53.6% for `catboost_hybrid`.

## Calibration schedule

- Fitted on period [6], then level-corrected to a forecast of the scoring period.
- Forecast rule `carry_forward`, chosen by backtest on periods [3, 4, 5, 6], applying a logit shift of 0.0000.
- Recalibrate at every period close, and raise a recalibration review when the observed prior moves more than 0.1 in logit from the calibration prior. This is an operating control, not a promotion gate.

## Promotion gates

- pr_auc_lift_ci_lower_above_zero: `true`
- catch_rate_improves_at_three_capacities: `true`
- no_capacity_regression_over_two_points: `true`
- positive_brier_skill: `true`
- ece_at_most_0_02: `true`
- calibration_slope_0_8_to_1_2: `true`
- calibration_intercept_abs_at_most_0_10: `false`
- economic_grid_positive_at_least_80_percent: `true`
- warnings_visible: `true`
- no_automatic_promotion_psi_blocks: `false`
- fairness_governance_review_resolved: `true`

## Limitations

- BAF is privacy-preserving synthetic account-opening data, not observed personal- or auto-loan performance.
- `credit_risk_score` is an incumbent proxy, not a verified vendor score.
- Economic values are sensitivity assumptions, not observed P&L.
- BAF has no cross-row identity truth; identity-linking evidence comes only from the separate fixture.
- Fairness and drift warnings require governance interpretation and never trigger hidden group-specific thresholds.

## Evidence

See `evaluation/model_evaluation.json` for full metrics, confidence intervals, capacity comparisons, explanations, variant stress tests, and artifact lineage.
