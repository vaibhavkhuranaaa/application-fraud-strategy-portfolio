# M3 evaluation report

> Dated record. Figures below are the M3 evidence as it stood on the dates named and are
> deliberately not rewritten. For current results see `evaluation/model_evaluation.json`,
> the pre-approved evaluation contract and its M6, M7 and M8 addenda, and `docs/originations-strategy.md`.
> Two figures here are superseded: the promotion count is now 9 of 11 after the segment
> findings were accepted on 2026-08-10, and the linear comparator named here was corrected
> at M6.

Evidence date: 2026-08-05; incumbent calibration figures corrected 2026-08-09 (see below). Evidence sources are labeled `baf_base`, `baf_variant_i`–`v`, or `synthetic_link_fixture`.

## Decision

Retain the `credit_risk_score` incumbent proxy and return `no robust recommendation`. The selected hybrid CatBoost challenger passed ranking, capacity, Brier, ECE, slope, and scenario-utility gates but failed calibration-intercept, PSI-block, and unresolved fairness-review gates.

## Model

| Month-7 metric | Hybrid CatBoost | Incumbent proxy |
| --- | ---: | ---: |
| PR-AUC | 0.2129 | 0.0403 |
| AUROC | 0.8947 | 0.6762 |
| Brier score | 0.012878 | 0.014380 |
| ECE | 0.00226 | 0.00197 |
| Calibration slope | 1.041 | 1.037 |
| Calibration intercept | 0.301 | 0.299 |

The paired PR-AUC lift was 0.1725 with 95% bootstrap interval 0.1536–0.1906. Hybrid catch rate exceeded the incumbent at 1%, 3%, 5%, and 10% capacity by 15.9, 26.8, 33.1, and 37.0 percentage points. At 5% capacity, incremental scenario utility was positive for 60/60 approved assumption points, ranging from $2.36M to $9.58M. None of these values is observed P&L.

## Governance warnings

- The challenger's absolute calibration intercept exceeded the 0.10 gate. The retained incumbent proxy sits at 0.299 on the same period, so the miscalibration is a month-7 shift affecting both comparators, not a defect unique to the challenger. Gates apply to the challenger, so the incumbent is retained as the simpler baseline rather than promoted on calibration quality.
- PSI produced 12 warnings and 16 promotion blocks against the pooled training window. The month-0
  reference this replaced produced 43 and 32; see the M6 correction below.
- Eligible age and housing groups triggered TPR/FPR or review-rate governance review.
- Rule-enabled strategies generated material overflow; score-only frontier points had zero overflow.

## Linking fixture

The 50,000-row fixture contained 200 labeled rings and 1,000 true entity pairs. Pairwise F1 was 1.000 clean and at least 0.953 at 15% corruption; false-merge rate was 0; seed spread was at most 0.0136 at 15%; matching finished within 1.304 seconds per required run. These claims do not apply to BAF, which contains no cross-row identity truth.

## Reproducibility

The full six-file curation produced 6,000,000 checked rows and 467 MB of typed Parquet in 19.787 seconds. PostgreSQL 17 migrations and a 1,000-row leakage/idempotency smoke load passed. Milestone closure reruns the fifteen unit and contract tests, Ruff, Docker Compose validation, and repository integrity checks.

## Correction, 2026-08-09

The incumbent proxy's score mapping standardised against whichever batch it was given, so its month-7
probabilities were produced using month-7's own distribution while its calibrator had been fitted on
month-6-scaled inputs. The mapping now uses fixed reference statistics fitted on the calibration period
and persisted in the champion manifest.

A full retrain from cleared checkpoints reproduced every other recorded value identically. Only the
incumbent's month-7 probability-quality metrics moved:

| Incumbent month-7 metric | Before | After |
| --- | ---: | ---: |
| Brier score | 0.014370 | 0.014380 |
| Brier skill | 0.010874 | 0.010189 |
| ECE | 0.000096 | 0.001966 |
| Calibration slope | 1.0344 | 1.0369 |
| Calibration intercept | 0.1435 | 0.2987 |

Rank-based results - PR-AUC, AUROC, catch rates at every capacity, the strategy frontier, promotion
gates, fairness, drift, and variant metrics - are unchanged, because the mapping is monotonic. The
decision is unchanged: challenger rejected, incumbent retained, `no robust recommendation`.

The earlier incumbent ECE of 0.000096 was an artefact of scoring the test period against its own
distribution and should not be cited.

## M6 correction, 2026-08-10

Four corrections to the model evidence, made after a staff review. The decision they were made against
did not change: the challenger is still rejected, the incumbent proxy is still retained, and the strategy
result is still `no robust recommendation` with 8 of 11 pre-agreed checks passing.

