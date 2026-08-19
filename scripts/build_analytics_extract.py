"""Build the governed analytics extract that feeds the Power BI report.

The extract is a small star schema derived only from committed aggregate evidence.
It contains no application-level record, no raw BAF data, and no fixture truth. The
generated CSVs stay out of version control and can be rebuilt before opening the model.

    PYTHONPATH=src uv run python scripts/build_analytics_extract.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.analysis.evidence import GATE_LABELS  # noqa: E402

EVIDENCE_DIR = Path("evaluation")
OUTPUT_DIR = Path("powerbi/data")

COMPARATOR_LABELS = {
    "prevalence": "Prevalence baseline",
    "incumbent_proxy": "Incumbent score proxy",
    "regularized_logistic": "Regularized logistic",
    "catboost_internal": "CatBoost internal",
    "catboost_hybrid": "CatBoost hybrid",
}

COMPARATOR_KIND = {
    "prevalence": "Baseline",
    "incumbent_proxy": "Incumbent",
    "regularized_logistic": "Internal comparator",
    "catboost_internal": "Internal challenger",
    "catboost_hybrid": "Hybrid challenger",
}


SOURCE_LABELS = {
    "baf_base": "BAF Base",
    "baf_variant_i": "BAF Variant I",
    "baf_variant_ii": "BAF Variant II",
    "baf_variant_iii": "BAF Variant III",
    "baf_variant_iv": "BAF Variant IV",
    "baf_variant_v": "BAF Variant V",
    "synthetic_link_fixture": "Synthetic linking fixture",
}

SEGMENT_LABELS = {
    "customer_age": "Customer age band",
    "income": "Income band",
    "source": "Application channel",
    "housing_status": "Housing status",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_table(directory: Path, name: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    path = directory / f"{name}.csv"
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def dim_comparator(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = []
    for name in model.get("month_7_metrics", {}):
        rows.append(
            [
                name,
                COMPARATOR_LABELS.get(name, name),
                COMPARATOR_KIND.get(name, "Comparator"),
                name == model.get("champion"),
                name == model.get("selected_challenger"),
            ]
        )
    return ["comparator_key", "comparator_name", "comparator_kind", "is_champion", "is_challenger"], rows


def dim_evidence_source(
    model: dict[str, Any], linking: dict[str, Any]
) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = [
        [key, label, "Synthetic fixture" if key == "synthetic_link_fixture" else "BAF suite"]
        for key, label in SOURCE_LABELS.items()
    ]
    return ["evidence_source_key", "evidence_source_name", "evidence_source_family"], rows


def fact_model_metric(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = []
    for name, metrics in model.get("month_7_metrics", {}).items():
        for metric, value in metrics.items():
            rows.append([name, "baf_base", 7, metric, value])
    return ["comparator_key", "evidence_source_key", "month", "metric_name", "metric_value"], rows


def fact_capacity(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = []
    for name, levels in model.get("month_7_capacity", {}).items():
        for level, values in levels.items():
            rows.append(
                [
                    name,
                    float(level),
                    values.get("capacity_count"),
                    values.get("queue_size"),
                    values.get("governance_referrals"),
                    values.get("overflow"),
                    values.get("fraud_caught"),
                    values.get("catch_rate"),
                    (values.get("catch_rate_ci95") or [None, None])[0],
                    (values.get("catch_rate_ci95") or [None, None])[1],
                    values.get("false_positive_count"),
                    values.get("false_positive_rate"),
                    values.get("precision"),
                    values.get("review_rate"),
                ]
            )
    return (
        [
            "comparator_key",
            "review_capacity",
            "capacity_count",
            "queue_size",
            "governance_referrals",
            "overflow",
            "fraud_caught",
            "catch_rate",
            "catch_rate_ci_lower",
            "catch_rate_ci_upper",
            "false_positive_count",
            "false_positive_rate",
            "precision",
            "review_rate",
        ],
        rows,
    )


def fact_promotion_gate(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = [
        [name, GATE_LABELS.get(name, name.replace("_", " ")).capitalize(), bool(passed), "Model promotion"]
        for name, passed in model.get("promotion_gates", {}).items()
    ]
    rows.extend(
        [name, name.replace("_", " ").capitalize(), bool(passed), "Identity linking"]
        for name, passed in model.get("linking_gates", {}).items()
    )
    return ["gate_key", "gate_name", "gate_passed", "gate_family"], rows


def fact_strategy_policy(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    frontier = model.get("strategy_frontier", {})
    rows = []
    for policy in frontier.get("policies", []):
        grid = policy.get("economic_grid", {})
        rows.append(
            [
                policy["policy_id"],
                policy["capacity"],
                policy["rules_enabled"],
                policy["frontier"],
                policy["catch_rate"],
                policy["false_positive_rate"],
                policy["review_rate"],
                policy["queue_size"],
                policy["governance_referrals"],
                policy["overflow"],
                policy["fraud_caught"],
                policy["precision"],
                policy["utility"],
                grid.get("positive_share"),
                grid.get("incremental_utility_min"),
                grid.get("incremental_utility_median"),
                grid.get("incremental_utility_max"),
            ]
        )
    return (
        [
            "policy_id",
            "review_capacity",
            "rules_enabled",
            "on_frontier",
            "catch_rate",
            "false_positive_rate",
            "review_rate",
            "queue_size",
            "governance_referrals",
            "overflow",
            "fraud_caught",
            "precision",
            "scenario_utility",
            "assumption_grid_positive_share",
            "incremental_utility_min",
            "incremental_utility_median",
            "incremental_utility_max",
        ],
        rows,
    )


def fact_fairness_group(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = []
    for segment in model.get("fairness", {}).get("segments", []):
        for group in segment.get("groups", []):
            rows.append(
                [
                    segment["segment"],
                    SEGMENT_LABELS.get(segment["segment"], segment["segment"]),
                    group["group"],
                    group.get("rows"),
                    group.get("positive_labels"),
                    bool(group.get("publishable")),
                    group.get("tpr"),
                    group.get("fpr"),
                    group.get("precision"),
                    group.get("review_rate"),
                    group.get("calibration_error"),
                    segment.get("max_min_tpr_gap"),
                    segment.get("max_min_fpr_gap"),
                    segment.get("review_rate_ratio"),
                ]
            )
    return (
        [
            "segment_key",
            "segment_name",
            "group_name",
            "applications",
            "positive_labels",
            "is_publishable",
            "catch_rate",
            "false_positive_rate",
            "precision",
            "review_rate",
            "calibration_error",
            "segment_max_min_tpr_gap",
            "segment_max_min_fpr_gap",
            "segment_review_rate_ratio",
        ],
        rows,
    )


def fact_drift(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    drift = model.get("drift", {})
    window = drift.get("reference_window") or []
    reference = f"{window[0]}-{window[-1]}" if window else ""
    rows = [
        [
            row["feature"],
            row["month"],
            row["psi"],
            row["status"],
            reference,
            bool(row.get("in_training_window")),
        ]
        for row in drift.get("rows", [])
    ]
    return [
        "feature_name",
        "month",
        "psi",
        "psi_status",
        "reference_window",
        "in_training_window",
    ], rows


def fact_variant(model: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = []
    for variant in model.get("variant_stress_tests", []):
        for metric, value in variant.get("metrics", {}).items():
            rows.append([variant["evidence_source"], variant.get("rows"), metric, value])
    return ["evidence_source_key", "applications", "metric_name", "metric_value"], rows


def fact_linking_run(linking: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = []
    for run in linking.get("runs", []):
        pairwise = run.get("pairwise", {})
        cubed = run.get("b_cubed", {})
        flags = run.get("ring_flags", {})
        rows.append(
            [
                run["corruption"],
                run["seed"],
                run.get("applications"),
                pairwise.get("precision"),
                pairwise.get("recall"),
                pairwise.get("f1"),
                cubed.get("f1"),
                run.get("false_merge_rate"),
                run.get("false_splits"),
                flags.get("ring_recall"),
                flags.get("flagged_rings"),
                flags.get("queue_impact_applications"),
                run.get("elapsed_seconds"),
            ]
        )
    return (
        [
            "corruption",
            "seed",
            "applications",
            "pairwise_precision",
            "pairwise_recall",
            "pairwise_f1",
            "b_cubed_f1",
            "false_merge_rate",
            "false_splits",
            "ring_recall",
            "flagged_rings",
            "queue_impact_applications",
            "elapsed_seconds",
        ],
        rows,
    )


def fact_data_quality(curation: dict[str, Any]) -> tuple[Sequence[str], list[Sequence[Any]]]:
    rows = [
        [
            record["evidence_source"],
            record["file_name"],
            record.get("rows"),
            record.get("columns"),
            record.get("curated_columns"),
            record.get("positive_count"),
            record.get("prevalence"),
            record.get("sha256"),
            record.get("curated_sha256"),
            record.get("elapsed_seconds"),
        ]
        for record in curation.get("files", [])
    ]
    return (
        [
            "evidence_source_key",
            "file_name",
            "rows",
            "source_columns",
            "curated_columns",
            "positive_count",
            "prevalence",
            "source_sha256",
            "curated_sha256",
            "curation_seconds",
        ],
        rows,
    )


def fact_run_context(model: dict[str, Any], linking: dict[str, Any], curation: dict[str, Any]):
    lift = model.get("pr_auc_lift_bootstrap", {})
    rows = [
        ["dataset_version", model.get("dataset_version")],
        ["evidence_revision", model.get("evaluation_source_sha")],
        ["champion", COMPARATOR_LABELS.get(model.get("champion"), model.get("champion"))],
        [
            "challenger",
            COMPARATOR_LABELS.get(model.get("selected_challenger"), model.get("selected_challenger")),
        ],
        ["challenger_approval_state", model.get("approval_state")],
        ["strategy_recommendation", model.get("strategy_frontier", {}).get("recommendation")],
        ["test_month", 7],
        ["test_applications", model.get("rows", {}).get("test")],
        ["pr_auc_lift_observed", lift.get("observed")],
        ["pr_auc_lift_ci_lower", lift.get("lower_95")],
        ["pr_auc_lift_ci_upper", lift.get("upper_95")],
        ["drift_warnings", model.get("drift", {}).get("warnings")],
        ["drift_blocks", model.get("drift", {}).get("blocks")],
        ["linking_all_gates_pass", linking.get("all_gates_pass")],
        ["source_rows_curated", curation.get("total_rows")],
        [
            "assumption_notice",
            model.get("strategy_frontier", {}).get("assumption_notice"),
        ],
    ]
    for index, reason in enumerate(model.get("strategy_frontier", {}).get("refusal_reasons", []), start=1):
        rows.append([f"refusal_reason_{index}", reason])
    return ["context_key", "context_value"], rows


def build(evidence_dir: Path, output_dir: Path) -> dict[str, int]:
    model = read_json(evidence_dir / "model_evaluation.json")
    linking = read_json(evidence_dir / "linking_evaluation.json")
    curation = read_json(evidence_dir / "data_curation.json")
    model = dict(model)
    model["linking_gates"] = linking.get("gates", {})
    output_dir.mkdir(parents=True, exist_ok=True)

    tables = {
        "dim_comparator": dim_comparator(model),
        "dim_evidence_source": dim_evidence_source(model, linking),
        "fact_model_metric": fact_model_metric(model),
        "fact_capacity": fact_capacity(model),
        "fact_promotion_gate": fact_promotion_gate(model),
        "fact_strategy_policy": fact_strategy_policy(model),
        "fact_fairness_group": fact_fairness_group(model),
        "fact_drift": fact_drift(model),
        "fact_variant_stress": fact_variant(model),
        "fact_linking_run": fact_linking_run(linking),
        "fact_data_quality": fact_data_quality(curation),
        "fact_run_context": fact_run_context(model, linking, curation),
    }
    counts = {name: write_table(output_dir, name, columns, rows) for name, (columns, rows) in tables.items()}
    manifest = {
        "evidence_ids": [
            model.get("evidence_id"),
            linking.get("evidence_id"),
            curation.get("evidence_id"),
        ],
        "dataset_version": model.get("dataset_version"),
        "evidence_revision": model.get("evaluation_source_sha"),
        "row_counts": counts,
        "boundary": (
            "Aggregate evidence only. No application-level record, no raw BAF data, and no fixture "
            "entity or ring truth is present in this extract."
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default=str(EVIDENCE_DIR))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    arguments = parser.parse_args()
    counts = build(Path(arguments.evidence_dir), Path(arguments.output_dir))
    print(json.dumps(counts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
