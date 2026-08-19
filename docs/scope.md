# Scope and KPIs

## Product decision

This project supports a fraud strategy owner's decision about whether a proposed application-fraud model
is safe to promote and how a fixed reviewer team would experience bounded screening scenarios. The verified
answer is a refusal: the challenger is rejected, the incumbent proxy is retained, 9 of 11 pre-agreed checks
pass, and there is `no robust recommendation`.

## KPIs

| KPI | Definition | Decision use | Boundary |
| --- | --- | --- | --- |
| Fraud capture | Fraud cases sent to review divided by all fraud cases | Compares screening value at fixed capacity | Retrospective synthetic evidence |
| Investigator hit rate | Fraud cases found divided by reviewed applications | Shows review-team precision | Labels mature after review |
| Good customers held | Non-fraud applications sent to review | Quantifies customer friction | Not a denial or realised harm |
| Capacity use | Reviewed applications divided by available review slots | Tests operational feasibility | Capacity is a declared input |
| Calibration and stability gates | Fixed evaluation checks recorded before the holdout opened | Govern automatic promotion | Failing either preserves the refusal |
| Economic range | Avoided-loss sensitivity less review and friction assumptions | Tests whether conclusions survive assumptions | Not realised savings or return |

## In scope

- Time-ordered comparison of an incumbent proxy, corrected linear baseline, and CatBoost challengers.
- Fixed promotion gates, capacity-bounded scenario exploration, and explicit refusal behavior.
- Aggregate fairness, stability, robustness, and calibration evidence with suppression rules.
- A separate synthetic fixture for matching quality and adversarial signal corruption.
- A static decision workspace, optional local PostgreSQL operating model, authored Power BI source, and
  unapplied Azure staging design.

## Out of scope

- Live lending decisions, automatic decline, automatic model promotion, and group-specific thresholds.
- Production-performance, realised financial, customer-identity, or BAF fraud-ring claims.
- Reject inference, automatic retraining, or a feedback loop without a real label feed.
- Power BI Service publication or a claim that the authored semantic model has been run in Desktop.
- Paid infrastructure, Azure provisioning, or any public release without a separate human gate.
