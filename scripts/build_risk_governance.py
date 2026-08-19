"""Build aggregate risk-governance evidence from frozen evaluation artifacts.

The output contains controls and aggregate counts only. Curated rows and score artifacts
remain ignored local inputs and never enter the public repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.analysis.evidence import EvidencePaths, analysis_frame  # noqa: E402
from fraud_strategy.analysis.scenarios import RULE_LABELS, available_rule_flags  # noqa: E402
from fraud_strategy.strategy import rank_review_queue  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation" / "risk_governance.json"


def _bootstrap_delta(values: np.ndarray, *, resamples: int, seed: int) -> list[int]:
    """Paired row bootstrap for a vector whose only values are -1, 0, and 1."""
    counts = np.array([(values == value).sum() for value in (-1, 0, 1)], dtype=int)
    draws = np.random.default_rng(seed).multinomial(len(values), counts / len(values), size=resamples)
    deltas = draws[:, 2] - draws[:, 0]
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    return [int(np.floor(lower)), int(np.ceil(upper))]


def paired_uncertainty(
    paths: EvidencePaths,
    walk_forward: Path,
    *,
    capacity: float = 0.05,
    resamples: int = 5000,
    seed: int = 20260818,
) -> dict[str, Any]:
    frame = analysis_frame(paths)
    labels = frame["fraud_bool"].to_numpy(dtype=np.int8)
    challenger = rank_review_queue(frame["catboost_hybrid"].to_numpy(), capacity)
    incumbent = rank_review_queue(frame["incumbent_proxy"].to_numpy(), capacity)
    challenger_actioned = challenger.review_mask | challenger.referral_mask
    incumbent_actioned = incumbent.review_mask | incumbent.referral_mask

    caught_delta = labels * (challenger_actioned.astype(int) - incumbent_actioned.astype(int))
    good_delta = (1 - labels) * (challenger_actioned.astype(int) - incumbent_actioned.astype(int))
    folds = json.loads(walk_forward.read_text(encoding="utf-8"))["folds"]
    temporal = [
        {
            "period": fold["test_period"],
            "challenger_caught": fold["catboost_hybrid"]["fraud_caught"]["0.05"],
            "incumbent_caught": fold["incumbent_proxy"]["fraud_caught"]["0.05"],
            "incremental_caught": (
                fold["catboost_hybrid"]["fraud_caught"]["0.05"]
                - fold["incumbent_proxy"]["fraud_caught"]["0.05"]
            ),
        }
        for fold in folds
    ]
    return {
        "status": "decision evidence, not a promotion gate",
        "approach": "catboost_hybrid",
        "baseline": "incumbent_proxy",
        "capacity": capacity,
        "fraud_caught_delta": {
            "estimate": int(caught_delta.sum()),
            "paired_interval_95": _bootstrap_delta(caught_delta, resamples=resamples, seed=seed),
        },
        "good_reviewed_delta": {
            "estimate": int(good_delta.sum()),
            "paired_interval_95": _bootstrap_delta(good_delta, resamples=resamples, seed=seed + 1),
        },
        "temporal_folds": temporal,
        "positive_temporal_folds": sum(row["incremental_caught"] > 0 for row in temporal),
        "resamples": resamples,
        "seed": seed,
        "method": (
            "Fixed-seed paired row bootstrap of frozen month-7 queue membership. The challenger and "
            "incumbent use identical five-percent capacity and deterministic score ordering."
        ),
        "limitation": (
            "The interval measures sampling uncertainty conditional on one synthetic period and frozen "
            "rankings. Five synthetic time folds do not establish future production performance."
        ),
    }


RULE_DECISIONS = {
    "dob_email_concentration": (
        "reject",
        "Reject as a queue override. It overwhelms capacity and displaces higher-ranked fraud.",
    ),
    "device_email_concentration": (
        "refer",
        "Refer for controlled validation as a reason code only. It worsens the challenger queue and has no temporal validation.",
    ),
    "foreign_low_identity_similarity": (
        "reject",
        "Reject as a queue override. It adds friction and reduces fraud caught at fixed capacity.",
    ),
    "branch_concentration": (
        "reject",
        "Reject as a queue override. It adds friction, reduces fraud caught, and uses a final-period cutoff.",
    ),
}


MONITORING_CONTROLS = [
    {
        "key": "calibration",
        "label": "Calibration",
        "availability": "measurable retrospectively; production feed unavailable",
        "owner_role": "Model Risk",
        "cadence": "Each label-mature evaluation period",
        "threshold_basis": "Pre-agreed gate: absolute calibration intercept at most 0.10",
        "trigger": "Absolute calibration intercept exceeds 0.10",
        "action": "Prohibit probability interpretation and promotion; convene recalibration review",
        "evidence_source": "evaluation/model_evaluation.json and docs/label-latency.md",
        "limitation": "BAF has no outcome timestamps, so it cannot establish a production trigger.",
    },
    {
        "key": "stability",
        "label": "Population stability",
        "availability": "measurable retrospectively; production feed unavailable",
        "owner_role": "Fraud Strategy Owner",
        "cadence": "Each period close",
        "threshold_basis": "Pre-agreed PSI warning at 0.10 and promotion block at 0.25",
        "trigger": "Any feature reaches the 0.25 promotion-block level",
        "action": "Keep rollout blocked; investigate seasonal versus durable shift before refitting",
        "evidence_source": "evaluation/model_evaluation.json drift record",
        "limitation": "The static evidence has no continuing production population feed.",
    },
    {
        "key": "review_yield",
        "label": "Investigator review yield",
        "availability": "needs production data",
        "owner_role": "Fraud Operations",
        "cadence": "Weekly after a measured baseline exists",
        "threshold_basis": "Proposed: compare with the trailing four label-mature periods",
        "trigger": "Material fall against the governed trailing baseline",
        "action": "Investigate queue and rule composition; do not retrain automatically",
        "evidence_source": "docs/feedback-loop.md",
        "limitation": "No investigator handling or operating-yield baseline exists in BAF.",
    },
    {
        "key": "capacity",
        "label": "Review capacity",
        "availability": "measurable in the scenario",
        "owner_role": "Fraud Operations",
        "cadence": "Daily in a production process",
        "threshold_basis": "Demand must fit the explicitly selected staffed ceiling",
        "trigger": "Any governance referral beyond the selected capacity",
        "action": "Stop expanding referrals and return the policy to governance; never auto decline",
        "evidence_source": "dashboard/data/dashboard.json policy grid",
        "limitation": "Capacity is an analyst input here, not observed staffing.",
    },
    {
        "key": "friction",
        "label": "Customer friction",
        "availability": "needs production data",
        "owner_role": "Customer and Conduct Risk",
        "cadence": "Monthly after labels and customer outcomes mature",
        "threshold_basis": "Proposed: governance-approved good-review and segment-friction bands",
        "trigger": "Good-review rate or segment gap leaves its approved band",
        "action": "Pause the policy change and review causes before resuming",
        "evidence_source": "Scenario insult rate and evaluation fairness evidence",
        "limitation": "Review is only a friction proxy; BAF has no abandonment or customer-value outcome.",
    },
    {
        "key": "label_maturity",
        "label": "Label maturity",
        "availability": "needs production data",
        "owner_role": "Data and Model Governance",
        "cadence": "Each outcome vintage",
        "threshold_basis": "A measured maturity curve and event timestamps must precede outcome reporting",
        "trigger": "No measured maturity curve, timestamp lineage, or sufficiently mature vintage",
        "action": "Keep outcome metrics non-operational and require an append-only outcome feed",
        "evidence_source": "docs/label-latency.md and docs/feedback-loop.md",
        "limitation": "The current maturity curve is declared, not measured from BAF.",
    },
    {
        "key": "segments",
        "label": "Segment performance",
        "availability": "measurable retrospectively under conditional acceptance",
        "owner_role": "Fair Lending and Model Governance",
        "cadence": "Each label-mature evaluation period",
        "threshold_basis": "Accepted gaps reopen if they widen by more than 0.05",
        "trigger": "An accepted disparity widens by more than 0.05 or acceptance lapses",
        "action": "Reopen governance review; never set a group-specific decision threshold",
        "evidence_source": "evaluation/governance_acceptance.json and docs/model-card.md",
        "limitation": "Aggregate synthetic evidence does not establish production treatment effects.",
    },
]


def rule_incrementality(paths: EvidencePaths, *, capacity: float = 0.05) -> list[dict[str, Any]]:
    frame = analysis_frame(paths)
    labels = frame["fraud_bool"].to_numpy(dtype=np.int8)
    scores = frame["catboost_hybrid"].to_numpy()
    flags = available_rule_flags(frame)
    base = rank_review_queue(scores, capacity)
    base_actioned = base.review_mask | base.referral_mask
    rows = []
    for key, flag in flags.items():
        outcome = rank_review_queue(scores, capacity, forced_review=flag)
        actioned = outcome.review_mask | outcome.referral_mask
        other_flags = np.logical_or.reduce([value for name, value in flags.items() if name != key])
        disposition, rationale = RULE_DECISIONS[key]
        rows.append(
            {
                "key": key,
                "label": RULE_LABELS[key],
                "disposition": disposition,
                "rationale": rationale,
                "capacity": capacity,
                "flagged_records": int(flag.sum()),
                "flagged_fraud": int((flag & (labels == 1)).sum()),
                "flagged_good": int((flag & (labels == 0)).sum()),
                "overlap_with_model_queue": int((flag & base_actioned).sum()),
                "overlap_with_other_rules": int((flag & other_flags).sum()),
                "unique_fraud_added": int((actioned & ~base_actioned & (labels == 1)).sum()),
                "fraud_displaced": int((base_actioned & ~actioned & (labels == 1)).sum()),
                "incremental_fraud_caught": int((actioned & (labels == 1)).sum())
                - int((base_actioned & (labels == 1)).sum()),
                "incremental_good_reviewed": int((actioned & (labels == 0)).sum())
                - int((base_actioned & (labels == 0)).sum()),
                "queue_overflow": outcome.overflow,
                "policy_boundary": "Non-binding reason code only. Never automatic decline or unbounded review.",
                "limitation": (
                    "One synthetic held-back period. Overlap is between application records, not "
                    "shared identities or fraud rings."
                ),
            }
        )
    return rows


def build(paths: EvidencePaths, walk_forward: Path, output: Path) -> dict[str, Any]:
    record = json.loads(output.read_text(encoding="utf-8"))
    record["uncertainty"] = paired_uncertainty(paths, walk_forward)
    record["rule_dispositions"] = rule_incrementality(paths)
    record["monitoring_controls"] = MONITORING_CONTROLS
    record["reopen_decision_when"] = [
        "A challenger passes all eleven unchanged promotion checks on untouched evidence",
        "Production label maturity, investigator handling, capacity, and customer-friction feeds are verified",
        "Every monitoring control has an accepted accountable owner and response process",
        "Governance approves the bounded use after reviewing calibration, stability, and segment evidence",
    ]
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated-dir", type=Path, default=Path("data/curated"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("evaluation"))
    parser.add_argument("--walk-forward", type=Path, default=Path("evaluation/walk_forward_backtest.json"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    record = build(
        EvidencePaths(
            curated_dir=args.curated_dir,
            artifact_dir=args.artifact_dir,
            evidence_dir=args.evidence_dir,
        ),
        args.walk_forward,
        args.output,
    )
    print(json.dumps(record["uncertainty"], indent=2))


if __name__ == "__main__":
    main()
