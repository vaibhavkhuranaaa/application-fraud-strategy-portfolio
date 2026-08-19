# Power BI report artifact

Executive reporting layer over the same verified evidence the static dashboard in `dashboard/` renders, for readers who want it inside Power BI.

## What is here

| File | What it is | Verified |
| --- | --- | --- |
| `data/*.csv` | Locally generated governed analytics extract - a twelve-table star schema derived from committed aggregate evidence and excluded from Git | Yes: generated and row-counted by `scripts/build_analytics_extract.py`, checked by `tests/test_analytics_extract.py` |
| `data/manifest.json` | Evidence IDs, dataset version, expected row counts, and the publication boundary for the reproducible local extract | Yes |
| `model.tmdl` | Semantic model - tables, typed columns, format strings, relationships, and the Power Query partitions that read the extract | Authored to the TMDL specification; **not opened in Power BI Desktop** (see below) |
| `measures.dax` | Measure library, including the assumption-labelling and withheld-group rules | Authored; **not evaluated in Power BI Desktop** |
| `report-spec.md` | Page-by-page visual specification: every visual, its field bindings, its title, its source label, and its required annotation | Authored |

## Verification status - read this before claiming anything about the report

Power BI Desktop runs on Windows only. This project was built on macOS, so **the semantic
model and measures in this folder have not been opened, refreshed, or evaluated in Power BI
Desktop, and no `.pbix` or published report exists.** They are authored source, not a
verified running report.

What that means in practice:

- Do not describe this as a working Power BI dashboard. Describe it as the governed extract,
  semantic model, measure library, and report specification for one.
- Whoever first opens `model.tmdl` on Windows should expect to fix small syntax or type
  issues, and should record the result before any screenshot or claim is made.
- Publication to the Power BI Service remains separately gated by `publication` in
  a separate publication approval, which has not been requested.

The extract itself is fully verified: it is generated deterministically from committed
evidence and its contents are asserted by the test suite. The generated CSVs are excluded
from Git so the public repository contains no dataset artifact.

## Rebuilding the extract

```bash
PYTHONPATH=src uv run python scripts/build_analytics_extract.py
```

Run this before opening the model and after any evaluation re-run, then confirm
`data/manifest.json` records the new evidence revision.

## Publication boundary

The extract contains aggregate evidence only:

- No application-level record and no raw BAF data.
- No linking-fixture entity or ring truth.
- No secret, credential, or connection string. `model.tmdl` reads local CSVs through an
  `ExtractFolder` parameter that must be pointed at `powerbi/data`.

The BAF suite is licensed CC BY-NC-SA 4.0 (Feedzai; Jesus et al., NeurIPS 2022). Attribution,
NonCommercial, and ShareAlike terms govern every derived result in this folder.

## Content rules the report must keep

These are not style preferences; they are the governance boundary carried over from
`DESIGN.md` and `evaluation/report.md`:

1. The refusal is the headline. `no robust recommendation` appears on the first page and is
   never softened into a recommendation.
2. Every visual carries its evidence source: BAF Base, BAF Variant I–V, or synthetic linking
   fixture.
3. Any measure ending `(assumption)` must be labelled as an assumption on the visual. No
   economic figure is presented as observed profit or loss.
4. Groups with fewer than 200 fraud cases are shown as withheld, never as zero or blank.
5. No identity or ring claim is made about BAF anywhere in the report.
6. No page implies an approval, denial, or account-opening decision.

## Operational tables added 2026-08-10

The model was a model-governance semantic model: gates, drift, fairness, comparator metrics. The
posting asks for operational performance dashboards for the Enterprise Fraud Group, which is a
different question, so four operational fact tables were added alongside the governance ones.

| Table | Grain | Built by |
| --- | --- | --- |
| `fact_monthly_kpi` | period x model | `scripts/build_kpi_pack.py` |
| `fact_channel_kpi` | period x model x channel | `scripts/build_kpi_pack.py` |
| `fact_risk_band_kpi` | period x model x risk band | `scripts/build_kpi_pack.py` |
| `fact_vendor_performance` | period | `scripts/build_kpi_pack.py` |

These are aggregated in PostgreSQL from `analytics.fact_daily_strategy` and require a database
populated by `fraud_strategy.cli operate`. The governance tables still come from
`scripts/build_analytics_extract.py` and need no database.

Three boundaries are written as measures rather than as prose, so a visual cannot leave them off:
`Vendor boundary notice`, `Operational boundary notice`, and `Capacity overshoot notice`. The first
two must appear on any page using the operational tables. Periods are relative BAF months labelled
Period 0 to Period 7; they are not calendar months and no visual may format them as dates.

Unchanged: nothing here has been opened in Power BI Desktop, which is Windows-only. No `.pbix` exists
and nothing is published. This remains authored source, verified only by the contract tests over the
extract.
