# Risk control framework

## Current disposition

The challenger is not approved for rollout. Nine of eleven pre-agreed checks passed. Calibration and
population-stability checks failed, so the recorded answer remains `no robust recommendation`.

The incumbent proxy is retained only as a temporary ranking baseline. Retained does not mean approved.
It may rank a bounded manual-review queue and serve as the fixed comparator for later evaluation. It may
not issue or influence an automatic approval, decline, price, or account-opening decision. Its score may
not be read as a calibrated fraud probability.

## Operating control

The Fraud Strategy Owner reviews the baseline monthly after labels mature and immediately after an
escalation trigger. Manual review, explicit queue capacity, visible calibration and stability evidence,
and the unchanged eleven-check promotion contract are compensating controls.

Escalate if the score is used outside bounded manual-review ranking, demand exceeds capacity, a monitored
control breaches, or labels are too immature for the reported period. Suspend use if the controls cannot
be operated. Replace the baseline only after a challenger passes every pre-agreed check and governance
approves its use.

The accountable roles in this framework are a proposed operating design. They are not evidence that a
real organization accepted responsibility.

## Decision uncertainty

At five percent review capacity in the held-back period, the challenger caught 472 more labelled fraud
attempts and held up 472 fewer records labelled as good than the incumbent proxy. A fixed-seed paired
row bootstrap places the fraud-catch difference between 425 and 519 and the good-review difference
between 628 fewer and 317 fewer, at 95% confidence. The challenger caught more fraud in all five
time-ordered folds, with fold differences of 440, 474, 460, 439, and 472.

This interval is conditional on frozen rankings in one synthetic period. The five-fold direction does not
establish future production performance, and neither result changes the recorded refusal.

## Concentration-rule disposition

| Rule | Disposition | Fraud change | Good-review change | Overflow | Reason |
|---|---|---:|---:|---:|---|
| Birth-date and email concentration | Reject | -281 | +38,018 | 37,737 | Overwhelms capacity and displaces higher-ranked fraud |
| Device and email concentration | Refer for validation | -53 | +53 | 0 | May remain a reason code, but worsens this queue and lacks temporal validation |
| Foreign request with weak identity similarity | Reject | -27 | +27 | 0 | Adds friction and reduces fraud caught |
| Selected-branch concentration | Reject | -65 | +65 | 0 | Adds friction, reduces fraud caught, and uses a final-period cutoff |

Changes are against the challenger-only queue at the same five-percent capacity. Each result describes one
synthetic held-back period. Rule overlap is between application records, not identities or fraud rings.
No rule may create an automatic decline or unbounded review demand.

## Monitoring and remediation

| Control | Accountable role | Availability | Trigger and response |
|---|---|---|---|
| Calibration | Model Risk | Retrospective only | Above 0.10 absolute intercept: prohibit probability use and promotion |
| Population stability | Fraud Strategy Owner | Retrospective only | Any 0.25 PSI block: keep rollout blocked and investigate the shift |
| Investigator review yield | Fraud Operations | Needs production data | Fall against a governed trailing baseline: investigate queue composition |
| Review capacity | Fraud Operations | Scenario-measurable | Any overflow: stop expanding referrals and return to governance |
| Customer friction | Customer and Conduct Risk | Needs production data | Leaves an approved band: pause the change and review causes |
| Label maturity | Data and Model Governance | Needs production data | Missing maturity or timestamp lineage: keep outcomes non-operational |
| Segment performance | Fair Lending and Model Governance | Retrospective conditional acceptance | Accepted gap widens over 0.05: reopen governance review |

The decision may be reopened only after a challenger passes all eleven unchanged checks on untouched
evidence, required operating feeds are verified, owners accept every control and response, and governance
approves the bounded use. Designed role ownership is not evidence of organizational acceptance.
