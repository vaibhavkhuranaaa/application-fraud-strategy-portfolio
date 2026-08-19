BEGIN;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS scoring;
CREATE SCHEMA IF NOT EXISTS linking;
CREATE SCHEMA IF NOT EXISTS strategy;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    script_sha256 text NOT NULL CHECK (length(script_sha256) = 64)
);

CREATE TABLE IF NOT EXISTS core.dataset_versions (
    dataset_version text PRIMARY KEY,
    source_name text NOT NULL,
    source_sha256 text NOT NULL CHECK (length(source_sha256) = 64),
    acquired_at date NOT NULL,
    row_count bigint NOT NULL CHECK (row_count > 0),
    evidence_source text NOT NULL,
    manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.applications (
    application_id text PRIMARY KEY CHECK (length(application_id) = 32),
    dataset_version text NOT NULL REFERENCES core.dataset_versions(dataset_version),
    period smallint NOT NULL CHECK (period BETWEEN 0 AND 7),
    channel text NOT NULL,
    evidence_source text NOT NULL CHECK (
        evidence_source IN (
            'baf_base', 'baf_variant_i', 'baf_variant_ii', 'baf_variant_iii',
            'baf_variant_iv', 'baf_variant_v', 'synthetic_link_fixture'
        )
    ),
    approved_features jsonb NOT NULL,
    target_fraud boolean,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS applications_period_idx ON core.applications (dataset_version, period);
CREATE INDEX IF NOT EXISTS applications_source_idx ON core.applications (evidence_source);

CREATE TABLE IF NOT EXISTS scoring.model_versions (
    model_version text PRIMARY KEY,
    dataset_version text NOT NULL REFERENCES core.dataset_versions(dataset_version),
    artifact_hash text NOT NULL CHECK (length(artifact_hash) = 64),
    code_sha text NOT NULL,
    approval_state text NOT NULL CHECK (
        approval_state IN ('candidate', 'champion', 'retained_baseline', 'rejected')
    ),
    manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    promoted_at timestamptz
);

CREATE TABLE IF NOT EXISTS scoring.application_scores (
    application_id text NOT NULL REFERENCES core.applications(application_id),
    model_version text NOT NULL REFERENCES scoring.model_versions(model_version),
    fraud_probability double precision NOT NULL CHECK (fraud_probability BETWEEN 0 AND 1),
    risk_band text NOT NULL CHECK (risk_band IN ('low', 'medium', 'high', 'critical')),
    reason_codes jsonb NOT NULL,
    artifact_hash text NOT NULL CHECK (length(artifact_hash) = 64),
    scored_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (application_id, model_version)
);

CREATE TABLE IF NOT EXISTS linking.signal_tokens (
    application_id text NOT NULL,
    signal_type text NOT NULL CHECK (signal_type IN ('email', 'phone', 'device', 'address')),
    exact_token text NOT NULL,
    fuzzy_tokens jsonb NOT NULL,
    evidence_source text NOT NULL DEFAULT 'synthetic_link_fixture'
        CHECK (evidence_source = 'synthetic_link_fixture'),
    PRIMARY KEY (application_id, signal_type)
);

CREATE INDEX IF NOT EXISTS signal_tokens_block_idx ON linking.signal_tokens (signal_type, exact_token);

CREATE TABLE IF NOT EXISTS linking.candidate_pairs (
    left_application_id text NOT NULL,
    right_application_id text NOT NULL,
    pair_score double precision NOT NULL CHECK (pair_score BETWEEN 0 AND 1),
    match_evidence jsonb NOT NULL,
    accepted boolean NOT NULL,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (left_application_id, right_application_id),
    CHECK (left_application_id < right_application_id)
);

CREATE TABLE IF NOT EXISTS linking.clusters (
    cluster_id text NOT NULL,
    application_id text NOT NULL,
    match_strength double precision NOT NULL CHECK (match_strength BETWEEN 0 AND 1),
    cluster_risk double precision NOT NULL CHECK (cluster_risk BETWEEN 0 AND 1),
    signal_types jsonb NOT NULL,
    evidence_warning text NOT NULL,
    PRIMARY KEY (cluster_id, application_id)
);

CREATE TABLE IF NOT EXISTS linking.ring_flags (
    flag_id bigserial PRIMARY KEY,
    cluster_id text NOT NULL,
    rule_version text NOT NULL,
    supporting_tokens jsonb NOT NULL,
    risk_score double precision NOT NULL CHECK (risk_score BETWEEN 0 AND 1),
    evidence_source text NOT NULL DEFAULT 'synthetic_link_fixture'
        CHECK (evidence_source = 'synthetic_link_fixture'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy.policy_versions (
    policy_version text PRIMARY KEY,
    model_version text NOT NULL REFERENCES scoring.model_versions(model_version),
    score_cut double precision NOT NULL CHECK (score_cut BETWEEN 0 AND 1),
    review_capacity double precision NOT NULL CHECK (review_capacity > 0 AND review_capacity <= 1),
    rule_toggles jsonb NOT NULL,
    approval_state text NOT NULL DEFAULT 'candidate',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy.scenario_runs (
    scenario_run_id uuid PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    model_version text NOT NULL REFERENCES scoring.model_versions(model_version),
    policy_version text NOT NULL REFERENCES strategy.policy_versions(policy_version),
    assumptions jsonb NOT NULL,
    results jsonb NOT NULL,
    recommendation text NOT NULL,
    refusal_reasons jsonb NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy.queue_assignments (
    scenario_run_id uuid NOT NULL REFERENCES strategy.scenario_runs(scenario_run_id),
    application_id text NOT NULL REFERENCES core.applications(application_id),
    queue_rank integer NOT NULL CHECK (queue_rank > 0),
    action text NOT NULL CHECK (action IN ('clear', 'manual_review', 'governance_referral')),
    reason_codes jsonb NOT NULL,
    PRIMARY KEY (scenario_run_id, application_id),
    UNIQUE (scenario_run_id, queue_rank)
);

CREATE TABLE IF NOT EXISTS governance.data_quality_results (
    result_id bigserial PRIMARY KEY,
    dataset_version text NOT NULL,
    check_name text NOT NULL,
    status text NOT NULL CHECK (status IN ('pass', 'warn', 'fail')),
    observed_value jsonb NOT NULL,
    artifact_hash text,
    checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.drift_results (
    result_id bigserial PRIMARY KEY,
    model_version text NOT NULL,
    period text NOT NULL,
    feature_name text NOT NULL,
    psi double precision NOT NULL CHECK (psi >= 0),
    status text NOT NULL CHECK (status IN ('pass', 'warn', 'block')),
    measured_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.approvals (
    approval_id bigserial PRIMARY KEY,
    object_type text NOT NULL,
    object_version text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approved', 'rejected', 'revoked')),
    actor_id text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.audit_events (
    event_id uuid PRIMARY KEY,
    correlation_id text NOT NULL,
    actor_id text NOT NULL,
    actor_role text NOT NULL,
    action text NOT NULL,
    object_type text NOT NULL,
    object_version text NOT NULL,
    outcome text NOT NULL,
    details jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.artifacts (
    artifact_hash text PRIMARY KEY CHECK (length(artifact_hash) = 64),
    artifact_type text NOT NULL,
    uri text NOT NULL,
    git_sha text NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
