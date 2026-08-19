# Data and model defect record

Status: `recorded 2026-08-10`

The posting names identifying, verifying and analysing data defects and driving root-cause
resolution as a responsibility. This project has four worked examples. They were spread across
delivery records where nobody would find them; this is the single legible account.

Each one follows the same shape: what the symptom was, why nothing caught it, what the actual cause
turned out to be, what changed, and the regression test that now fails if it comes back. The third
and fourth were found by building something else, which is the honest way most defects surface.

---

## 1. A comparator returning chance-level results, undetected for five milestones

**Symptom.** None. Every gate passed, every test passed, and the recorded results looked coherent
for five consecutive milestones.

**What was actually wrong.** The linear comparator, `elastic_net_logistic`, scored AUROC 0.5156 and
PR-AUC 0.0163 against a prevalence floor of 0.0147. It was sitting on the base-rate solution. Its
rolling folds were 0.0093, 0.0099 and 0.0104, all at or below the floor.

**Root cause.** An `SGDClassifier` with no class weighting. At roughly 1% prevalence the unweighted
objective is already near its optimum at the trivial base-rate solution, and a stochastic solver's
stopping rule reads a step-to-step delta rather than a gradient, so it converges there in about
twenty iterations and reports success.

**Why nothing caught it.** Every check was relative. The challenger was compared against the
comparator, and a broken comparator flatters everything measured against it. No test asserted that a
baseline could separate the classes at all.

**Fix.** Replaced with a class-weighted logistic regression on a full-batch solver, same features and
same split: AUROC 0.8848, PR-AUC 0.1787, 49.4% catch at 5% capacity, converged in 33 to 34
iterations. The class weighting is the fix; the full-batch solver removes the second half of the
problem by reading the gradient instead of a delta.

**Consequence beyond the fix.** The lift gate is measured against the strongest baseline, which was
now the linear comparator rather than the incumbent proxy. Recorded lift fell from 0.1725 to 0.0342
and still cleared zero. The real distance between a linear model and gradient boosting turned out to
be 4.3 points of catch at 5% capacity, not the gulf the broken comparator implied.

**Regression test.** The suite now fails if any comparator's AUROC sits near 0.5 or its PR-AUC sits
near the prevalence floor, and if any fold fails to converge.

---

## 2. A champion that could not score a single application

**Symptom.** Found by attempting to measure single-record scoring latency for the release gate. The
champion produced a different probability for the same application depending on what else was in the
batch, and could not score one row at all.

**Root cause.** The incumbent proxy's score mapping standardised against whatever batch it received.
A single row has no distribution to standardise against, and a batch of a thousand has a different
one from a batch of a million.

**Fix.** Persist fixed reference statistics from the calibration period in the model manifest, and
standardise against those. Verified to score an application identically alone and inside a batch.

**Consequence beyond the fix.** It corrected a published figure. The incumbent's month-7 expected
calibration error moved from 0.000096 to 0.001966 and its calibration intercept from 0.143 to 0.299.
The earlier ECE was an artefact of scoring a period against its own distribution and must not be
cited. That correction also revealed that the incumbent and the challenger miss the intercept gate by
the same margin, so the miscalibration is a property of the period rather than a challenger defect.

**Regression test.** Scoring one application alone and inside a batch must agree exactly.

---

## 3. Withheld groups rendering as measured zeros

**Symptom.** None visible. Found while confirming an unrelated control, that no group-specific
threshold exists anywhere in the product.

**What was actually wrong.** The publication rule requires groups with fewer than 200 fraud cases to
render as withheld and never as zero. The page withheld the fraud *rate* and printed the fraud
*count*. A housing group with six applications rendered as zero fraud, and an age band with three
applications rendered as zero. Both read as measured zeros.

**The larger half.** `dashboard/data/dashboard.json` is a public static payload, and it shipped every
suppressed count regardless of what the page displayed. Suppression at render time is not
suppression. The moment the dashboard was hosted, it would have published group estimates the
evaluation contract does not permit.

**Root cause.** The rule was implemented where the number is *displayed* rather than where it is
*written*.

**Fix.** The payload now emits null for the fraud count and rate of any group under the threshold, and
the renderer withholds count and rate together. Application volume is retained, because it shows the
group exists without being a fraud estimate.

**Regression test.** A test fails if any withheld group ships a number in the payload.

---

## 4. A matcher structurally blind to the cheapest evasion

**Symptom.** Ring detection returned zero flags while building the daily suspect report. The linking
evaluation had recorded ring recall of 1.000, so the two results could not both be right.

**Root cause.** The pair acceptance rule is `score >= 0.72 and ({email, phone} intersects the exactly
matching signals)`. Ring members are distinct identities sharing infrastructure, so they match on
device and address and on neither email nor phone. No pair between them can be accepted at any score.
The recorded ring recall came from a separate detection path, not from the pair matcher.

**Why nothing caught it.** The fixture's uniform corruption degrades all four signals together, so it
can never isolate the two the rule depends on. And clean pairwise F1 of 1.000 measures a generator and
a matcher that share assumptions.

**Fix and finding.** Added per-signal corruption to the fixture generator, backward compatible and
byte-identical when unused. Measured: corrupting only email and phone takes pairwise recall from 1.000
to 0.051, a 95% loss. Corrupting only device and address at identical rates leaves recall at exactly
1.000 at every rate. The asymmetry is total, which is what proves the cause is the rule rather than
corruption.

The rule was left in place. Requiring a strong identifier suppresses false merges across shared
households and devices, and a false merge produces a wrong decline on someone who did nothing, which
is the more expensive error. What changed is that the trade is now written down and measured instead
of implicit.

**Regression test.** Targeted corruption must collapse recall and control corruption must not, and the
rule must be recorded with the reason it exists.

---

## What these have in common

Three of the four produced no symptom at all. They were found by building something that used the
component, not by monitoring it: the release gate found the scoring defect, the fairness confirmation
found the withholding defect, the daily report found the matcher blind spot. Only the first was found
by a review.

The pattern in the causes is narrower than it looks. Every one of them is a component that was
correct in the situation it was tested in and wrong in the situation it was used in. A solver correct
at balanced prevalence, a mapping correct on a batch, a suppression correct at render time, a matcher
correct on duplicates that share contact details.

The tests added for each are therefore all of the same kind: they assert the property in the
situation of *use*, not of test.
