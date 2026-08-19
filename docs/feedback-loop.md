# Feedback loop design

Status: `design recorded 2026-08-10; no migration and no code, deliberately`
Depends on: `docs/label-latency.md`, `docs/reject-inference.md`
Schema: `db/migrations/001_fraud_schema.sql`, `db/migrations/002_analytics.sql`

M9 deferred this and M12 records it. Fraud adversaries adapt within weeks, and a model whose
performance is only ever measured at the moment it was built will drift silently. This is the design
against the schema that now exists, rather than against one imagined for it.

## 0. Why there is no migration in this document

M9's finding was that six schemas, two views and a recovery test existed and nothing read or wrote
any of them, so the governed row-level product was architecture on paper. Adding tables for a label
feed that does not exist would recreate exactly that, one milestone after fixing it.

So: the one table this design needs is specified below and not created. It lands with the first
producer that writes to it. Everything else in the design works against tables that are already
populated.

## 1. What already works, with no change at all

**Shadow evaluation is available today.** `scoring.application_scores` is keyed on
`(application_id, model_version)`, so an application can carry a score from every registered model
at once. The operations run already writes two: the retained champion and the rejected challenger.
Scoring a candidate alongside the champion, on the same population, on the same day, needs no schema
change and no new code path. That is the single most valuable property the wired schema turned out
to have, and it was already there.

**Model lineage is recorded.** `scoring.model_versions` carries approval state, artifact hash, code
revision, and now a behaviour fingerprint that identifies what a model does rather than which file it
came from. `analytics.v_model_registry` exposes it.

**Refreshes are audited.** `governance.audit_events` records one row per operations refresh, with
the code revision, the champion, the operating period and capacity. That is the spine a decay series
hangs on: it says what was running when.

**Drift has a home.** `governance.drift_results` exists and the stability program already produces
the rows for it.

## 2. The one thing missing: an outcomes table

`core.applications.target_fraud` is a single boolean set once when the row is loaded. That is fine
for a fixed research dataset and useless for a feedback loop, for two reasons. It cannot express
*when* an outcome became known, so maturity cannot be computed. And it is destructive: a later,
better label overwrites the earlier one, so nothing can be reconstructed.

What is needed is append-only, one row per observation rather than per application:

```
core.application_outcomes
    application_id     references core.applications
    outcome            'fraud' | 'good' | 'unresolved'
    outcome_source     'first_payment_default' | 'never_pay' | 'confirmed_identity_theft'
                       | 'manual_review' | 'chargeback' | 'policy_decline'
    observed_at        timestamptz
    periods_on_book    smallint
    superseded_by      nullable self-reference
    evidence           jsonb
    primary key (application_id, outcome_source, observed_at)
```

Three properties matter more than the columns.

**Append-only.** A label is never updated in place. A revision inserts a new row and points
`superseded_by` at it. Without this, the maturity curve in `docs/label-latency.md` can never be
measured rather than declared, which is the single biggest limitation in this program's monitoring.

**`outcome_source` is not decoration.** It is what distinguishes a 30-day first-payment default from
a 180-day confirmed identity theft, and therefore what lets a vintage curve be fitted per channel and
per product instead of assumed uniform.

**`policy_decline` is an outcome.** A declined application has no fraud outcome and never will, and
recording that explicitly is what keeps `docs/reject-inference.md`'s censored population visible
instead of silently absent.

## 3. Decay tracking

With outcomes timestamped, decay is a query rather than a project.

For each vintage, the cohort of applications from one period, and each model version scored against
it, compute catch rate at the operating capacity using only outcomes known by a given observation
date. That produces a surface: performance by vintage, by model, by observation age.

Two readings come out of it:

- **Down a column**, fixing observation age: is catch rate at 90 days on book falling from vintage to
  vintage? That is decay, and it is the question the loop exists to answer.
- **Across a row**, fixing a vintage: how much did catch rate fall as labels arrived? That measures
  the maturity curve directly and replaces the declared one.

The critical discipline is that the two must never be mixed. Comparing a recent vintage at 30 days
against an older one at 180 days measures maturity and reports it as decay, and it will always look
like the model is getting better. That is the most likely way this loop produces a wrong answer.

## 4. Alert thresholds, tiered by what is observable

`docs/label-latency.md` establishes that outcome-based signals lag by 30 to 90 days and longer, and
that the recalibration trigger has no input at all at period close. So alerts are tiered by latency,
not by severity, and the fast tier carries the operational weight.

| Tier | Signal | Latency | Trigger |
| --- | --- | --- | --- |
| Immediate | Score distribution PSI against the pooled training window | none | warn 0.10, block 0.25, unchanged from the contract |
| Immediate | Review rate against staffed capacity | none | any overshoot above the tie-block, which is a known and measured effect |
| Days | Reviewer hit rate, confirmed fraud per case worked | days | a fall against the trailing four periods, sized when a baseline exists |
| Weeks | Shadow-versus-champion rank disagreement on the reviewed set | none for the score, days for confirmation | a rise in disagreement is an early sign the champion is stale |
| 30 to 90 days+ | Maturity-corrected prior move | lagged | the superseded control in `docs/label-latency.md`, applied at a stated lag, on the approved population only |
| 30 to 90 days+ | Vintage decay in catch rate at fixed observation age | lagged | a fall beyond the between-period spread the walk-forward measured |

The last row is the only one that can confirm decay, and it is the slowest. Everything above it is a
reason to look, not a reason to act.

## 5. What this loop must not do

**It must not retrain automatically.** A model retrained on a period whose labels are 35% complete
has learned from the fraud that defaults fastest, which is not a random sample of fraud. Retraining
cadence is bounded by label maturity, not by compute or by a schedule.

**It must not promote automatically.** The promotion gates exist and a decay signal is not one of
them. A loop that can promote is a loop that can bypass the checks this whole program is built on.

**It must not compute maturity corrections on a population containing declines.** Doing so inflates
the correction by the decline rate. `docs/reject-inference.md` records why.

## 6. Sequence, if this is built

1. A label feed exists and writes `core.application_outcomes`. Nothing before this is worth building.
2. Fit the maturity curve from real `observed_at` values and replace the declared one. Every
   latency conclusion in this repository becomes measured rather than assumed at that point.
3. Turn on shadow scoring, which needs no schema change.
4. Build the vintage decay query and hold it for two full label-maturity cycles before trusting it.
5. Size the alert thresholds against the observed baselines rather than against guesses.
6. Only then consider a random-approval control group, which is the precondition for the product ever
   becoming binding.
