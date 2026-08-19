# Application Fraud Strategy Portfolio

## Portfolio contract

- **Category / industry:** data science analytics / Consumer Lending Fraud
- **Industry question:** Which bounded application-fraud strategy best balances fraud caught, good-customer friction, and manual-review capacity for US personal and auto loan originations?
- **Owner-facing user and decision:** A fraud strategy analyst compares an incumbent-score proxy, internal models, transparent rules, and identity-link flags; tests them under explicit review-capacity and economic assumptions; and recommends or refuses a strategy for governance review. The product never executes a live approval, denial, or account-opening decision.
- **Data classification:** Licensed synthetic application/account-opening records. The approved Bank Account Fraud (BAF) suite contains no direct PII and is stored git-ignored in `data/quarantine/`. Public artifacts may expose aggregate BAF evidence and a separately generated synthetic linking fixture; raw BAF files are not committed or bundled.
- **Current status:** the analytical workflow and improved public decision workspace are complete and publication-approved. The challenger passes 9 of 11 checks but remains rejected on calibration and population stability; the incumbent proxy remains a temporary comparison baseline and the strategy remains `no robust recommendation`. Power BI source is unverified in Desktop, Azure Terraform is unapplied, and no paid resource exists.
- **Product workflow:** validate and curate BAF; compare the incumbent proxy, a regularized logistic baseline, and calibrated CatBoost challengers; test capacity, transparent rules, and declared economic assumptions; inspect the bounded queue; evaluate matching only on a separate labeled fixture; and return a governance recommendation or refusal.
- **Public URL target:** `/projects/application-fraud-strategy-portfolio`
- **GitHub repository:** https://github.com/vaibhavkhuranaaa/application-fraud-strategy-portfolio

## Origin

This companion project targets the OneMain Financial "Senior Loans Fraud Data Analyst" role without relabeling the sibling default-risk project as fraud work. The role scope was supplied by the project owner and is reflected in this charter.

## Success criteria

1. A reviewer can reproduce dataset provenance, checksums, feature eligibility, sentinel handling, temporal splits, model selection, calibration, and strategy evidence.
2. Every scenario reports fraud catch rate, false-positive/friction rate, review demand versus capacity, confidence intervals, segment effects, and assumption-led economic sensitivity.
3. The fraud model is promoted only when it passes the pre-approved temporal, calibration, capacity, robustness, and business-utility gates recorded in `evaluation/report.md`; otherwise the simpler baseline remains champion and the negative result is published honestly.
4. Identity-linking quality is measured only against the deterministic fixture's held-out entity/ring truth. BAF concentration features are never presented as recovered identities or rings.
5. The stakeholder dashboard and Power BI report contract explain evidence source, period, freshness, assumptions, confidence, supported decision, and limitations in stakeholder language.
6. Local execution is reproducible; Azure staging remains an authored scale mapping, and no cloud resource is provisioned without deployment and paid-capacity approval.

## Delivery constraints

- Use `Base.csv` for model development and months 0–7 for temporal evaluation. Use Variants I–V only as frozen-model bias and robustness stress tests.
- Exclude target, split-only, protected/audit-only, constant, and post-application fields according to `docs/data-dictionary.md`.
- Treat `credit_risk_score` as an incumbent-score proxy, not a verified third-party vendor product.
- Keep economic outputs assumption-led; BAF contains no observed loan exposure, review cost, conversion value, or production P&L.
- Keep SAS claims limited to documented Python/SQL equivalents. Use PostgreSQL, not DuckDB. Do not add Spark, Kafka, Kubernetes, Airflow, a feature store, or a separate ML platform without measured need and approval.
- Do not provision, spend, deploy, publish, create GitHub, or change visibility without the matching human approval gate.
