# Monthly fraud readout, Period 7

Status: `prepared 2026-08-10 for management and business partners`
Source: PostgreSQL fraud schema, `analytics.fact_daily_strategy`. Workbook: `docs/samples/monthly-fraud-kpi.xlsx`.

This is the readout that accompanies the workbook. It is written as a document rather than as a
`.pptx` deliberately: a slide binary cannot be reviewed in a diff, and everything of value here is
the numbers and the boundaries around them. The decision is recorded in the case study.

---

## Slide 1. Headline

**Fraud pressure is up 69% while application volume is down 36%.**

- Attempt rate 87.5 bps in period 2 to **147.5 bps** in period 7
- Applications 150,936 to **96,843**
- Fraud attempts this period: **1,428**

Read the attempt rate as a floor. Labels mature over 30 to 90 days and longer, so recent periods are
incomplete and will worsen.

---

## Slide 2. What the desk did

| | Period 7 |
| --- | --- |
| Cases worked | 4,916 |
| Fraud caught | 295 |
| Catch rate | 20.7% |
| Reviewer hit rate | 6.0% |
| Fraud reaching approval unchecked | 1,133 |
| Reviews above staffed capacity | 74 |

**The rising hit rate is not the team improving.** A fixed review capacity is meeting a richer pool of
fraud. Hit rate is available within days; catch rate lags by a quarter. Do not read them the same way.

---

## Slide 3. The one thing to fix this month

**The queue runs over its own staffing every period, by 63 to 168 cases.**

The incumbent score is a low-cardinality integer, so the block of applications sitting exactly on the
cut cannot be split. Every application at the cutting value has to be treated alike, and the queue
overshoots by that block.

This is unbudgeted review volume being worked every month. The fix is a deterministic tie-break at
the cutting score, which is a change to how the cut is taken and not to any model.

---

## Slide 4. The proposed approach, and why it is not recommended

At the identical 4,843 cases worked, the proposed approach would have caught
**471 more fraud attempts** and held up **544 fewer good customers**. It is better on both
axes at the same cost.

**It is still not recommended.** It fails two of eleven checks agreed before any result was seen:

1. Calibration intercept, so a stated fraud probability cannot be taken at face value
2. Population stability, so results from older months may not hold on newer ones

A five-period backtest puts its catch rate between 49.0% and 54.2%, averaging 52.5%. The honest range
for a future period is 45.9% to 59.1%.

---

## Slide 5. Ask

1. **Approve** the tie-break fix. No model change, recovers unbudgeted review volume.
2. **Approve** raising monitoring cadence on the attempt-rate trend.
3. **Note** that adding reviewers is the expensive lever here: doubling capacity under today's
   screening reaches 30.8% catch, still short of what the proposed approach does at half the headcount.
   The constraint is ranking quality, not staffing.
4. **No decision requested** on the proposed approach. It returns when the two failing checks are
   resolved or the evaluation contract is revised.

---

## Boundaries

- BAF is privacy-preserving synthetic account-opening data, not observed originations.
- Periods are relative BAF months labelled Period 0 to Period 7, not calendar months.
- `credit_risk_score` is an incumbent score proxy standing in for a third-party decision score. It is not a verified vendor product and its performance here is not a vendor SLA.
- Catch rate assumes review prevents the fraud it finds; review effectiveness and loss-given-fraud are not modelled, so every figure is an upper bound.
- No period in this pack authorises a policy. Both scenario runs carry the recorded refusal.
- Reviewer hit rate is a leading indicator, available within days, because a review confirms fraud at review time. Catch rate shares that numerator but divides by all fraud in the period including what slipped past review, so it is lagging by 30 to 90 days and longer. The most recent periods here will get worse as labels arrive, so the rise in attempt rate is a floor rather than a point estimate. See docs/label-latency.md.
- `capacity_overshoot` is the queue above the reviewer headcount the capacity implies. It is a property of cutting a tied score, not a modelling error: applications at the cutting value cannot be split, so a low-cardinality score overshoots by its tied block.
