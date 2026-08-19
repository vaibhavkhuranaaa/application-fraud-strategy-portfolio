# Fairness review: age and housing segment findings

Status: `analysis complete and governance decision recorded 2026-08-10; both findings accepted; housing_status retained`

This record exists because the M2 evaluation contract routes material segment disparities to a
human rather than failing or passing them automatically. Sections 1 to 7 are the analysis. Section 8
is the decision, which was taken on 2026-08-10 and closes the check that had blocked promotion since
M3.

Evidence: `evaluation/fairness_ablation.json` (`EV-M7-HOUSING-ABLATION-20260810`),
`evaluation/model_evaluation.json` (`fairness` block). Reproduce with
`PYTHONPATH=src uv run python scripts/fairness_ablation.py`.

## 1. Scope and what triggered this

The evaluation contract triggers governance review when an uncertainty-supported maximum-minimum
TPR or FPR gap exceeds 10 percentage points, or when a review-rate ratio falls outside 0.80 to
1.25. Two attributes trigger it on the untouched test period, month 7, at the 5% review capacity:

- `customer_age`, which is never trained on and is audit-only by contract.
- `housing_status`, which is one of the 33 eligible model inputs.

Groups with fewer than 200 positive labels are not published, so the comparison rests on age bands
30, 40 and 50, and on housing groups BA and BC. Every other group is withheld.

This review does not cover income or channel. Neither produced two publishable groups on month 7,
so neither has a measurable gap to review.

## 2. Measured disparity, current model

Month 7, 96,843 applications, 1,428 fraud cases, hybrid CatBoost at 5% review capacity.

| Attribute | Groups | Review-rate ratio | TPR gap | FPR gap | Contract trigger |
| --- | --- | --- | --- | --- | --- |
| `housing_status` | BA, BC | 0.073 | 0.377 | 0.156 | All three |
| `customer_age` | 30, 40, 50 | 0.397 | 0.234 | 0.049 | Ratio and TPR gap |

Group detail for `housing_status`:

| Group | Applications | Fraud cases | Fraud rate | Reviewed | Review rate | Caught | Catch rate | Yield per review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BA | 19,182 | 899 | 4.69% | 3,670 | 19.13% | 606 | 67.4% | 16.5% |
| BC | 37,502 | 266 | 0.71% | 525 | 1.40% | 79 | 29.7% | 15.1% |

### 2.1 The disparity is not one disparity

Two harms run in opposite directions and a single ratio hides that.

**Burden.** BA applicants are reviewed at 19.13% against BC at 1.40%, so BA carries roughly
fourteen times the friction of a manual review. Under a four-fifths framing where review is the
adverse outcome, BA is the disadvantaged group and the ratio is 0.073 against a 0.80 threshold.

**Protection.** BC fraud is caught at 29.7% against BA at 67.4%. Fraud attempted through BC
applications is less than half as likely to be stopped. Under a framing where detection is the
benefit, BC is the disadvantaged group.

A mitigation that improves one of these will usually worsen the other. That is the substance of
the decision in section 8, and it is why the contract does not resolve it automatically.

### 2.2 How much of the gap is the model, and how much is the base rate

BA's fraud rate is 4.69% against BC's 0.71%, a ratio of 0.151. A capacity-constrained ranking
model that is working correctly will review a higher-prevalence group more often. Dividing the
review-rate ratio by the prevalence ratio isolates the part of the disparity that is not explained
by where fraud actually is.

| Attribute | Review-rate ratio | Prevalence ratio | Prevalence-adjusted ratio | Inside 0.80 to 1.25 |
| --- | --- | --- | --- | --- |
| `customer_age` (30 vs 50) | 0.397 | 0.475 | **0.836** | Yes |
| `housing_status` (BC vs BA) | 0.073 | 0.151 | **0.484** | No |

This separates the two findings, and it is the single most decision-relevant number in this
review.

**`customer_age` is a prevalence artifact.** Once each band's own fraud rate is accounted for, the
review rates are inside the contract band. The model is not treating age bands differently beyond
tracking where fraud is. Age is also never used as an input. The residual TPR gap of 0.234
reflects that fraud in older bands is easier to separate at this capacity, not that the model
applies a different standard.

