# Case study: refusing a better fraud model

## The decision

A CatBoost challenger catches **766 of 1,428 fraud attempts** at a fixed 5% review capacity. Screening
today catches **294**. The challenger also holds up **472 fewer good customers** at the same workload.

It is still not approved for rollout.

Two promotion checks fixed before the final period was opened fail independently: calibration and
population stability. The incumbent score proxy remains only as a temporary ranking baseline, not an
approved probability model, and the strategy result is `no robust recommendation`.

That refusal is the product. The project demonstrates how to reach it, explain it, and keep a superficially
better model from bypassing governance.

## The operating problem

Application-fraud strategy is not a leaderboard. A strategy owner needs to know:

- how much fraud a policy sends to review;
- how many good customers it delays;
- whether the investigator team can absorb the volume;
- whether stated risk can be trusted;
- whether the population still resembles the one the model learned from;
- and which conclusions are observed versus assumption-driven.

The system therefore compares approaches at fixed reviewer capacity, applies promotion gates, writes a
bounded review queue, and returns a recommendation or refusal for governance review. It never makes a live
lending decision.

## Evidence design

The approved Bank Account Fraud suite contains six synthetic account-opening tables of one million rows
each. `Base.csv` supplies the modeling population. Variants I to V are frozen-model stress tests.

The evaluation is time ordered:

1. Months 0 to 5 select the approach.
2. Month 6 calibrates it.
3. Month 7 remains untouched until the model and decision rules are fixed.

The challenger reaches PR-AUC 0.2129 against 0.1787 for the corrected regularized logistic baseline and
0.0403 for the incumbent proxy. Its paired lift over the strongest baseline has a 95% interval of
0.0219 to 0.0464.

The ranking gain is real. The approval case is not.

At five-percent capacity, a paired row bootstrap places the additional fraud caught between 425 and 519
at 95% confidence. The challenger catches more fraud in all five time-ordered folds. This reduces
uncertainty about ranking and does not remove the calibration or population-stability failures.

## Why promotion was refused

The challenger passes 9 of 11 checks. It fails:

- **Calibration intercept:** 0.301 against an absolute limit of 0.10.
- **Population stability:** 16 feature-month PSI results reach the automatic-promotion block level.

The dashboard never recomputes those gates or lets a scenario control override them. Capacity, rules, and
economic assumptions change the operating view, not the recorded governance position.

Segment findings remain visible even after their formal human acceptance. Groups with fewer than 200 fraud
cases are withheld where the number is written, so an unstable estimate cannot leak through another surface.

## What the build uncovered

The most useful findings were defects in the evaluation system itself.

### A broken baseline

The original linear comparator used an unweighted stochastic solver at roughly 1% prevalence and settled
near the base-rate solution. Replacing it with a class-weighted regularized logistic model moved PR-AUC
from 0.0163 to 0.1787 and fraud capture at 5% capacity to 49.4%.

The challenger still wins, but by about four capture points rather than by an implausible landslide.

### Batch-dependent incumbent scoring

The incumbent proxy originally standardised against whichever batch it received. The same application
could score differently alone and in a cohort. Persisting calibration-period reference statistics made
single and batch scoring identical.

That correction moved the incumbent calibration intercept close to the challenger's failure. The incumbent
is retained because it is the established simple baseline, not because its probabilities are better calibrated.

### A misleading calibration gate

Across five walk-forward periods, expected calibration error passes every measured model-period combination
while the absolute intercept fails every one. The intercept reads a recalibration line far above the score
region applications occupy. The evidence suggests the contract should be reconsidered, but the approved
gate was deliberately left unchanged. Changing it requires a new evaluation approval.

### A shipping failure

The first modernized dashboard depended on fetching a JSON file. Opening `index.html` directly caused a
browser-origin failure and displayed `Data unavailable`. The complete reviewed payload is now embedded in
the HTML, with the JSON retained as fallback. Browser verification covers HTTP loading, direct local-file
loading, and a forced double-failure with an explicit retry action.

## The decision product

The static dashboard leads with the refusal and exposes only the controls that change an operating decision:
scenario starting point, review capacity, transparent rules, and economic assumptions. It then shows the
same-capacity difference against the incumbent score proxy.

Operational evidence sits behind one disclosure. The queue shows ten sampled cases at a time, supports
retrospective-outcome and rule filters, and opens each case into score drivers and rule evidence. Technical
model diagnostics sit behind a separate analyst disclosure.

The visible risk disposition defines what the temporary baseline may and may not do. A second disclosure
contains seven role-assigned monitoring controls and marks investigator yield, customer friction, and label
maturity as needing production data. The four concentration rules have explicit dispositions. Three are
rejected as queue overrides; the device signal is referred for controlled validation as a non-binding
reason code only.

All 1,152 bounded policy combinations are precomputed. The page needs no runtime server, database,
authentication, or third-party request and can remain on free static hosting.

## Operational and reporting surfaces

The local PostgreSQL Fraud Schema stores applications, model scores, scenario runs, ranked queue assignments,
daily strategy facts, and governance events. It supports the monthly fraud KPI and daily suspect-application
reports without turning the public dashboard into an application server.

The repository also includes:

- an originations strategy with four explicit operating decisions;
- a five-sheet Excel management workbook sample;
- annotated SAS translations, clearly labelled as unexecuted translations rather than claimed experience;
- Power BI semantic source and DAX measures, clearly labelled as unverified in Power BI Desktop;
- unapplied Azure Terraform as a scale mapping, not a deployed system.

## Boundaries

- BAF is synthetic account-opening evidence, not observed production lending performance.
- BAF rows contain no recoverable identity relationships. Matching results come from a separate deterministic
  synthetic fixture with held-out truth.
- Money figures are sensitivity arithmetic over declared assumptions, not realised value.
- No automatic decline, group-specific threshold, automatic retraining, or automatic promotion exists.
- No Azure resource, paid capacity, Power BI publication, or production feedback loop exists.

## Outcome

The project finishes with a stronger model, a controlled temporary baseline, an explicit monitoring and
exit path, and a refusal to promote. That is the correct outcome because the evidence supports better
ranking and does not support safe adoption.

The remaining external action is publication of the improved dashboard and simplified narrative after the
human publish gate is approved.
