"""Read-only evidence access for the M4 workbench.

The workbench never recomputes, tunes, or writes M3 evidence. It reads the verified
evidence files; when one is absent it reports the exact path and the documented
recovery command rather than substituting a fabricated value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import DEFAULT_ARTIFACT_DIR, DEFAULT_CURATED_DIR, DEFAULT_EVIDENCE_DIR

TEST_MONTH = 7

SOURCE_LABELS = {
    "baf_base": "BAF Base",
    "baf_variant_i": "BAF Variant I",
    "baf_variant_ii": "BAF Variant II",
    "baf_variant_iii": "BAF Variant III",
    "baf_variant_iv": "BAF Variant IV",
    "baf_variant_v": "BAF Variant V",
    "synthetic_link_fixture": "Synthetic linking fixture",
}

COMPARATOR_LABELS = {
    "prevalence": "Prevalence baseline",
    "incumbent_proxy": "Incumbent score proxy",
    "regularized_logistic": "Regularized logistic",
    "catboost_internal": "CatBoost internal",
    "catboost_hybrid": "CatBoost hybrid",
}

# Phrased as requirements rather than sentences, so the same label reads correctly in
# a pass/fail table and inside a recorded "gates failed: …" statement.
GATE_LABELS = {
    "pr_auc_lift_ci_lower_above_zero": "ranking-lift confidence interval above zero",
    "catch_rate_improves_at_three_capacities": "catch-rate improvement at three of four review capacities",
    "no_capacity_regression_over_two_points": "no capacity regression over two percentage points",
    "positive_brier_skill": "positive probability skill versus the prevalence baseline",
    "ece_at_most_0_02": "average predicted-versus-observed gap at most 0.02",
    "calibration_slope_0_8_to_1_2": "calibration slope between 0.8 and 1.2",
    "calibration_intercept_abs_at_most_0_10": "calibration intercept within 0.10 of zero",
    "economic_grid_positive_at_least_80_percent": "positive scenario value across at least 80% of assumptions",
    "no_automatic_promotion_psi_blocks": "no distribution shift at the automatic-promotion block level",
    "fairness_governance_review_resolved": "segment review resolved or explicitly accepted",
    "warnings_visible": "every warning visible to the reader",
}

RECOVERY_COMMANDS = {
    "model": "PYTHONPATH=src uv run python -m fraud_strategy.cli train --trials 6 --bootstrap-resamples 1000",
    "linking": (
        "FRAUD_LINK_HMAC_KEY='<local key of at least 16 bytes>' "
        "PYTHONPATH=src uv run python -m fraud_strategy.cli link-evaluate"
    ),
    "curation": "PYTHONPATH=src uv run python -m fraud_strategy.cli curate",
}


@dataclass(frozen=True)
class EvidenceGap:
    """A named evidence artifact the workbench needs but cannot find."""

    label: str
    path: str
    recovery: str


@dataclass(frozen=True)
class EvidencePaths:
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR
    curated_dir: Path = DEFAULT_CURATED_DIR

    @property
    def model(self) -> Path:
        return self.evidence_dir / "model_evaluation.json"

    @property
    def linking(self) -> Path:
        return self.evidence_dir / "linking_evaluation.json"

    @property
    def curation(self) -> Path:
        return self.evidence_dir / "data_curation.json"

    @property
    def champion_manifest(self) -> Path:
        return self.artifact_dir / "models" / "model_manifest.json"

    @property
    def candidate_manifest(self) -> Path:
        return self.artifact_dir / "models" / "candidate_model_manifest.json"

    @property
    def predictions(self) -> Path:
        return self.artifact_dir / "predictions" / "month_7_scores.parquet"

    @property
    def curated_base(self) -> Path:
        return self.curated_dir / "base.parquet"

    @property
    def candidate_model(self) -> Path:
        return self.artifact_dir / "models" / "catboost_hybrid.cbm"


@dataclass(frozen=True)
class EvidenceBundle:
    """Every verified record the workbench is allowed to render."""

    paths: EvidencePaths
    model: dict[str, Any] = field(default_factory=dict)
    linking: dict[str, Any] = field(default_factory=dict)
    curation: dict[str, Any] = field(default_factory=dict)
    champion_manifest: dict[str, Any] = field(default_factory=dict)
    candidate_manifest: dict[str, Any] = field(default_factory=dict)
    gaps: tuple[EvidenceGap, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.gaps

    @property
    def recommendation(self) -> str:
        return self.model.get("strategy_frontier", {}).get("recommendation", "unavailable")

    @property
    def refused(self) -> bool:
        return self.recommendation == "no robust recommendation"

    @property
    def refusal_reasons(self) -> list[str]:
        return [
            humanize_reason(reason)
            for reason in self.model.get("strategy_frontier", {}).get("refusal_reasons", [])
        ]

    @property
    def champion(self) -> str:
        return self.model.get("champion", "unavailable")

    @property
    def challenger(self) -> str:
        return self.model.get("selected_challenger", "unavailable")

    @property
    def promotion_gates(self) -> dict[str, bool]:
        return dict(self.model.get("promotion_gates", {}))

    @property
    def failed_gates(self) -> list[str]:
        return sorted(name for name, passed in self.promotion_gates.items() if not passed)

    @property
    def evidence_sha(self) -> str:
        return str(self.model.get("evaluation_source_sha", ""))

    @property
    def dataset_version(self) -> str:
        return str(self.model.get("dataset_version") or self.curation.get("dataset_version", "unknown"))

    @property
    def test_rows(self) -> int:
        return int(self.model.get("rows", {}).get("test", 0))

    @property
    def test_prevalence(self) -> float:
        return float(self.model.get("month_7_metrics", {}).get("incumbent_proxy", {}).get("prevalence", 0.0))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(paths: EvidencePaths | None = None) -> EvidenceBundle:
    """Load every evidence record, recording a gap for each artifact that is absent."""
    paths = paths or EvidencePaths()
    documents: dict[str, dict[str, Any]] = {}
    gaps: list[EvidenceGap] = []
    required = (
        ("model", "Model and strategy evidence", paths.model, RECOVERY_COMMANDS["model"]),
        ("linking", "Identity-linking evidence", paths.linking, RECOVERY_COMMANDS["linking"]),
        ("curation", "Data curation evidence", paths.curation, RECOVERY_COMMANDS["curation"]),
        ("champion_manifest", "Champion model manifest", paths.champion_manifest, RECOVERY_COMMANDS["model"]),
        (
            "candidate_manifest",
            "Challenger model manifest",
            paths.candidate_manifest,
            RECOVERY_COMMANDS["model"],
        ),
    )
    for key, label, path, recovery in required:
        if path.is_file():
            documents[key] = read_json(path)
        else:
            documents[key] = {}
            gaps.append(EvidenceGap(label=label, path=path.as_posix(), recovery=recovery))
    return EvidenceBundle(paths=paths, gaps=tuple(gaps), **documents)


@lru_cache(maxsize=1)
def _scores(path_key: str) -> pd.DataFrame:
    return pd.read_parquet(path_key)


@lru_cache(maxsize=1)
def _month_seven(path_key: str) -> pd.DataFrame:
    frame = pd.read_parquet(path_key, filters=[("month", "==", TEST_MONTH)])
    return frame.reset_index(drop=True)


def analysis_frame(paths: EvidencePaths | None = None) -> pd.DataFrame:
    """Month-7 curated applications joined to their recorded comparator scores.

    Row order follows the scores artifact so every derived policy matches the M3
    evidence exactly.
    """
    paths = paths or EvidencePaths()
    for label, path in (
        ("Month-7 comparator scores", paths.predictions),
        ("Curated BAF Base artifact", paths.curated_base),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path.as_posix()}")
    scores = _scores(paths.predictions.as_posix())
    features = _month_seven(paths.curated_base.as_posix())
    merged = scores.merge(
        features.drop(columns=["fraud_bool", "evidence_source"]),
        on="application_id",
        how="inner",
        validate="one_to_one",
    )
    if len(merged) != len(scores):
        raise ValueError(
            f"score/feature join lost rows: {len(scores)} scored, {len(merged)} matched to curated features"
        )
    return merged


def source_label(value: str) -> str:
    return SOURCE_LABELS.get(value, value)


def comparator_label(value: str) -> str:
    return COMPARATOR_LABELS.get(value, value)


def humanize_reason(reason: str) -> str:
    """Replace recorded gate identifiers with their plain-language names.

    The stored evidence text is authoritative and unchanged on disk; this only makes
    the same statement readable, as the design contract requires.
    """
    for name in sorted(GATE_LABELS, key=len, reverse=True):
        if name in reason:
            reason = reason.replace(name, GATE_LABELS[name])
    return reason
