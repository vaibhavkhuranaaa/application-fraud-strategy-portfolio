# Product


## Platform

web

## Users

**Primary - fraud strategy owner at a consumer lender.** Sits between the fraud operations floor and
the credit/risk committee. Confirmed by the user as non-technical: reads business outcomes, staffing,
and money, not model diagnostics. Their situation is a periodic strategy review: "should we change how
we screen applications, and can the review team absorb it?" Their job on this surface is to reach a
defensible position they can take into a governance meeting, and to see plainly when the evidence does
not support changing anything.

**Secondary - fraud operations manager.** Owns the review queue and the investigators working it. Cares
about alert volume against capacity, investigator hit rate, and how much good-customer friction a policy
creates.

**Secondary - analyst or model reviewer.** The only audience for model discrimination, calibration,
stability, fairness, and lineage evidence. Confirmed by the user that this audience's material moves
behind the main dashboard rather than leading it.

**Tertiary - hiring manager evaluating the author.** Reads the surface as work product. Not designed
for, but the reason the surface must be publicly reachable and self-explanatory without a walkthrough.

## Job

Decide whether to adopt a bounded application-fraud screening strategy, or to refuse and say why, with
the review team's capacity and the customer-friction cost visible at the moment of the decision.

## Capabilities

- Compare screening approaches on one untouched evaluation period.
- Vary review capacity, transparent concentration rules, and three economic assumptions, and see the
  operational and financial consequence.
- Inspect the resulting review queue case by case, with the drivers behind each score.
- Read the governance position: adopt or refuse, and every reason behind it.
- Read the temporary baseline controls, uncertainty, concentration-rule dispositions, monitoring triggers,
  and evidence required to reopen a refusal.

## Constraints

- **The product never issues a lending decision.** No approval, no denial, no account opening. Actions
  are `clear`, `manual review`, and `governance referral`, all simulated and non-binding.
- **The current verified answer is a refusal**: `no robust recommendation`, and that must remain the
  headline. Two of eleven pre-approved promotion checks failed. No control anywhere may turn the
  refusal into a recommendation.
- **The incumbent is a temporary ranking baseline, not an approved model.** It may support a bounded
  manual-review queue and fixed comparison. Its score is not a fraud probability and may not drive an
  automatic applicant decision.
- **Two kinds of number, never blurred.** Observed evidence carries its source and period. Analyst
  assumptions (fraud exposure, review cost, friction cost, capacity) are marked as assumptions and are
  never presented as profit, loss, or realised saving.
- **No identity or ring claim about the source data.** Its publisher states rows have no relationship to
  one another. Cross-row matching results come from a separate synthetic fixture and transfer to nothing
  else.
- **No production-performance claim.** The data is synthetic account-opening records.
- Groups with fewer than 200 fraud cases are shown as withheld, never as zero.
- Free hosting only. No recurring cost, no card on file.

## Evidence

All figures come from a verified local evaluation recorded in `evaluation/*.json`: a checksum-pinned
1,000,000-row modelling population across eight months, a 96,843-row untouched final period, a
50,000-row synthetic matching fixture, and five bias-injected stress variants. Provenance, promotion
checks, fairness, stability, and recovery evidence are all recorded and reproducible.

## Terminology

Use the fraud industry's own words, with a plain-language reading available: fraud capture rate,
investigator hit rate, alert-to-fraud ratio, insult rate (good customers held up), leakage (fraud
missed), referral volume, queue overflow, capacity utilisation. Model vocabulary such as PR-AUC,
calibration intercept, and PSI belongs only in the analyst area.

## Accessibility

WCAG AA contrast, keyboard operable with visible focus, semantic landmarks and real table headers, no
meaning carried by colour alone. Verified by an automated gate at four viewport widths.

## Open decisions

- The public build uses synthetic demonstration rows in its case view. Source rows stay outside the
  public interface.
- The 2026-08-10 release is public. Publishing the risk-control dashboard revision requires a new approval.
