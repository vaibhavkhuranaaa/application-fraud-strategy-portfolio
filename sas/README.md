# SAS translations

**These are translations, not production experience.** The posting lists SAS first among its
required tools. This project is built in Python and SQL, and `PROJECT.md` limits SAS claims to
documented equivalents. That policy previously had no artifact behind it; these files are the
artifact.

What they are: the two pieces of logic a fraud desk would most plausibly need in SAS, written out
so the equivalence between the Python implementation and a SAS one is legible and checkable. What
they are not: code that has been executed. There is no SAS licence in this environment, so nothing
here has been run, and no output is claimed.

| File | Python source it translates | What it does |
| --- | --- | --- |
| `score_to_probability.sas` | `src/fraud_strategy/calibration.py` | Maps an incumbent score to a calibrated probability through fixed reference statistics and a prior shift |
| `review_queue.sas` | `src/fraud_strategy/strategy.py` | Ranks a scored population and cuts it at a review capacity, with the tie behaviour made explicit |

Both carry the same boundaries as the rest of the program: no automatic decline, one population-wide
threshold, and no group-specific treatment.

## Why these two

They are the operations a desk runs daily and the two most likely to be reimplemented in whatever
tool the team already has. The modelling itself is not translated: a gradient-boosted model is not
meaningfully expressible in a DATA step, and pretending otherwise would be the kind of claim this
repository exists to avoid.

## The tie behaviour is the interesting part

`review_queue.sas` reproduces a finding the Python program measured rather than assumed: a score
threshold cannot land on an exact reviewer headcount when the score has ties, because every
application at the cutting value has to be treated alike. The incumbent proxy is a low-cardinality
integer score and its queue therefore exceeds staffed capacity by 1.06% to 2.45% every period. The
SAS translation makes that visible in the code rather than hiding it behind a `WHERE` clause, and it
shows the deterministic tie-break the strategy document recommends as the fix.