### 1. The linear comparator was measuring nothing

`elastic_net_logistic` used an `SGDClassifier` with no class weighting. At roughly 1% prevalence the
unweighted objective is already near its optimum at the base-rate solution, so the fit stopped there and
the comparator returned chance-level ranking for five milestones. It is replaced by
`regularized_logistic`, a class-weighted logistic regression fitted with a full-batch solver on the same
features, the same months, and the same split.

| Month-7 result | Before | After |
| --- | ---: | ---: |
| AUROC | 0.5156 | 0.8848 |
| PR-AUC | 0.0163 | 0.1787 |
| Rolling fold PR-AUC | 0.0093 / 0.0099 / 0.0104 | 0.1300 / 0.1419 / 0.1529 |
| Catch rate at 5% review capacity | 7.2% | 49.4% |
| Solver iterations per fold | about 20 | 34 / 33 / 33, all converged |

The prevalence floor on this period is 0.0147, so the previous PR-AUC of 0.0163 was at the floor.

Two things follow. First, the promotion test got harder. The lift gate is measured against the strongest
baseline, which was the incumbent proxy at PR-AUC 0.0403 and is now the linear comparator at 0.1787. The
paired lift falls from 0.1725 to 0.0342, with a 95% bootstrap interval of 0.0219 to 0.0464. The gate
still passes, now against a real baseline.

Second, the distance between a linear model and gradient boosting on this problem is small. At the same
review volume the linear comparator catches 49.4% of the fraud against the hybrid's 53.6%, which is 92.0%
of the capture for a model with stable coefficients and direct adverse-action reasoning. The gap is 3.2,
4.3, 4.3, and 3.0 percentage points at 1%, 3%, 5%, and 10% capacity.

Selection did not change. The contract selects on mean rolling PR-AUC first, and the hybrid leads 0.1727
to 0.1416, so the tiebreaker that ends in simplicity never comes into play. The comparison is recorded in
`simple_versus_complex` because it is the term of a model-risk trade a reviewer should be able to see,
not because it promotes anything. Neither model is promoted.

### 2. The calibration schedule was measured rather than assumed

The calibrator is fitted on the last closed period before scoring, which carries that period's fraud rate
into the next one. The schedule now states this and corrects for it: after fitting, the calibrated
log-odds are shifted by the difference between the calibration-period prior and a forecast of the scoring
period's prior. The forecast rule is chosen by backtest on periods 3 to 6, and month 7 is never among
them.

| One-period-ahead prior forecast | Mean absolute logit error on months 3 to 6 |
| --- | ---: |
| Carry the last prior forward | 0.1079 |
| Damped three-period logit trend | 0.1065 |
| Three-period logit trend | 0.1248 |

No rule beats carrying the prior forward by the 0.02 margin fixed before the backtest ran, so carrying
forward stands and the applied shift is 0.0000. The mechanism is retained for deployment, where a trend
may be stronger than the one in this data.

The finding is that the schedule is not the main cause. The reported intercept of 0.3014 decomposes as
0.2325 from the slope and 0.0689 of level error where the scores actually sit. The gate reads the
recalibration line at probability 0.5, and these scores sit at a mean logit of -5.66, so a slope of 1.041
is multiplied by that distance before it reaches the intercept. In other words the intercept gate is a
much tighter slope gate than the stated 0.8 to 1.2 band suggests. The one-period prior move between
calibration and scoring is 0.0967 in logit, which accounts for the entire 0.0689 of level error and no
more.

The gates are unchanged, because changing them needs a newly approved evaluation contract. What is added
is an operating control: recalibrate at every period close, and raise a recalibration review when the
observed prior moves more than 0.10 in logit from the calibration prior. The median absolute
month-over-month move in this data is 0.0992 and 3 of the 6 observed transitions exceed the trigger.

### 3. Stability is measured against the training window

PSI used month 0 as its reference while the model was fitted on months 0 to 5, so half of the blocking
results were charging the model for movement inside its own training data. The reference is now the
pooled training window.

| Stability result | Month-0 reference | Pooled months 0 to 5 |
| --- | ---: | ---: |
| Warnings at 0.10 | 43 | 12 |
| Blocks at 0.25 | 32 | 16 |

Nine of the 16 remaining blocks fall in months 6 and 7, after the training window, which is the drift a
deployment decision actually has to answer for. The gate still fails and still blocks automatic
promotion.

### 4. A failed gate now returns the incumbent, not the strongest baseline

The retained champion was previously whichever baseline ranked best on the test period. With the linear
comparator working, that rule would have promoted an internal model that has never been through the
promotion gates on the strength of a single test period. The champion on failure is now the incumbent
proxy explicitly. The recorded champion is unchanged; the rule that produces it is no longer accidental.
