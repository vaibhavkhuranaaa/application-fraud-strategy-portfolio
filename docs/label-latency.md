# Label latency and what it breaks

Status: `analysis recorded 2026-08-10; the maturity curve is a stated model, not a measurement`
Evidence: `evaluation/label_latency.json` (`EV-M8-LABEL-LATENCY-20260810`)
Reproduce: `PYTHONPATH=src uv run python scripts/label_latency.py`

## 1. The assumption nobody wrote down

Every temporal decision in this program assumes a period's labels are complete when the period
closes. Training uses months 0 to 5, calibration uses month 6, evaluation uses month 7, and each is
treated as fully labelled the moment it ends.

Application fraud does not work that way. It surfaces through several channels with different
delays:

| Channel | Typical delay |
| --- | --- |
| First-payment default | 30 to 45 days |
| Never-pay and straight-rollers | 60 to 90 days |
| Confirmed identity theft, customer dispute, affidavit | 60 to 180 days and beyond |

At the moment an application period closes, none of its loans have had a payment fall due. That
period's fraud rate is not merely incomplete. It is close to unobservable.

There is a second problem that is not a delay at all. Synthetic identity fraud frequently never
receives a fraud label: it charges off as credit loss and is recorded against the wrong cause. A
share of true fraud is therefore permanently filed as a good customer. That is target
misclassification, and it behaves differently from latency in the arithmetic below.

## 2. What can be measured here, and what cannot

BAF carries no label timestamps. No vintage curve can be derived from it, and fitting one to the
data would manufacture a result rather than find one. So the curve below is **stated**, structured
on the mechanisms above rather than estimated, and every conclusion in this document is conditional
on it.

| Periods after cohort closes | Share of eventual fraud known |
| --- | --- |
| 0 (at close) | 0.00 |
| 1 | 0.35 |
| 2 | 0.60 |
| 3 | 0.78 |
| 4 | 0.86 |
| 6 | 0.92 |
| 12 | 1.00 |

Plus a declared 15% of true fraud that is never labelled at all.

## 3. The M6 recalibration trigger does not survive this

M6 added an operating control: recalibrate at every period close, and raise a review when the
observed prior moves more than 0.10 in logit from the calibration prior. It was a sound response to
a real problem. It assumed the observed prior is observable.

Running the trigger on censored priors, at each possible reporting lag:

| Reporting lag | Cohort maturity | Compared against | Censoring bias (logit) | Against a 0.10 threshold | Decisions matching the truth |
| --- | --- | --- | --- | --- | --- |
| 0 periods (as written) | 0.00 | 0.35 | undefined | undefined | **0 of 0, nothing to read** |
| 1 period | 0.35 | 0.60 | −0.539 | **5.4x the threshold** | 3 of 7 |
| 2 periods | 0.60 | 0.78 | −0.262 | 2.6x | 2 of 7 |
| 3 periods | 0.78 | 0.86 | −0.098 | 0.98x | 5 of 7 |
| 6 periods | 0.92 | 0.93 | −0.014 | 0.14x | **7 of 7** |

Three things follow, in order of how much they matter.

**As written, the trigger has no input.** It compares the just-closed period's observed prior against
the calibration prior, and the just-closed period is 0% mature. There is no number there to compare.

**At any usable lag the censoring bias dwarfs the threshold the trigger uses.** One period after
close the bias is 5.4 times the trigger's own limit. The trigger cannot distinguish a genuine
movement in fraud pressure from labels that have not arrived yet, because immaturity looks exactly
like a falling fraud rate.

**The bias is directional, and it points the wrong way.** Every bias figure is negative: a newer
cohort is always less mature than the one before it, so the observed prior always understates the
movement. The trigger therefore under-fires, and it under-fires hardest when fraud is accelerating,
because that is when the immature tail is largest. The monthly KPI pack shows attempt rate rising
from 87.5 to 147.5 basis points. That is precisely the regime in which this control would stay
quiet.

### Why under-labelling does not appear in that table

