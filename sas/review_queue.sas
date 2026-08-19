/* -----------------------------------------------------------------------------
   Capacity-bounded review queue.

   Translation of rank_review_queue and policy_metrics in
   src/fraud_strategy/strategy.py. Not executed: no SAS licence here, and no
   output from this file is claimed.

   Boundaries, identical to the Python program:
     - one population-wide ranking and one capacity cut, never per group
     - three simulated actions, none of which declines an applicant
     - no group attribute enters the ranking or the cut

   Inputs
     WORK.SCORED    output of score_to_probability.sas
     &CAPACITY      review capacity as a share of the population, e.g. 0.05
   ----------------------------------------------------------------------------- */

%let CAPACITY = 0.05;

proc sql noprint;
    select count(*), floor(count(*) * &CAPACITY)
      into :population trimmed, :headcount trimmed
      from work.scored;
quit;

/* A stable sort matters. Ties broken by an arbitrary physical row order make the
   queue non-reproducible between runs, and a queue that changes when nothing
   changed cannot be audited. APPLICATION_ID is the deterministic tie-break the
   strategy document recommends. */
proc sort data=work.scored out=work.ranked;
    by descending fraud_probability application_id;
run;

data work.queue;
    set work.ranked;
    queue_rank = _n_;

    length action $20;
    if queue_rank <= &headcount then action = 'manual_review';
    else                              action = 'clear';
run;

/* -----------------------------------------------------------------------------
   The tie problem, made explicit rather than hidden.

   Cutting on a THRESHOLD rather than on a rank cannot land on an exact
   headcount when the score has ties, because every application sitting at the
   cutting value has to be treated alike. The incumbent proxy is a
   low-cardinality integer score, so its tied block is large: measured across
   eight periods its queue exceeds staffed capacity by 63 to 168 cases, 1.06% to
   2.45%. The challenger overshoots by exactly one.

   The rank-based cut above does not have that problem, which is precisely why
   it is written this way. This block quantifies what a threshold cut would have
   cost, so the choice is visible instead of implicit.
   ----------------------------------------------------------------------------- */
proc sql noprint;
    select min(fraud_probability) into :score_cut trimmed
      from work.queue where action = 'manual_review';

    select count(*) into :threshold_queue trimmed
      from work.scored where fraud_probability >= &score_cut;
quit;

data work.capacity_diagnostics;
    population       = &population;
    headcount        = &headcount;
    rank_cut_queue   = &headcount;
    threshold_queue  = &threshold_queue;
    overshoot        = &threshold_queue - &headcount;
    overshoot_rate   = overshoot / headcount;
    label overshoot = 'Reviews above staffed capacity if cutting on score rather than rank';
run;

/* Operating metrics. FRAUD_BOOL is the retrospective label a reviewer would not
   have had at the time; it is used to judge queue quality after the fact, never
   to build the queue. */
proc sql;
    create table work.queue_metrics as
    select  count(*)                                              as applications,
            sum(fraud_bool)                                       as fraud_attempts,
            sum(case when action ne 'clear' then 1 else 0 end)    as cases_worked,
            sum(case when action ne 'clear' then fraud_bool else 0 end) as fraud_caught,
            calculated fraud_caught / max(calculated fraud_attempts, 1) as catch_rate,
            calculated fraud_caught / max(calculated cases_worked, 1)   as reviewer_hit_rate
      from work.queue;
quit;

/* Reviewer hit rate is observable within days, because a review confirms fraud
   at review time. Catch rate shares that numerator but divides by ALL fraud in
   the period, including what slipped past review and surfaces through default 30
   to 90 days later. Read the first as current and the second as lagging.
   See docs/label-latency.md. */
