# Application fraud originations strategy

Status: `prepared 2026-08-10 for governance review; recommendation is a partial refusal`
Author: fraud strategy analyst
Evidence: `evaluation/model_evaluation.json`, `evaluation/monthly_kpi.json`, `evaluation/fairness_ablation.json`
Population: BAF `Base.csv`, months 0 to 7. Month 7 is the untouched evaluation period, 96,843
applications and 1,428 fraud attempts.

## 1. Decision requested

Four decisions, and they are not the same decision.

1. Promote the proposed model to champion. **I am not recommending this.**
2. Adopt the concentration rule set. **I am recommending against this.**
3. Buy catch rate by increasing review capacity under the incumbent score proxy. **I am
   recommending against this, and the reason is not cost.**
4. Approve four operating changes that need no model promotion. **I am recommending all four.**

The first three are refusals with stated conditions. The fourth is where the available improvement
actually is this quarter.

## 2. What is in place today, and what it costs

The screening in place is a single incumbent score proxy, applied as one ranking over the whole
population with one capacity cut. There is no automatic decline anywhere in the process.

At the operating capacity of 5%, on month 7:

| | Value |
| --- | --- |
| Applications | 96,843 |
| Fraud attempts | 1,428 |
| Cases worked | 4,842 |
| Fraud caught | 294 |
| **Catch rate** | **20.59%** (95% CI 18.57% to 22.76%) |
| Fraud reaching approval unchecked | 1,134 |
| Good customers held up | 4,548 |
| Reviewer hit rate | 6.07%, roughly 1 confirmed fraud per 16.5 cases worked |

Two things about the current state are not usually said out loud and belong in this record.

**The current screening is itself miscalibrated.** Its month-7 calibration intercept is 0.2987
against an absolute limit of 0.10. The proposed model's is 0.3014. These are the same failure to
within a rounding, so the miscalibration is a property of the period rather than a defect the
challenger introduced. Any probability the current screening states is unreliable in the same way and
to the same degree. Nobody has previously recorded that.

**The current queue overruns its own staffing every period.** The incumbent score is a
low-cardinality integer, so the block of applications sitting exactly on the cut cannot be split, and
every application at the cutting value has to be treated alike. Measured across the eight periods,
the queue exceeds the staffed headcount by 63 to 168 cases, 1.06% to 2.45%. The proposed model
overshoots by exactly one case. This is unbudgeted review volume being worked every month.

## 3. The problem this strategy has to answer

Fraud pressure is rising while volume falls.

| Period | Applications | Attempt rate | Reviewer hit rate |
| --- | --- | --- | --- |
| Period 2 | 136,979 | 87.5 bps | 9.4% |
| Period 5 | 119,323 | 118.2 bps | 12.8% |
| Period 7 | 96,843 | 147.5 bps | 15.8% |

Attempt rate is up 69% from its low while application volume is down 29%. The rising reviewer hit
rate is not the team improving. It is a fixed review capacity meeting a richer pool of fraud, which
is what a worsening portfolio looks like from inside the queue. A desk reading only the hit rate
would conclude things were going well.

At current catch, 1,134 fraud attempts reached approval unchecked in month 7 alone.

Read the attempt rate as a floor. Fraud labels mature over 30 to 90 days and longer, so the most
recent periods above are incomplete and will worsen. The rising reviewer hit rate is available within
days and can be read as current; the catch rate beside it cannot.

## 4. Options considered

All comparisons hold review capacity fixed at 5%, 4,842 cases, so nothing below is bought with extra
headcount.

| Option | Catch | Fraud caught | Good customers held up | Reviewer hit rate | Overflow |
| --- | --- | --- | --- | --- | --- |
| A. Incumbent score proxy | 20.59% | 294 | 4,548 | 6.07% | 0 |
| B. Proposed model, hybrid | **53.64%** | **766** | **4,076** | **15.82%** | 0 |
| C. Simple statistical model | 49.37% | 705 | 4,137 | 14.56% | 0 |
| D. Add concentration rules | 39.57% | 565 | 43,559 | 1.28% | **39,282** |

**Read Option B's catch rate as a range, not a number.** A five-period walk-forward puts catch at
54.24%, 53.93%, 51.81%, 49.03% and 53.64%, a mean of **52.53%** with a standard deviation of 2.17
points. The single figure in the table is the last of those five and sits above the average, so it is
a better-than-typical period rather than a representative one. For planning a future period the
honest interval is **45.93% to 59.13%**, roughly two and a half times wider than the 51.05% to 56.21%
the record previously carried, because a single period varies around the mean as well as the mean
being uncertain. The comparison itself is unaffected: the proposed model beat the screening in place
today in every one of the five periods, by between 30.3 and 31.6 points.

**Option B is strictly better than A on both axes.** It catches 472 more fraud attempts and holds up
472 fewer good customers, for the same 4,842 cases worked. There is no trade being made between fraud
and friction here; it dominates. That is unusual and it is why the model was built.

