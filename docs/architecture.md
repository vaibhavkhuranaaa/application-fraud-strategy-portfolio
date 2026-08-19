# Architecture

## Decision flow

1. Six approved BAF files are checksum-verified outside Git, typed, and curated to local Parquet.
2. Time-ordered model evaluation selects on months 0 to 5, calibrates on month 6, and opens month 7 once.
3. The strategy layer applies the fixed capacity, calibration, stability, fairness, and robustness gates.
4. Aggregate evidence is written to versioned JSON. Raw rows, curated data, fitted models, and predictions
   remain local and ignored.
5. The dashboard builder converts only reviewed aggregate evidence and a bounded synthetic queue sample
   into a static lookup payload.
6. GitHub Pages serves the reviewed `dashboard/` directory. The page makes no request to a database,
   application server, analytics service, or third party.

## Components

| Component | Responsibility | Runtime boundary |
| --- | --- | --- |
| `src/fraud_strategy/` | Curation, modeling, linking fixture, policy evaluation, and optional operations | Local Python and containers |
| PostgreSQL Fraud Schema | Scored applications, review queues, KPI facts, and governance events | Local optional operating model |
| `evaluation/` | Versioned aggregate metrics, gates, and release results | Public evidence without source rows |
| `scripts/build_dashboard_data.py` | Validates evidence and builds the static policy lookup | Local release build |
| `dashboard/` | Stakeholder decision, bounded scenarios, exhibits, and sampled drill-down | Static GitHub Pages site |
| `powerbi/` | Authored semantic model, measures, and report specification | Unverified until opened in Power BI Desktop |
| `infra/azure-staging/` | Unapplied mapping to managed Azure services | Separately gated and never provisioned |

## Trust and evidence boundaries

- The dashboard is read-only and cannot approve, decline, promote a model, or change a policy.
- The challenger remains rejected. Controls only select among precomputed evidence rows.
- Observed measures and analyst assumptions are labelled separately.
- Groups with fewer than 200 fraud cases are withheld at the point where a value would be written.
- BAF rows contain no recoverable identity relationship. Matching evidence comes only from a separate
  deterministic synthetic fixture with held-out truth.
- The public repository contains aggregate evidence and a bounded synthetic demonstration sample, not raw
  or curated datasets, fitted models, predictions, delivery state, or generated code graphs.

## Deployment and recovery

The Pages workflow uploads `dashboard/` exactly as reviewed and stamps a health document with the deploying
revision. It deliberately does not rebuild evidence in CI because the ignored source artifacts are absent.
Rollback is reverting the release commit and allowing the same workflow to redeploy. Teardown is disabling
the Pages site. The deployed surface has no stateful resource and accrues no infrastructure cost.
