BEGIN;

CREATE TABLE IF NOT EXISTS analytics.dim_date (
    date_key integer PRIMARY KEY,
    calendar_date date NOT NULL UNIQUE,
    month_start date NOT NULL,
    month_label text NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_model (
    model_key bigserial PRIMARY KEY,
    model_version text NOT NULL UNIQUE,
    model_type text NOT NULL,
    approval_state text NOT NULL,
    artifact_hash text NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_policy (
    policy_key bigserial PRIMARY KEY,
    policy_version text NOT NULL UNIQUE,
    review_capacity double precision NOT NULL,
    score_cut double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_segment (
    segment_key bigserial PRIMARY KEY,
    segment_type text NOT NULL,
    segment_value text NOT NULL,
    UNIQUE (segment_type, segment_value)
);

CREATE TABLE IF NOT EXISTS analytics.dim_channel (
    channel_key bigserial PRIMARY KEY,
    channel_code text NOT NULL UNIQUE,
    channel_label text NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_action (
    action_key smallserial PRIMARY KEY,
    action_code text NOT NULL UNIQUE CHECK (
        action_code IN ('clear', 'manual_review', 'governance_referral')
    ),
    action_label text NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.fact_daily_strategy (
    date_key integer NOT NULL REFERENCES analytics.dim_date(date_key),
    model_key bigint NOT NULL REFERENCES analytics.dim_model(model_key),
    policy_key bigint NOT NULL REFERENCES analytics.dim_policy(policy_key),
    segment_key bigint NOT NULL REFERENCES analytics.dim_segment(segment_key),
    channel_key bigint NOT NULL REFERENCES analytics.dim_channel(channel_key),
    action_key smallint NOT NULL REFERENCES analytics.dim_action(action_key),
    application_count bigint NOT NULL CHECK (application_count >= 0),
    fraud_count bigint NOT NULL CHECK (fraud_count >= 0),
    fraud_caught bigint NOT NULL CHECK (fraud_caught >= 0),
    good_customer_reviews bigint NOT NULL CHECK (good_customer_reviews >= 0),
    expected_utility numeric(18, 2),
    PRIMARY KEY (date_key, model_key, policy_key, segment_key, channel_key, action_key)
);

CREATE OR REPLACE VIEW analytics.v_model_registry AS
SELECT
    model_version,
    dataset_version,
    approval_state,
    artifact_hash,
    code_sha,
    created_at,
    promoted_at
FROM scoring.model_versions;

CREATE OR REPLACE VIEW analytics.v_review_queue AS
SELECT
    q.scenario_run_id,
    q.queue_rank,
    q.application_id,
    q.action,
    q.reason_codes,
    s.fraud_probability,
    s.risk_band,
    a.period,
    a.channel,
    a.evidence_source
FROM strategy.queue_assignments q
JOIN strategy.scenario_runs r USING (scenario_run_id)
JOIN scoring.application_scores s
  ON s.application_id = q.application_id AND s.model_version = r.model_version
JOIN core.applications a ON a.application_id = q.application_id;

COMMIT;