**`housing_status` is not.** BC is reviewed at roughly half the rate its own fraud rate would
justify. This is a genuine model behaviour and it survives the prevalence adjustment.

Yield per review is close between the two groups, 16.5% for BA against 15.1% for BC. Predictive
parity approximately holds while error-rate balance fails. Both cannot be satisfied at once when
base rates differ, so the question is which one this program should prefer, and that is a policy
judgment rather than a measurement.

## 3. Cost of removing `housing_status`

### 3.1 Protocol

Both arms are fitted on identical months, identical rows, identical seeds and the tuned parameters
carried forward from the M6 selection checkpoint. Nothing was retuned. The difference between the
arms is the one feature.

The materiality thresholds were fixed in `scripts/fairness_ablation.py` before the script was first
run, and are recorded in the evidence file:

- 1.0 percentage point of catch at 5% capacity. One point is about 14 month-7 fraud cases against
  a recorded catch interval half-width of 2.6 points, so a smaller loss is not separable from
  sampling noise at the sample size this program has.
- 0.005 mean rolling PR-AUC, which is under 3% of the hybrid's 0.1727 and smaller than its own
  spread across three folds.

The decision is taken on the rolling-origin folds, which is the evidence the selection contract
already ranks on. Month 7 is recorded for completeness and did not move the decision, as
`evaluation/report.md` requires.

### 3.2 Result: the cost is material

| Measure | With `housing_status` | Without | Cost | Threshold | Material |
| --- | --- | --- | --- | --- | --- |
| Rolling mean PR-AUC | 0.1727 | 0.1608 | 0.0120 | 0.005 | Yes |
| Rolling catch at 5% capacity | 53.12% | 50.73% | 2.39 pp | 1.0 pp | Yes |
| Rolling worst-fold PR-AUC | 0.1524 | 0.1472 | 0.0052 | | |
| Month 7 catch at 5% capacity | 53.64% | 49.23% | 4.41 pp | | |
| Month 7 fraud cases caught | 766 | 703 | 63 cases | | |

Both pre-registered thresholds are exceeded, so this review takes the documented branch: the
disparate-impact analysis, business-justification record and less-discriminatory-alternative
search below.

For scale, the entire measured distance between a linear model and gradient boosting on this data
is 4.3 percentage points of catch at the same capacity. Removing this one feature costs 2.39
points on the rolling folds, so it gives back more than half of what the complex model buys.

### 3.3 Removal does not close the gate

| `housing_status` at 5% capacity | With | Without | Trigger |
| --- | --- | --- | --- |
| Review-rate ratio | 0.073 | 0.169 | Still outside 0.80 to 1.25 |
| Prevalence-adjusted ratio | 0.484 | **1.119** | Now inside the band |
| TPR gap | 0.377 | 0.190 | Still above 0.10 |
| FPR gap | 0.156 | 0.096 | **Now below 0.10** |

Removal is a real mitigation and not a cosmetic one. The excess review burden beyond prevalence is
eliminated: BC moves from being reviewed at half the rate its fraud rate justifies to being
reviewed slightly above it. The FPR gap drops below its trigger. But two of the three housing
triggers still fire, and `customer_age` is untouched, so the governance check does not close on
either arm. There is no version of this model that clears the fairness gate by engineering alone.

### 3.4 The gap closes partly by levelling down

| Group | Reviewed with | Reviewed without | Caught with | Caught without | Yield with | Yield without |
| --- | --- | --- | --- | --- | --- | --- |
| BA | 3,670 | 2,648 | 606 | 509 | 16.5% | 19.2% |
| BC | 525 | 877 | 79 | 100 | 15.1% | 11.4% |

BC gains 352 reviews and 21 caught frauds. BA loses 1,022 reviews and 97 caught frauds. The
narrowing of the TPR gap is therefore about four-fifths a reduction in BA detection and one-fifth
an improvement in BC detection, and the program catches 63 fewer frauds in total.

