# Decision 0002: Control the retained baseline

Date: 2026-08-18

## Decision

Classify the incumbent proxy as a temporary ranking baseline, not an approved probability model. Limit it
to bounded manual-review ranking and fixed comparison. Assign a Fraud Strategy Owner role, a monthly
cadence after label maturity, compensating controls, escalation triggers, and explicit exit criteria.

## Why

The existing evidence says the challenger is rejected and the incumbent is retained. Without an operating
disposition, a reader could mistake retention for approval even though the incumbent has similar
calibration concerns and no production validation.

## Alternatives rejected

- Call the incumbent approved because it remains in place. The evidence does not support that claim.
- Remove the incumbent from comparison. That would erase the named baseline every challenger must beat.
- Add automated decisions. The product contract permits manual review and governance referral only.

## Not done

No model, threshold, promotion check, score, or evidence value changed. No real person is claimed to have
accepted an owner role.

## Changed

The machine-readable disposition and its stakeholder summary now define what retained means, who would
operate it, when it is reviewed, what triggers escalation, and how it exits.
