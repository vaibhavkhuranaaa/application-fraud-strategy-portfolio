"""Versioned application-domain interfaces for M3 and later API layers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceSource = Literal[
    "baf_base",
    "baf_variant_i",
    "baf_variant_ii",
    "baf_variant_iii",
    "baf_variant_iv",
    "baf_variant_v",
    "synthetic_link_fixture",
]


class Action(StrEnum):
    CLEAR = "clear"
    MANUAL_REVIEW = "manual_review"
    GOVERNANCE_REFERRAL = "governance_referral"


class ApprovalState(StrEnum):
    CANDIDATE = "candidate"
    CHAMPION = "champion"
    RETAINED_BASELINE = "retained_baseline"
    REJECTED = "rejected"


class ApplicationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    application_id: str
    period: int = Field(ge=0, le=7)
    channel: str
    approved_predecision_features: dict[str, Any]
    evidence_source: EvidenceSource


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: str
    model_version: str
    calibrated_fraud_probability: float = Field(ge=0, le=1)
    risk_band: Literal["low", "medium", "high", "critical"]
    reason_codes: list[str]
    scored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_hash: str
    evidence_source: EvidenceSource


class LinkFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: str
    cluster_id: str
    match_strength: float = Field(ge=0, le=1)
    signal_types: list[str]
    cluster_risk: float = Field(ge=0, le=1)
    evidence_source: Literal["synthetic_link_fixture"] = "synthetic_link_fixture"
    evidence_warning: str = "Synthetic fixture evidence; not a recovered BAF or customer identity."


class StrategyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str
    policy_version: str
    score_cut: float = Field(ge=0, le=1)
    review_capacity: float = Field(gt=0, le=1)
    rule_toggles: dict[str, bool] = Field(default_factory=dict)
    fraud_exposure: float = Field(ge=0)
    review_cost: float = Field(ge=0)
    friction_cost: float = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=128)


class StrategyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str
    policy_version: str
    catch_rate: float = Field(ge=0, le=1)
    false_positive_rate: float = Field(ge=0, le=1)
    review_rate: float = Field(ge=0, le=1)
    queue_size: int = Field(ge=0)
    overflow: int = Field(ge=0)
    expected_utility_interval: tuple[float, float]
    segment_impacts: dict[str, Any]
    frontier_position: int | None
    recommendation: str
    refusal_reasons: list[str]
    evidence_source: EvidenceSource

    @model_validator(mode="after")
    def recommendation_is_bounded(self) -> StrategyResult:
        if self.overflow and not self.refusal_reasons:
            raise ValueError("capacity overflow requires a refusal reason")
        return self


class BehaviourFingerprint(BaseModel):
    """A hash of what a model does, not of the file it is stored in."""

    model_config = ConfigDict(extra="forbid")

    digest: str
    reference_period: int
    reference_rows: int
    reference_seed: int
    decimals: int
    method: str


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str
    source_checksum: str
    dataset_version: str
    feature_contract: list[str]
    split_periods: dict[str, list[int]]
    parameters: dict[str, Any]
    calibrator: Literal["sigmoid", "isotonic"]
    metrics: dict[str, Any]
    artifact_hash: str
    # The artifact hash identifies a file. CatBoost writes a finish time and a GUID into
    # the model, so a functionally identical model hashes differently after a retrain, and
    # a rollback decision cannot be made on it. The fingerprint identifies behaviour
    # instead: it hashes the model's own predictions over a fixed reference sample, so two
    # artifacts that score identically carry the same fingerprint whatever their bytes say.
    behaviour_fingerprint: BehaviourFingerprint | None = None
    code_sha: str
    approval_state: ApprovalState
    limitations: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
