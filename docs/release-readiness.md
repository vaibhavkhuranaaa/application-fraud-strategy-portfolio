# Release readiness

Status: `M20 release verified and publication-approved on 2026-08-18; 93 unit and contract tests pass; unchanged container and database-recovery checks were not rerun`

This is the human-readable companion to `evaluation/release_quality.json`. It answers one question
per approved success criterion, and it names what was not verified rather than leaving the gap silent.

Measured on: Apple M5, 10 logical cores, 16 GB RAM, macOS 26.5. The approved reference environment is
4 vCPU and 16 GB RAM, so every latency figure here is optimistic relative to that reference and must not
be read as a floor for it.

## Success criteria

### 1. A reviewer can reproduce provenance, checksums, feature eligibility, sentinel handling, temporal splits, model selection, calibration, and strategy evidence

**Verified.** All six source checksums and all six curated artifact hashes were recomputed and matched
`evaluation/data_curation.json`. The feature contract, sentinel conventions, and split protocol are fixed
in `src/fraud_strategy/config.py` and `evaluation/report.md`, and the Data operations screen renders
them from evidence rather than from prose. The analytics extract regenerates byte-identically from the
committed evidence. Dependencies are pinned in `uv.lock`.

### 2. Every scenario reports catch rate, friction, review demand versus capacity, confidence intervals, segment effects, and assumption-led economic sensitivity

**Verified after a fix.** Catch rate, false-positive rate, review demand against capacity, overflow, and
assumption-led scenario value were already reported per scenario. Confidence intervals were not - the
M3 bootstrap intervals existed in evidence but reached no screen. They now appear on the strategy
scenario and on the model capacity table.

The intervals are shown only where they apply. They were bootstrapped for score-only policies at the
four approved capacities, so a rule-enabled policy or a fifteen-percent capacity now says that no
interval was pre-computed instead of borrowing one that describes a different policy. Segment effects
live on the Model and governance screen, which the refusal on every other screen points to.

### 3. The model is promoted only when it passes the pre-approved gates; otherwise the baseline is retained and the negative result is published honestly

**Verified.** Two of eleven gates failed and the incumbent proxy was retained only as a temporary ranking
baseline. The refusal is the headline of every screen, the failed gates print DID NOT PASS as well as the
colour, and the rejected
challenger's manifest is kept alongside the champion's so the rejection stays auditable. No control in
the interface can turn the refusal into a recommendation: model and governance gates are applied above
any frontier point.

### 4. Identity-linking quality is measured only against the fixture's held-out truth; BAF concentration features are never presented as recovered identities or rings

**Verified.** The linking screen leads with the boundary, not the result: BAF rows were generated
independently and contain no recoverable shared identity. Fixture gates, per-seed runs, and the truth
boundary are rendered from `evaluation/linking_evaluation.json`. Concentration rules are labelled as
aggregate counts on a single application everywhere they appear, including in the queue's rule column
and in the Power BI specification.

### 5. The dashboard and the report explain evidence source, period, freshness, assumptions, confidence, supported decision, and limitations in stakeholder language

**Verified for the dashboard.** Every exhibit carries the question it answers, its units, and a source
line naming the period and population. The dataset version and evidence revision sit in the colophon.
Assumptions carry a distinct marker and the word "assumption", and the two money measures are the only
figures derived from them. Promotion checks are rendered as plain requirements - "Risk estimates are not
systematically off" - with the consequence of each failure stated beneath it, never as gate identifiers.

**Not verified for the Power BI report.** See the limitations register below.

### 6. Local execution is fully reproducible; Azure staging is deployable through approved infrastructure-as-code, with no cloud resource provisioned

**Partly verified.** Local reproducibility is verified: recorded month-7 policies reproduce exactly from
the stored scores, the analytics extract regenerates byte-identically, curated hashes match, migrations
are idempotent, and the database recreates from an empty volume.

