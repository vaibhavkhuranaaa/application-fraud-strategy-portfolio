import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from build_analytics_extract import build  # noqa: E402

EVIDENCE_DIR = Path("evaluation")

# Fields that would turn the aggregate extract into an application-level release.
FORBIDDEN_COLUMNS = {"application_id", "fraud_bool", "customer_age", "entity_id", "ring_id"}


@pytest.fixture(scope="module")
def extract(tmp_path_factory) -> Path:
    if not (EVIDENCE_DIR / "model_evaluation.json").is_file():
        pytest.skip("evaluation evidence is not present in this checkout")
    output = tmp_path_factory.mktemp("powerbi")
    build(EVIDENCE_DIR, output)
    return output


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_extract_contains_every_expected_table(extract: Path) -> None:
    expected = {
        "dim_comparator",
        "dim_evidence_source",
        "fact_model_metric",
        "fact_capacity",
        "fact_promotion_gate",
        "fact_strategy_policy",
        "fact_fairness_group",
        "fact_drift",
        "fact_variant_stress",
        "fact_linking_run",
        "fact_data_quality",
        "fact_run_context",
    }
    assert {path.stem for path in extract.glob("*.csv")} == expected


def test_extract_holds_no_application_level_field(extract: Path) -> None:
    for path in extract.glob("*.csv"):
        with path.open(encoding="utf-8") as handle:
            header = set(next(csv.reader(handle)))
        assert not header & FORBIDDEN_COLUMNS, f"{path.name} exposes {header & FORBIDDEN_COLUMNS}"


def test_run_context_carries_the_refusal_and_its_reasons(extract: Path) -> None:
    context = {row["context_key"]: row["context_value"] for row in _rows(extract / "fact_run_context.csv")}
    assert context["strategy_recommendation"] == "no robust recommendation"
    assert context["champion"] == "Incumbent score proxy"
    assert context["challenger_approval_state"] == "rejected"
    assert any(key.startswith("refusal_reason_") for key in context)
    assert "assumption" in context["assumption_notice"].lower()


def test_gate_table_records_the_failures_that_blocked_promotion(extract: Path) -> None:
    rows = _rows(extract / "fact_promotion_gate.csv")
    model_gates = [row for row in rows if row["gate_family"] == "Model promotion"]
    linking_gates = [row for row in rows if row["gate_family"] == "Identity linking"]
    failed = [row["gate_key"] for row in model_gates if row["gate_passed"] == "False"]
    assert len(model_gates) == 11
    assert len(linking_gates) == 5
    assert "calibration_intercept_abs_at_most_0_10" in failed
    assert all(row["gate_passed"] == "True" for row in linking_gates)
    assert all(row["gate_name"] and "_" not in row["gate_name"] for row in model_gates)


def test_withheld_fairness_groups_keep_their_flag_and_blank_metrics(extract: Path) -> None:
    rows = _rows(extract / "fact_fairness_group.csv")
    withheld = [row for row in rows if row["is_publishable"] == "False"]
    assert withheld, "the record contains groups below the publication threshold"
    for row in withheld:
        assert int(row["positive_labels"]) < 200
        # Blank, not zero: a withheld estimate must never read as a measured zero.
        assert row["catch_rate"] == ""


def test_manifest_records_evidence_identity_and_boundary(extract: Path) -> None:
    manifest = json.loads((extract / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_version"].startswith("baf-")
    assert manifest["evidence_revision"]
    assert all(manifest["evidence_ids"])
    assert "no fixture entity or ring truth" in manifest["boundary"].lower()
    assert manifest["row_counts"]["fact_strategy_policy"] == 8
