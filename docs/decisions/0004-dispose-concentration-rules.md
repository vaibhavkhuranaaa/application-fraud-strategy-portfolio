# Decision 0004: Dispose the concentration rules

Date: 2026-08-18

## Decision

Reject three concentration rules as queue overrides. Refer the device and email concentration signal for
controlled validation as a non-binding reason code only. No rule may approve, decline, or create unbounded
review demand.

## Why

At five-percent capacity, every rule worsens the challenger queue. The birth-date and email rule also
creates severe overflow. The device signal improves the retained baseline in one synthetic period, but it
worsens the stronger challenger and has no temporal validation, so it is not ready for operational use.

## Alternatives rejected

- Keep every transparent rule because it is explainable. Explainability does not offset negative marginal
  value or excess customer friction.
- Treat overlapping applications as linked identities. The source rows carry no relationship to one another.
- Hide overflow outside the capacity count. Every governance referral remains visible.

## Not done

No rule issues an automatic decline, uses a group-specific threshold, or changes the recorded model
decision. No identity or fraud-ring claim is made.

## Changed

Each rule now has measured record overlap, unique fraud added, fraud displaced, incremental customer
friction, overflow, an explicit disposition, and its evidence limitation.