The trade also runs the other way on yield. Equalising review burden relative to prevalence costs
predictive parity: the yield ratio between the groups moves from 0.91 to 0.59. Reviewers working
BC cases would see roughly one confirmed fraud in nine rather than one in seven.

## 4. Business justification record

Recorded for the case where the accountable human elects to retain the feature.

**Legitimate business purpose.** `housing_status` is a categorical application attribute collected
in the ordinary course of account opening. It is used as one of 33 inputs to a fraud risk ranking
that orders a capacity-constrained manual review queue. It does not gate approval or decline. The
product produces no automatic decision of any kind.

**Evidence of contribution.** Measured, not asserted: 0.0120 mean rolling PR-AUC and 2.39
percentage points of catch at 5% capacity, both above pre-registered materiality thresholds, on a
paired design where nothing else differs. On month 7 this is 63 additional fraud cases detected
per 96,843 applications at fixed review capacity.

**Proportionality.** The feature does not act on its own. Removing it moves the model's ranking,
not any group's treatment, because a single population-wide threshold is applied to every
applicant. No group-specific threshold exists at any point in the program, verified in section 6.

**Limits of this justification.** It rests on synthetic data. BAF is privacy-preserving synthetic
account-opening data and its published groups carry no stated real-world meaning, so neither the
disparity nor the business case transfers to a real portfolio. A production version of this record
would need the same measurement on observed data and legal review of the attribute itself, neither
of which this project can supply.

## 5. Less-discriminatory-alternative search

### Alternative A: remove `housing_status`

Measured in section 3. Costs 2.39 points of catch and 63 month-7 fraud cases, brings the
prevalence-adjusted review-rate ratio into band and the FPR gap under its trigger, leaves the TPR
gap and the raw review-rate ratio failing, and reduces total detection. Viable, at a material and
now quantified cost. This is the alternative on the table.

### Alternative B: group-specific thresholds

Rejected on policy grounds without measurement. The evaluation contract forbids silently applying
group-specific thresholds, and the design contract forbids any group-specific treatment in the
product. Equalising review rates by group would mean deliberately reviewing identical risk
differently based on housing status. It is excluded by the contract this project operates under
and is recorded here only so the search is complete.

### Alternative C: rebalance without dropping the feature

Not pursued, and the reason is measurable. Reweighting or constraining the model to equalise
review rates by group requires the group label at training time and produces a model whose ranking
depends on group membership by construction. That is Alternative B expressed through the loss
function rather than the threshold, and the same contract prohibition applies.

### The proxy finding, which limits every alternative

Housing group membership is recoverable from the 32 remaining inputs.

| Target | AUROC | Base rate |
| --- | --- | --- |
| Membership of BA | 0.799 | 19.8% |
| Membership of BC | 0.770 | 38.7% |

Dropping the column does not make the model blind to the group. It removes the direct signal and
roughly half of the excess review burden, and the remaining features continue to carry enough
information to reconstruct group membership well above chance. This is why the raw review-rate
ratio improves from 0.073 to 0.169 rather than to 1.0, and it is the reason removal should be
described as a partial mitigation rather than a fix.

It also carries a cost that is easy to miss. `housing_status` is currently a published audit
dimension. Removing it from the feature set does not remove it from the audit, but a program that
removes group attributes as a matter of course eventually loses the ability to measure the
disparity it is trying to manage.

## 6. Confirmation: no group-specific threshold, and withholding

Verified 2026-08-10 as M7 acceptance item 4.

**No group-specific threshold exists anywhere in the product.** `rank_review_queue`
(`src/fraud_strategy/strategy.py:49`) builds one ranking over the whole population and applies one
capacity cut. `segment_metrics` (`src/fraud_strategy/metrics.py:166`) computes the threshold on
the full population and only then slices by group, so the reported per-group review rates are
consequences of one shared threshold rather than separate thresholds. The four policy rules exposed
in the product are behavioural: birth-date and email concentration, device and email concentration,
foreign request with weak name-and-email similarity, and selected-branch concentration. No group
attribute enters policy construction, the capacity grid or the rule set.

