# Decision 0003: Quantify decision uncertainty

Date: 2026-08-18

## Decision

Report a paired 95% row-bootstrap interval around the month-7 fixed-capacity difference and show the
fraud-catch difference for every existing time-ordered fold. Keep this evidence separate from the model
promotion contract.

## Why

The point estimate of 472 additional fraud attempts caught is useful but incomplete. A risk owner also
needs to know whether the advantage survives paired sampling uncertainty and whether its direction holds
across the five untouched fold periods.

## Alternatives rejected

- Infer a paired interval from separate marginal intervals. That discards the row pairing.
- Tune the model or threshold after reading month 7. That would contaminate the held-back period.
- Turn the interval into a new promotion gate. The eleven checks remain fixed.

## Not done

No score, model, capacity, threshold, promotion check, or held-back result changed. The private row-level
inputs are not published.

## Changed

The aggregate governance evidence now carries the fixed-seed paired interval, method, five fold-level
comparisons, and limitations.