A constant never-labelled share scales both priors in the comparison by the same factor, and a
common factor cancels out of a difference of logits. Under-labelling therefore biases the **level**
of the prior without biasing the **move**, so it does not affect this trigger. It does affect
anything that reads the level, including calibration. Latency does not cancel, because the two
cohorts being compared are different ages, and that difference is the entire bias.

## 4. The repair

Divide the observed rate by the maturity the curve states it has, then compare. On these priors that
restores agreement with the true trigger decision to **7 of 7 at every lag**, including lag 1.

This is a real improvement and it is not a solution. It replaces an unstated assumption that labels
are complete with a stated assumption about how they arrive, and it is exactly as right as the curve
is. With no label timestamps in this dataset the curve cannot be validated here, which is why the
recommendation is to state it rather than to trust it.

The recommended form of the control, superseding the M6 wording:

1. Do not read the just-closed period. It has no information.
2. Compute the observed prior for each cohort and divide by the stated maturity for its age.
3. Raise a recalibration review when the corrected move exceeds 0.10 in logit.
4. Record the curve as an assumption alongside the result, and revisit it as soon as real
   label timestamps exist.
5. Until then, treat the trigger as a directional signal rather than a threshold test, because a
   threshold test on a modelled correction implies a precision the model does not have.

## 5. What is observable inside the latency window

A desk cannot wait 90 days to learn something is wrong. These are the signals available sooner, and
this is the part that changes day-to-day practice.

| Signal | Latency | Why |
| --- | --- | --- |
| Score distribution stability | Immediate | Computed from scores alone. Needs no label. |
| Review rate, queue composition | Immediate | A property of the policy and the score, not of outcomes. |
| **Reviewer hit rate** | **Days** | A review confirms fraud at review time. This is the leading indicator. |
| Catch rate | 30 to 90 days+ | See below. |
| Observed prior, and the recalibration trigger | 30 to 90 days+ | The same problem as catch rate. |

The distinction between the last two rows and the third is the useful one, and it is easy to miss
because both look like outcome metrics.

**Reviewer hit rate is fast. Catch rate is slow. They share a numerator.** Fraud confirmed by a
review is known within days. Hit rate divides that by cases worked, which is known immediately, so
hit rate is available almost at once. Catch rate divides the same numerator by *all* fraud in the
period, including everything that slipped past review and will only surface through default months
later. The slow part is the denominator.

The monthly KPI pack reports both. The hit-rate column is a leading indicator and can be read as
current. The catch-rate column is a lagging indicator and the most recent periods in it will get
worse as labels arrive. The pack records this in its limitations.

## 6. Consequences for the rest of the program

**The evaluation is optimistic about information.** At the moment a desk would score month 7, it
would hold mature labels only through roughly month 4. The model actually deployable at that moment
is two to three periods staler than the one evaluated here. Nothing in the recorded results reflects
that, and closing the gap needs a re-run under a lagged-label protocol rather than a note.

**Rising attempt rate is a floor, not an estimate.** The 147.5 basis points reported for the latest
period is what is known now. It will rise as labels arrive, so the 69% increase in the monthly pack
understates the movement rather than overstating it.

**Retraining cadence is bounded by maturity, not by compute.** A model retrained on a period whose
labels are 35% complete has learned mostly from the fraud that defaults fastest, which is not a
random sample of fraud. Retraining faster than labels mature selects for one kind of fraud.

**The target itself is biased.** Fifteen percent of true fraud never being labelled is not noise; it
is a systematic hole in the negative class, concentrated in synthetic identity, which is the class
most worth catching. Every performance figure in this program is measured against labels that omit
it.

## 7. Limitations

- The maturity curve and the never-labelled share are declared, not measured. Nothing here is an
  observed result about this dataset or any portfolio.
- The analysis treats a period as a month. BAF periods are relative and unlabelled by date.
- It models a single curve applied uniformly. Real maturity differs by channel, product, and fraud
  type, and a production version would need curves by segment.
- Correcting by a stated curve is only as good as the curve, and this dataset cannot validate it.
