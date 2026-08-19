"""Immutable M3 data and feature contracts."""

from __future__ import annotations

from pathlib import Path

DATASET_VERSION = "baf-2026-08-05-fb8d6d8b96f9"
BASE_SOURCE = "baf_base"

SOURCE_FILES = {
    "Base.csv": {
        "sha256": "7bf10a37ce07e72e14c1b09e5efee3d27261baff4facc7da767b0474dcf9b809",
        "rows": 1_000_000,
        "columns": 32,
        "evidence_source": BASE_SOURCE,
    },
    "Variant I.csv": {
        "sha256": "48c637a255d1fa4515da4286ccb99251412a6d905937ec7c108838ddfc1674bd",
        "rows": 1_000_000,
        "columns": 32,
        "evidence_source": "baf_variant_i",
    },
    "Variant II.csv": {
        "sha256": "60bcd971cf28779abb183c3286990cff9a87275bd8b83d9f6054a396c95cc736",
        "rows": 1_000_000,
        "columns": 32,
        "evidence_source": "baf_variant_ii",
    },
    "Variant III.csv": {
        "sha256": "64693e549cff7ef802cf043fc7c937839e5929966e33a0852953b3f4c4321339",
        "rows": 1_000_000,
        "columns": 34,
        "evidence_source": "baf_variant_iii",
    },
    "Variant IV.csv": {
        "sha256": "c6cddebbad34fa262a278deeb7985e7b669a64308d26e480d8eb85bfd08dac75",
        "rows": 1_000_000,
        "columns": 32,
        "evidence_source": "baf_variant_iv",
    },
    "Variant V.csv": {
        "sha256": "470899bbef97c32a100528d63e863e1b1036df9501df6ef8140e7ec13b7365b4",
        "rows": 1_000_000,
        "columns": 34,
        "evidence_source": "baf_variant_v",
    },
}

BASE_COLUMNS = [
    "fraud_bool",
    "income",
    "name_email_similarity",
    "prev_address_months_count",
    "current_address_months_count",
    "customer_age",
    "days_since_request",
    "intended_balcon_amount",
    "payment_type",
    "zip_count_4w",
    "velocity_6h",
    "velocity_24h",
    "velocity_4w",
    "bank_branch_count_8w",
    "date_of_birth_distinct_emails_4w",
    "employment_status",
    "credit_risk_score",
    "email_is_free",
    "housing_status",
    "phone_home_valid",
    "phone_mobile_valid",
    "bank_months_count",
    "has_other_cards",
    "proposed_credit_limit",
    "foreign_request",
    "source",
    "session_length_in_minutes",
    "device_os",
    "keep_alive_session",
    "device_distinct_emails_8w",
    "device_fraud_count",
    "month",
]

CATEGORICAL_FEATURES = ["payment_type", "employment_status", "housing_status", "source", "device_os"]
AUDIT_ONLY_FEATURES = ["customer_age", "month"]
EXCLUDED_FEATURES = ["fraud_bool", "customer_age", "month", "device_fraud_count", "days_since_request"]
INCUMBENT_FEATURE = "credit_risk_score"
SENTINEL_MINUS_ONE = [
    "prev_address_months_count",
    "current_address_months_count",
    "bank_months_count",
    "session_length_in_minutes",
    "device_distinct_emails_8w",
]
NEGATIVE_IS_MISSING = ["intended_balcon_amount"]
MISSING_INDICATORS = [f"{column}__missing" for column in SENTINEL_MINUS_ONE + NEGATIVE_IS_MISSING]
INTERNAL_FEATURES = [
    column for column in BASE_COLUMNS if column not in EXCLUDED_FEATURES and column != INCUMBENT_FEATURE
] + MISSING_INDICATORS
HYBRID_FEATURES = [*INTERNAL_FEATURES, INCUMBENT_FEATURE]

BINARY_COLUMNS = [
    "fraud_bool",
    "email_is_free",
    "phone_home_valid",
    "phone_mobile_valid",
    "has_other_cards",
    "foreign_request",
    "keep_alive_session",
    "device_fraud_count",
]

DEFAULT_RAW_DIR = Path("data/quarantine")
DEFAULT_CURATED_DIR = Path("data/curated")
DEFAULT_ARTIFACT_DIR = Path("artifacts")
DEFAULT_EVIDENCE_DIR = Path("evaluation")

SEED = 20260805
CAPACITIES = (0.01, 0.03, 0.05, 0.10)