**Withholding was not being applied correctly, and was fixed.** `DESIGN.md` requires that groups
under 200 fraud cases render as withheld and never as zero. The dashboard withheld the fraud rate
but still printed the raw fraud count, so housing group BG rendered as 6 applications and 0 fraud,
and age band 90 to 99 rendered as 3 applications and 0. Both read as measured zeros. Separately,
`dashboard/data/dashboard.json` is a public static payload and carried every suppressed count
regardless of what the page displayed, which would have published group estimates the evaluation
contract does not permit as soon as the dashboard was hosted.

Both were corrected. Suppression now happens where the number is written rather than where it is
displayed: the payload emits null for the fraud count and rate of any group under the threshold,
and the renderer withholds count and rate together. Application volume is retained, because it
shows the group exists without being a fraud estimate. A regression test in
`tests/test_evidence_contract.py` fails if a withheld group ever ships a number again.

The governed Power BI extract continues to carry `positive_labels` for withheld groups with all
derived metrics blank. That is deliberate and unchanged: it is an internal governed record where
the count is what justifies the suppression, and the existing contract test asserts the derived
metrics stay blank.

## 7. Residual risk

- The disparity is real on this data and only partially mitigable without group-specific
  treatment, which the contract forbids.
- Both arms fail the fairness gate, so no engineering path closes M7 item 3.
- BAF is synthetic. Neither the disparity nor the justification transfers to a real portfolio.
- The measurement is a single test period at a single capacity. The gaps are reported with Wilson
  intervals in the evidence file, and the BC group rests on 266 positive labels.
- Housing group membership remains recoverable from the retained features under either arm.

## 8. Governance decision, recorded

**Decided 2026-08-10 by vaibhavkhuranaaa@gmail.com. Both findings accepted. `housing_status` is
retained in the feature contract.** This closes the check that had blocked promotion since M3. The
machine-readable record is `evaluation/governance_acceptance.json`; the human record is
the machine-readable acceptance in `evaluation/governance_acceptance.json`.

**`customer_age`: accepted** as a prevalence artifact. The feature is audit-only and never trained
on, and its review-rate ratio moves from 0.397 to 0.836, inside the 0.80 to 1.25 band, once each
band's own fraud rate is accounted for. This is the outcome the analysis in section 2.2 supports.

**`housing_status`: accepted, feature retained**, on the business-justification record in section 4.
The disparity is real and survives the prevalence adjustment at 0.484, and the acceptance does not
pretend otherwise. What it rests on is that removal was measured rather than assumed: it costs 2.39
percentage points of catch at 5% capacity and 63 month-7 fraud cases, brings the prevalence-adjusted
ratio to 1.119 and the FPR gap under its trigger while leaving the raw ratio at 0.169 and the TPR gap
at 0.190, and closes the gap partly by levelling down, with BA losing 97 caught frauds so that BC can
gain 21. Group membership also stays recoverable from the 32 remaining inputs at AUROC 0.799 and
0.770, so removal takes away the audit handle rather than the behaviour.

### What this acceptance does not do

It resolves promotion gate 5 and nothing else. The calibration intercept at 0.3014 and the 16 PSI
blocks fail independently, so the challenger remains rejected, the incumbent proxy remains champion,
and the strategy result remains `no robust recommendation`. The check count moves from 8 of 11 to 9
of 11, which is bookkeeping rather than progress toward promotion.

It authorises no group-specific threshold and no automatic decline. Neither exists anywhere in the
code or the schema, and section 6 records the verification.

### How it can lapse

The acceptance is granted against the values measured on 2026-08-10 and recorded in
`granted_against`. It is matched reason by reason, so a segment that begins failing later is not
covered by it, and it lapses for any segment whose accepted gap widens by more than 0.05 or whose
review-rate ratio falls by more than 0.05. Both properties are enforced in
`apply_governance_acceptance` and covered by tests. An acceptance that could not lapse would be a
permanent exemption wearing a governance label.

### Implementation note

Gate 5 reads "resolved **or explicitly accepted by governance**". Only the first branch had ever been
computed, so before this a recorded human acceptance could not satisfy the gate written to receive
it. Implementing the second branch completes the approved wording; it changes no threshold, no
trigger, and no measurement, and every warning stays visible in the evidence and on the dashboard.