The second clause is **partly** met as of 2026-08-09. `infra/azure-staging/` now holds Terraform for the
costed staging design, and it passes `terraform fmt -check` and `terraform validate`. That proves the
configuration is syntactically correct and internally consistent - nothing more. It has never been
planned against a subscription, applied, or torn down, so "deployable" is not established. No cloud
resource exists, which is the part of the criterion that fully holds.

## Gate families

| Family | Result |
| --- | --- |
| Evaluation | The M3 contract's gates were applied unchanged; two failed and the refusal stands. Recorded policies reproduce exactly from the stored scores. |
| Business usefulness | The five design journeys complete end to end. Two defects were found and fixed during this review: missing confidence intervals, and policy choice not carrying from the strategy screen to the queue. |
| Accessibility | Re-measured on the static dashboard at five viewport widths: zero contrast failures across 656 visible text nodes (worst 5.11:1), no horizontal page scroll, zero unnamed controls, zero positive `tabindex`, one `h1`, every table with real headers, every chart carrying a text finding. Full results in `evaluation/ux_evaluation.json`. |
| Security | The M20 run is clean for regex secrets, audited `detect-secrets` findings, dependency vulnerabilities, SQL interpolation, and dangerous constructs. The container was not rerun because this candidate does not change the Dockerfile, dependencies, runtime, or scoring code. The historical clean container result is labelled below. |
| Reproducibility | Source and curated checksums verified, extract regenerates byte-identically, recorded policies reproduce, dependencies pinned. |
| Recovery | The M20 run skips database recovery because this candidate changes no migration, database, model, or artifact path. The verified 2026-08-10 recovery result is carried forward as historical evidence, not presented as a new run. |
| Performance | Single-record champion scoring p95 0.001 ms, verified identical alone and in a batch; single-record challenger scoring p95 0.675 ms against a 250 ms budget; full scenario computation over 96,843 rows p95 22.4 ms against 2 s; one-million-row batch scoring in 0.75 s against 15 minutes. The batch is verified as well as timed: its month-7 slice matches the recorded prediction artifact exactly, maximum absolute difference 0.0. |

### Historical container scan

The unchanged worker image was last scanned on 2026-08-10. That run reported **0 critical, 0 high, 0 medium,
and 0 low** findings. The current `evaluation/release_quality.json` correctly records that the container and
database-recovery checks were skipped for this dashboard and governance-only candidate.

Getting there took three attempts, and the first two are worth recording because they show why the
obvious fixes do not work:

1. **Purge the `perl` package.** Removes the `IO::Uncompress::Unzip` module named in CVE-2026-48959 -    verified absent - but the scan does not improve. `perl-base` is Debian-essential, provides
   `/usr/bin/perl`, and is built from the same source package, so all four findings stick to it.
2. **Move to a Debian 12 base** (`python:3.12-slim-bookworm`). Same result: every Debian carries an
   essential `perl-base`.
3. **Remove the distribution.** A two-stage build now compiles the locked environment on
   `python:3.11-slim-bookworm` and copies it into `gcr.io/distroless/python3-debian12`, which has no
   shell, no package manager, and no perl. That cleared every finding and cut the image from 2.74 GB to
   1.31 GB.

Verified functional offline: the container starts with `--network none`, CatBoost loads the 450-tree
model, and every dependency imports.

A separate defect was found while smoke-testing the remediated image: the entrypoint used `uv run`,
which re-resolved dependencies at container start and pulled the dev group, making start-up depend on
the network. The entrypoint now runs the interpreter from the locked environment directly, verified by
starting the container with `--network none`.

### Artifact hash is not a model fingerprint

The full retrain produced byte-different `catboost_hybrid.cbm` files across runs while every recorded
metric matched to 1e-12. CatBoost embeds `train_finish_time` and a `model_guid` in the saved model, so
the recorded `artifact_hash` identifies a *file*, not a *model*: two functionally identical models hash
differently.

The hash remains valid for lineage and rollback, which is what it is used for today. It must not be
used to assert that two models are the same. Recording a behaviour fingerprint - a hash of predictions
over a fixed deterministic sample - would give that property, and is deferred to M6 rather than done
now, because it would require another full evidence regeneration for a field that only matters once a
model is deployed.