**Option C is the honest simplicity check.** A plain regularised logistic regression reaches 49.37%,
which is 92.0% of what gradient boosting achieves. The complex model is worth 4.27 percentage points
of catch at this capacity, about 61 fraud attempts per period. That is a real difference and it is
smaller than a reader would assume from the ranking scores. If the added operational cost of a
gradient-boosted model is material, Option C keeps most of the benefit.

**Option D fails on arithmetic, not on judgment.** The four concentration rules force 43,559
applications into review against a capacity of 4,842. The 39,282 case overflow cannot be worked, so
in practice the rules would either be ignored or would silently become a decline policy, and this
program authorises no automatic decline. Reviewer hit rate collapses to 1.28%, meaning 78 cases
worked per confirmed fraud. The rules are useful as investigation signals on individual cases. They
are not a capacity-feasible policy and should not be presented as one.

**What Option B is worth, as a range.** Against the incumbent score proxy, at the same review
capacity, incremental value across the approved assumption grid is **$0.57M to $9.58M for the evaluation
period**, not annualised: it is arithmetic over one month of 96,843 applications.
That is a range and not a point because two factors sit between fraud caught and money saved: a
review does not stop every fraud it finds, and a stopped fraud does not recover the whole balance.
Neither factor has a source meeting this project's citation bar, so both are declared sensitivity
inputs. The sign holds across all 960 combinations tested, so the comparison itself is not in doubt.
Any single figure quoted from the optimistic corner of that range is up to 4.1 times the pessimistic
middle of it, which is why no single figure appears in section 5.

**Buying catch with capacity is the expensive lever.** Under the current screening, doubling review
capacity from 5% to 10% moves catch from 20.59% to 30.81%. That is 10.2 points for twice the
reviewers, and it still does not reach what the proposed model achieves at half that headcount. The
binding constraint is ranking quality, not staffing. Adding reviewers to a weak ranking is the most
expensive way to buy catch rate available here, and it is the one most often reached for.

## 5. Recommendation

**Do not promote the proposed model.** It fails two of the eleven pre-agreed promotion checks. Both
were fixed before any result was seen and neither has been altered since.

- **Calibration intercept 0.3014 against an absolute limit of 0.10.** The stated fraud probability
  cannot be taken at face value. Ranking is unaffected, which is why catch rate at a fixed capacity
  is still trustworthy, but any process that reads the number itself is not.
- **16 population stability results at the automatic-promotion block threshold**, 9 of them after the
  training window. The applicant mix moved materially, so results measured on older months may not
  hold on newer ones.

**Do not adopt the concentration rule set**, on the overflow in section 4.

**Do approve these four operating changes, none of which need a model promotion.**

1. **Fix the capacity overshoot.** Define a deterministic tie-break at the cutting score so the queue
   lands on the staffed headcount instead of 1% to 2.5% above it. This is a change to how the cut is
   taken, not to the model, and it recovers unbudgeted review volume every period.
2. **Apply the recalibration control to the incumbent score proxy, corrected 2026-08-10.** An
   earlier version of this document recommended recalibrating the incumbent on the grounds that its
   intercept is 0.2987. The walk-forward disproved both halves of that reasoning: recalibrating on
   the preceding period does not bring the intercept inside the limit in any of ten observations, and
   the incumbent's expected calibration error runs between 0.00024 and 0.00327 across the five
   periods, so its probabilities already match observed frequencies closely where applications
   actually sit. There is no calibration defect there to repair. What should be applied is the
   control on its own terms: recalibrate at period close and raise a review when the observed prior
   moves more than 0.10 in logit, as a response to prior drift rather than as a fix for a metric.
3. **Raise monitoring cadence on the attempt-rate trend.** A 69% rise across six periods with falling
   volume warrants monthly review of the trend rather than incidental observation, and the rising
   reviewer hit rate must not be reported as an efficiency gain.
4. **Run the daily suspect-application report into the investigation queue.** It is built and
   validated and produces roughly 150 referrals a day. It is independent of the promotion decision.

## 6. Conditions under which I would withdraw the refusal

Stated in advance so the next review is a measurement rather than an argument.

**On calibration, corrected 2026-08-10.** An earlier version of this document proposed recalibrating
on the most recent closed period and re-measuring. The walk-forward has now tested exactly that, and
it does not work. Every one of the five folds calibrated on the period immediately before its test,
and the intercept failed in all five: -0.4255, +0.4128, +0.2783, -0.3104 and +0.3014 against a limit
of 0.10. The calibration slope stayed inside its own 0.8 to 1.2 band in every period. The failure is
structural, not a property of month 7, and recalibration is not the remedy.

The backtest also produced the clearest evidence yet that the check is not measuring what it was
written to measure. Across five periods and both models, ten observations, two calibration metrics on
the same predictions disagree completely:

