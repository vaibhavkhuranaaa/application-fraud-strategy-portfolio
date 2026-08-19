/* -----------------------------------------------------------------------------
   Incumbent score to calibrated probability.

   Translation of src/fraud_strategy/calibration.py. Not executed: this project
   has no SAS licence, and no output from this file is claimed anywhere.

   The point of this mapping is that it standardises against FIXED reference
   statistics captured on the calibration period, never against whatever batch
   arrives. Standardising against the incoming batch was a real defect in this
   program, found at M5: the champion could not score one application in
   isolation, because a single row has no distribution to standardise against.
   The fix was to persist the reference statistics in the model manifest, and
   this translation carries the same discipline.

   Inputs
     WORK.APPLICATIONS      one row per application, with CREDIT_RISK_SCORE
     &REF_MEDIAN            reference median from the model manifest
     &REF_SCALE             reference scale from the model manifest
     &CAL_SLOPE &CAL_INTERCEPT   sigmoid calibration fitted on the calibration period
     &LOGIT_SHIFT           prior shift between calibration and scoring period

   Output
     WORK.SCORED            adds FRAUD_PROBABILITY and RISK_BAND
   ----------------------------------------------------------------------------- */

%let REF_MEDIAN   = 139.0;        /* artifacts/models/model_manifest.json */
%let REF_SCALE    = 62.3379355639;
%let LOGIT_SHIFT  = 0.0;          /* carry_forward selected by backtest; shift is zero */

/* Risk band edges are quantiles of the CALIBRATION period, fixed once and reused.
   Recomputing them per batch would mean "critical" meant a different thing every
   period, which is useless to an investigator. */
%let BAND_CRITICAL = 0.0484955562;
%let BAND_HIGH     = 0.0322993396;
%let BAND_MEDIUM   = 0.0188695590;

data work.scored;
    set work.applications;

    /* 1. Standardise against the fixed reference, not against this batch. */
    standardised = (credit_risk_score - &REF_MEDIAN) / &REF_SCALE;

    /* 2. Monotone map to (0,1). Rank order is preserved, so catch rate at a
          fixed capacity is unaffected by every step in this file. */
    raw_probability = 1 / (1 + exp(-standardised));

    /* 3. Sigmoid calibration fitted on the calibration period. */
    calibrated_logit = &CAL_INTERCEPT + &CAL_SLOPE * log(raw_probability / (1 - raw_probability));

    /* 4. Prior shift between the calibration period and the scoring period.
          This is a property of the schedule, not of the model. */
    shifted_logit = calibrated_logit + &LOGIT_SHIFT;

    fraud_probability = 1 / (1 + exp(-shifted_logit));

    length risk_band $8;
    if      fraud_probability >= &BAND_CRITICAL then risk_band = 'critical';
    else if fraud_probability >= &BAND_HIGH     then risk_band = 'high';
    else if fraud_probability >= &BAND_MEDIUM   then risk_band = 'medium';
    else                                             risk_band = 'low';

    drop standardised raw_probability calibrated_logit shifted_logit;
run;