## Limitations register

Stated plainly, because a reader deciding whether to trust this work needs them more than the results.

1. **BAF is synthetic.** Every performance figure describes CTGAN-generated account-opening records, not
   observed loan-origination outcomes. No production-performance claim is made anywhere.
2. **Economic figures are assumptions.** BAF records no exposure, review cost, conversion value, or P&L.
   Scenario values are arithmetic over analyst-entered inputs from published benchmark ranges.
3. **The challenger failed promotion and the governance work is open.** The calibration intercept, the 16
   distribution-shift blocks, and the age and housing segment review are unresolved by design, not by
   oversight.
4. **~~The champion cannot score a single application in isolation.~~ Fixed 2026-08-09.** The mapping now
   uses fixed reference statistics fitted on the calibration period and persisted in the champion
   manifest, so an application scores identically alone and inside any batch, and month 7 is no longer
   scored against its own distribution. The fix changed the incumbent's month-7 probability-quality
   metrics - its ECE moved from 0.000096 to 0.001966 and its calibration intercept from 0.143 to 0.299 -    and changed nothing else, because the mapping is monotonic. The earlier ECE should not be cited. See
   the correction section of `evaluation/report.md`.
5. **~~The linear comparator was measuring nothing.~~ Fixed 2026-08-10.** It used a stochastic solver with
   no class weighting, which at roughly 1% prevalence stops at the base-rate solution, so for five
   milestones the simplest comparator returned chance-level ranking and nothing in the suite noticed.
   Corrected, it scores AUROC 0.8848 and PR-AUC 0.1787 rather than 0.5156 and 0.0163. Two consequences.
   The lift gate is now measured against a real baseline and the recorded lift falls from 0.1725 to
   0.0342, still above zero. And the gap between a linear model and gradient boosting on this problem is
   about four percentage points of catch, not the chasm the earlier evidence implied. The suite now
   carries a regression test that fails if any comparator sits at the base rate. See the M6 section of
   `evaluation/report.md`.
6. **The Power BI artifact is unverified.** Power BI Desktop is Windows-only; the semantic model,
   measures, and specification have never been opened, refreshed, or evaluated. No `.pbix` exists.
7. **Terraform is authored but unapplied.** `infra/azure-staging/` passes `terraform fmt` and
   `terraform validate`, which proves it is syntactically correct and internally consistent. It has never
   been planned against a subscription, applied, or torn down, so nothing about deployability, quota, or
   the cost estimate is verified.
8. **No API, no authentication, no load testing.** The stakeholder surface is static files with no
   request handler, so the approved API latency SLO has nothing to measure and all timings are
   single-user. Being static is what removes the authentication and hosting-cost questions entirely;
   adding a server process would reopen both.
9. **Fixture linking results transfer to nothing else.** They describe the deterministic fixture and are
   not evidence about BAF or about production identity resolution.
10. **~~Screenshot sign-off is open.~~ Closed 2026-08-10.** The `DESIGN.md` quality gate was
    re-approved after the screenshots were regenerated and a local preview reviewed, before
    deployment approval was given. That build measured zero contrast failures, a 5.11 minimum
    ratio and a 40.8 ms median render.
11. **~~The container image carries known base-image vulnerabilities.~~ Fixed 2026-08-09** by moving
    the runtime stage to distroless. Scan is now clean at every severity. The image has no shell and no
    package manager, which also means no in-container debugging: diagnose from logs, or run the build
    stage locally.
12. **The recorded artifact hash identifies a file, not a model.** CatBoost embeds a finish time and a
    GUID, so a functionally identical model hashes differently after a retrain.

## Reproducing this verification

```bash
python3 -m http.server 8060 --directory dashboard             # separate shell
PYTHONPATH=src uv run python scripts/ux_check.py
PYTHONPATH=src uv run python scripts/release_check.py
```

`release_check.py` needs a local Docker daemon and `FRAUD_DATABASE_URL` for the container and recovery
sections; pass `--skip-container --skip-recovery` to run the rest without them.
