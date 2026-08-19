# Reject inference: the position, and what it will cost to keep it

Status: `documented position recorded 2026-08-10; no build, and none currently needed`
Evidence: this document. There is no measurement to make yet, and that is the point.

## 1. The position today

Reject inference is the problem that once review leads to declines, the labels you observe are
conditional on the policy that produced them. You only learn outcomes for applications you approved,
so the training data becomes a record of what the current policy let through rather than of fraud.

**This program does not have that problem yet, and the reason is structural rather than lucky.** The
product is non-binding. It simulates three actions, `clear`, `manual_review` and `governance_referral`,
and none of them declines anyone. There is no automatic decline in the code, none in the database
schema's `action` constraint, and the strategy engine returns a refusal rather than a policy. Nothing
this program does removes an application from the population whose outcome is later observed.

So the labels are not conditional on this model's decisions. That is a clean position and it is worth
stating plainly rather than carrying as a pending debt. It is also the single largest thing that
changes the day the product becomes binding.

## 2. What changes the day it binds

The failure is slow, and it is easy to mistake for success while it happens.

1. The policy starts declining the applications it is most confident about.
2. Those applications never receive an outcome, so they leave the training data.
3. The next model is fitted on what survived the policy. The patterns the policy already blocks are
   now rare in the data, so the model learns them weakly, or stops learning them at all.
4. Model performance metrics look fine, because they are measured on the same censored population.
5. Somebody observes that the model does not seem to rely on those old rules and proposes retiring
   them. The measurement supports that, because the measurement is censored the same way.
6. The rules are retired, the blocked fraud returns, and losses appear one to two quarters later,
   which is long enough that the cause is no longer obvious.

That sequence needs no incompetence at any step. Every individual decision reads as evidence-led.

## 3. What has to exist before go-live, not after

The counterfactual cannot be recovered once it is lost. If an application was declined and never
funded, no amount of later analysis reveals whether it would have defaulted. So the mitigation has to
be in place before the first binding decision, not designed in response to the first surprise.

**A random-approval control group.** A small, randomly selected share of applications that the policy
would decline are approved anyway, and their outcomes observed. This is the only mechanism that
produces genuinely unconditional labels. It has a real and calculable cost, which is the fraud losses
on the control group, and that cost is the price of knowing whether the policy still works. It has to
be sized deliberately: large enough that the fraud rate in the control group is measurable against the
latency in `docs/label-latency.md`, small enough that the losses are acceptable. Both of those pull
against each other and the sizing is a governance decision rather than a technical one.

**Swap-set analysis at every policy change.** When a policy changes, record which applications the old
policy and the new policy disagree on, and track those separately. It does not recover the
counterfactual for declines, but it makes the population change visible at the moment it happens
rather than a year later.

**Shadow scoring of the declined population.** Score the declines with the candidate model and record
the distribution, even though outcomes are unavailable. It cannot measure accuracy, but a shift in the
declined population's score distribution is an early warning that the two models disagree about a
growing group.

## 4. The upstream problem this program cannot solve

BAF is derived from a real-world dataset through a selection process its publisher does not document.
Whatever policy governed the original population, its effects are already in these labels and cannot
be removed or measured from here. Every result in this program is therefore conditional on an unknown
prior policy, and no analysis available in this repository can quantify by how much.

That limitation is inherited, not created, and it is stated here so that nothing in this program is
read as unconditional.

## 5. Interaction with label latency

Reject inference and label latency compound in a way neither does alone. Latency means a period's
labels are incomplete for 30 to 90 days and longer. Reject inference means some labels never arrive at
all, because the application was declined. A monitoring process that cannot tell those two apart will
read a decline-driven gap as an immaturity gap and wait for labels that are never coming.

The practical consequence: any maturity correction of the kind in `docs/label-latency.md` must be
computed on the approved population only. Applying a maturity curve to a population that includes
declines inflates the correction by the decline rate, and the error grows with the policy's strength.

## 6. Why there is no code in this milestone item

The acceptance criterion for this item asks for a documented position, and this is it. Building
reject-inference machinery now would mean building a correction for a bias that does not exist in a
non-binding product, validating it against synthetic data that carries an undocumented selection
process of its own, and carrying it as tested code that has never met the condition it was written
for. The honest deliverable is the design above and the requirement that it precedes any binding
deployment.