| Metric | Limit | Result |
| --- | --- | --- |
| Expected calibration error | at most 0.02 | **passes 10 of 10**, worst 0.00449 |
| Absolute calibration intercept | at most 0.10 | **fails 10 of 10**, best 0.2066 |

They differ in where they read. Expected calibration error compares predicted against observed
probability across the actual score distribution. The intercept reads the recalibration line at
probability 0.5, roughly 5.66 logits above where any application in this population sits. One of
these is describing the probabilities the desk would actually use.

Two things follow. There is no operational change available that passes this check as written, so it
should be recorded as a standing limitation rather than as work in progress. And the parameterisation
is now the substantive question for a governance forum: reading the intercept at the operating point
rather than at probability 0.5 is a change only a newly approved evaluation contract can make. I am
not asking for a waiver, and I am not proposing to tune toward the check. I am asking that the
evidence above be considered when the contract is next revised.

**On stability.** Investigate the 16 blocking results and establish whether they are seasonal
movement or a durable population shift. The features driving them are fraud-pressure signals:
application velocity at four weeks, twenty-four hours and six hours, postal-area concentration, and
birth-date to email concentration. If they are seasonal, the check passes on a longer reference
window under a revised contract. If the population has genuinely shifted, the model should be refit
before promotion rather than promoted and monitored.

**What would not change my position.** A better result on month 7. The evaluation contract fixes the
untouched period and I will not re-read it to support a promotion.

## 7. Segment position

Two attributes triggered governance review and both were examined and formally accepted by the
accountable human on 2026-08-10. The differences themselves are unchanged.

**Age** is a prevalence artifact. Its review-rate ratio moves from 0.397 to 0.836, inside the
contract band, once each band's own fraud rate is accounted for, and the attribute is audit-only and
never used as a model input.

**Housing status** is not a prevalence artifact and was accepted on an explicit business-justification
record. Between the two publishable groups, one is reviewed at 19.13% and the other at 1.40%. After
adjusting for each group's own fraud rate the ratio is 0.484, so roughly half the difference is not
explained by where fraud is. Removing the attribute was measured rather than assumed: it costs 2.39
percentage points of catch and 63 fraud attempts per period, brings the adjusted ratio to 1.119 and
the false-positive gap under its trigger, and still leaves two of three triggers firing. It also
closes the gap partly by levelling down, with the more-reviewed group losing 97 caught frauds so the
less-reviewed group can gain 21, for 63 fewer caught overall. Group membership remains recoverable
from the remaining 32 inputs at AUROC 0.799 and 0.770, so removal takes away the ability to audit the
segment rather than the behaviour.

The attribute is retained. The acceptance covers the measured values recorded on the date it was
given and lapses if any accepted gap widens by more than 0.05 or a review-rate ratio falls by more
than 0.05. No group-specific threshold exists anywhere in this process, and none is proposed.

## 8. What would change this document

Three pieces of work are in progress and each could move a number above.

- **Economics are now a range, and the range is wide.** Resolved 2026-08-10. Review effectiveness and
  loss given fraud are modelled as explicit sensitivity dimensions, giving the $0.57M to $9.58M band in
  section 4 in place of the former $2.36M to $9.58M point-anchored figure. The comparison's sign holds
  everywhere. Neither factor could be sourced to this project's citation standard, so both are declared
  inputs and no figure derived from them is an observed result. The promotion gate still uses the
  approved 60-point grid at both factors equal to 1.0, unchanged, because widening the grid a gate is
  measured against needs a newly approved evaluation contract.
- **The headline rested on one period. Resolved 2026-08-10.** A five-period walk-forward now gives the
  range quoted in section 4. It also corrected an earlier estimate of mine: I had put between-period
  variation at 1.74 times the within-period interval, using periods the model had trained on. Measured
  out of sample the two are about equal. The reported interval still understates the decision, but
  because a next-period decision faces both sources at once, not because one dominates.
- **Labels arrive late. Resolved 2026-08-10.** Recent periods in section 3 are incomplete and will
  worsen as labels arrive, so the rise in attempt rate is a floor rather than a point estimate. Two
  consequences went on the record. The M6 recalibration control does not survive censoring and has been
  superseded: at its own reporting point the newest cohort is 0% mature and the control has no input,
  and one period later the censoring bias is 5.4 times its own threshold, always in the direction that
  suppresses the alarm. And the reviewer hit rate in section 2 is a leading indicator available within
  days, while the catch rate beside it lags by 30 to 90 days and longer, because they share a numerator
  and only the denominator is slow. See `docs/label-latency.md`.

## 9. Limitations

- BAF is privacy-preserving synthetic account-opening data. It is not observed personal-loan or
  auto-loan performance and nothing here is a production result.
- `credit_risk_score` stands in for a third-party decision score. It is not a verified vendor product
  and its performance here is not a vendor service level.
- Identity-linking evidence comes only from a separate deterministic fixture. No BAF application is
  linked, duplicated, or described as part of a ring.
- No simulated action in this document declines an applicant. The process ranks, explains, and
  recommends; a person decides.
