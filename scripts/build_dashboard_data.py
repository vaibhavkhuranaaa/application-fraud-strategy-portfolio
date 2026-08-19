"""Precompute every figure the stakeholder dashboard renders.

The dashboard is a static page: no server, no database, no cost. Everything it can
show is computed here from verified evidence and written to one JSON file, so the
whole policy space is explorable in the browser with no round trip.

Counts are computed here; money is computed in the browser from the analyst's own
assumptions, so an assumption can never be mistaken for an observed figure.

    PYTHONPATH=src uv run python scripts/build_dashboard_data.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.analysis.evidence import (  # noqa: E402
    EvidencePaths,
    analysis_frame,
    comparator_label,
    load_bundle,
)
from fraud_strategy.analysis.reasons import reason_codes  # noqa: E402
from fraud_strategy.analysis.scenarios import RULE_LABELS, available_rule_flags  # noqa: E402
from fraud_strategy.config import DEFAULT_CURATED_DIR  # noqa: E402
from fraud_strategy.strategy import (  # noqa: E402
    LOSS_GIVEN_FRAUD_RANGE,
    REVIEW_EFFECTIVENESS_RANGE,
    combine_rule_flags,
    policy_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dashboard" / "data" / "dashboard.json"
RISK_GOVERNANCE = ROOT / "evaluation" / "risk_governance.json"

MODELS = ("catboost_hybrid", "catboost_internal", "regularized_logistic", "incumbent_proxy")
CAPACITIES = (
    0.005,
    0.0075,
    0.01,
    0.015,
    0.02,
    0.025,
    0.03,
    0.04,
    0.05,
    0.06,
    0.07,
    0.08,
    0.10,
    0.12,
    0.15,
    0.18,
    0.20,
    0.25,
)
RULES = tuple(RULE_LABELS)
CASE_SAMPLE = 60

# Plain-language names for the pre-approved promotion checks. The dashboard never
# shows a raw gate identifier to a stakeholder.
CHECK_LABELS = {
    "pr_auc_lift_ci_lower_above_zero": "Ranks fraud better than today's screening, beyond sampling noise",
    "catch_rate_improves_at_three_capacities": "Catches more fraud at the same review workload",
    "no_capacity_regression_over_two_points": "No review level performs materially worse",
    "positive_brier_skill": "Risk estimates beat a naive base-rate guess",
    "ece_at_most_0_02": "Stated risk matches observed risk",
    "calibration_slope_0_8_to_1_2": "Risk estimates are correctly spread",
    "calibration_intercept_abs_at_most_0_10": "Risk estimates are not systematically off",
    "economic_grid_positive_at_least_80_percent": "Pays for itself across the assumption range",
    "no_automatic_promotion_psi_blocks": "The applicant population is stable enough to rely on",
    "fairness_governance_review_resolved": "Segment differences reviewed and accepted",
    "warnings_visible": "Every warning is surfaced to the reader",
}

CHECK_CONSEQUENCE = {
    "calibration_intercept_abs_at_most_0_10": (
        "Both this approach and today's screening overstate risk on the latest period by a similar "
        "margin, so a stated fraud probability cannot be trusted as a number."
    ),
    "no_automatic_promotion_psi_blocks": (
        "The applicant mix moved materially over the period, so results measured on older months may "
        "not hold."
    ),
    "fairness_governance_review_resolved": (
        "Review rates differ enough between customer groups to need a governance decision before use."
    ),
}

SEGMENT_LABELS = {
    "customer_age": "Age band",
    "income": "Income band",
    "source": "Application channel",
    "housing_status": "Housing status",
}

CHANNEL_LABELS = {"INTERNET": "Online", "TELEAPP": "Phone"}

# The main surface is read by people who do not work with models. The technical
# names stay in the analyst section, where the comparator table still uses them.
APPROACH_LABELS = {
    "catboost_hybrid": "Proposed approach",
    "catboost_internal": "Proposed, ignoring the current score",
    "regularized_logistic": "Simple statistical model",
    "incumbent_proxy": "Incumbent score proxy",
}


def rule_subsets() -> list[tuple[str, ...]]:
    subsets: list[tuple[str, ...]] = []
    for size in range(len(RULES) + 1):
        subsets.extend(combinations(RULES, size))
    return subsets


def policy_grid(frame: pd.DataFrame) -> dict[str, Any]:
    """Every model / capacity / rule combination, as counts only."""
    labels = frame["fraud_bool"].to_numpy()
    flags = available_rule_flags(frame)
    subsets = rule_subsets()
    forced_by_subset = {
        subset: (combine_rule_flags(flags, {name: name in set(subset) for name in flags}) if subset else None)
        for subset in subsets
    }
    scores = {model: frame[model].to_numpy() for model in MODELS}

    rows: list[list[Any]] = []
    for model in MODELS:
        for capacity in CAPACITIES:
            for subset in subsets:
                metrics = policy_metrics(
                    labels, scores[model], capacity, forced_review=forced_by_subset[subset]
                )
                rows.append(
                    [
                        MODELS.index(model),
                        CAPACITIES.index(capacity),
                        int("".join("1" if name in set(subset) else "0" for name in RULES), 2),
                        metrics["fraud_caught"],
                        metrics["false_positive_count"],
                        metrics["queue_size"],
                        metrics["governance_referrals"],
                        metrics["capacity_count"],
                    ]
                )
    return {
        "columns": [
            "model",
            "capacity",
            "rules",
            "fraud_caught",
            "good_reviewed",
            "queue_size",
            "referrals",
            "capacity_count",
        ],
        "models": [
            {"key": name, "label": APPROACH_LABELS.get(name, comparator_label(name))} for name in MODELS
        ],
        "capacities": list(CAPACITIES),
        "rules": [{"key": key, "label": RULE_LABELS[key]} for key in RULES],
        "rows": rows,
    }


def monthly_trend(curated_dir: Path) -> list[dict[str, Any]]:
    frame = pd.read_parquet(curated_dir / "base.parquet", columns=["month", "fraud_bool", "source"])
    rows = []
    for month, group in frame.groupby("month"):
        rows.append(
            {
                "month": int(month),
                "applications": int(len(group)),
                "fraud": int(group["fraud_bool"].sum()),
                "fraud_rate": round(float(group["fraud_bool"].mean()), 6),
            }
        )
    return rows


def segment_breakdown(frame: pd.DataFrame, bundle) -> list[dict[str, Any]]:
    """Observed fraud rate by customer group in the evaluation period.

    Groups below the publication threshold are marked rather than dropped, so a reader
    can see that they exist and why their numbers are withheld.
    """
    published: list[dict[str, Any]] = []
    definitions = [
        ("source", "Application channel", lambda f: f["source"].map(lambda v: CHANNEL_LABELS.get(v, v))),
        ("housing_status", "Housing status", lambda f: f["housing_status"].astype(str)),
        (
            "customer_age",
            "Age band",
            lambda f: f["customer_age"].map(lambda v: f"{int(v)}–{int(v) + 9}"),
        ),
        (
            "income_band",
            "Income band",
            lambda f: pd.cut(
                f["income"],
                bins=[-0.01, 0.3, 0.6, 0.8, 1.01],
                labels=["Lowest 30%", "30–60%", "60–80%", "Top 20%"],
            ).astype(str),
        ),
    ]
    for key, label, accessor in definitions:
        values = accessor(frame)
        groups = []
        for name, group in frame.groupby(values, observed=True):
            fraud = int(group["fraud_bool"].sum())
            publishable = fraud >= 200
            # Withheld at build time, not only at render time. The payload is a public
            # static file, so shipping the counts and hiding them in the page would still
            # publish a group estimate the evaluation contract does not permit. Volume
            # stays, because it is what shows the group exists rather than a fraud figure.
            groups.append(
                {
                    "group": str(name),
                    "applications": int(len(group)),
                    "fraud": fraud if publishable else None,
                    "fraud_rate": round(float(group["fraud_bool"].mean()), 6) if publishable else None,
                    "publishable": publishable,
                }
            )
        groups.sort(key=lambda row: -row["applications"])
        published.append({"key": key, "label": label, "groups": groups})
    return published


def monthly_kpi(paths: EvidencePaths) -> dict[str, Any]:
    """The operating record, read from the KPI pack the fraud database produces.

    Absent rather than fabricated when the pack has not been built: the desk view is a
    claim about what happened, and an empty one is honest where a placeholder is not.
    """
    source = Path("evaluation/monthly_kpi.json")
    if not source.is_file():
        return {}
    pack = json.loads(source.read_text(encoding="utf-8"))
    challenger = [row for row in pack["monthly"] if not row["model_version"].startswith("incumbent")]
    return {
        "capacity": pack["review_capacity"],
        "source": pack["source"],
        "periods": [
            {
                "period": row["period"],
                "applications": row["applications"],
                "fraud": row["fraud_attempts"],
                "rate_bps": row["fraud_rate_bps"],
                "reviewed": row["queue_size"],
                "caught": row["fraud_caught"],
                "catch_rate": row["catch_rate"],
                "catch_change": row["catch_rate_change"],
                "yield": row["investigator_yield"],
                "overshoot": row["capacity_overshoot"],
            }
            for row in challenger
        ],
        "vendor": [
            {
                "period": row["period"],
                "incumbent": row["incumbent_catch_rate"],
                "challenger": row["challenger_catch_rate"],
                "extra_caught": row["additional_fraud_caught"],
            }
            for row in pack["vendor_performance"]
        ],
    }


def case_sample(frame: pd.DataFrame, paths: EvidencePaths) -> list[dict[str, Any]]:
    """The top of the review queue under the default policy, with drivers."""
    default_model = "catboost_hybrid"
    ordered = frame.nlargest(CASE_SAMPLE, default_model).reset_index(drop=True)
    flags = available_rule_flags(frame)
    order_index = frame[default_model].to_numpy().argsort()[::-1][:CASE_SAMPLE]
    reasons = reason_codes(ordered, paths.candidate_model)
    rows = []
    for position, record in enumerate(ordered.to_dict("records")):
        source_index = int(order_index[position])
        fired = [RULE_LABELS[name] for name in RULES if bool(flags[name][source_index])]
        rows.append(
            {
                "rank": position + 1,
                "id": record["application_id"][:12],
                "score": round(float(record[default_model]), 6),
                "confirmed_fraud": int(record["fraud_bool"]) == 1,
                "rules_fired": fired,
                "drivers": reasons[position] if position < len(reasons) else [],
            }
        )
    return rows


def analyst_detail(bundle) -> dict[str, Any]:
    model = bundle.model
    drift = model.get("drift", {})
    blocks: dict[str, int] = {}
    for row in drift.get("rows", []):
        if row["status"] == "block":
            blocks[row["feature"]] = blocks.get(row["feature"], 0) + 1
    window = drift.get("reference_window") or []
    reference = f"months {window[0]} to {window[-1]}" if window else "unavailable"
    return {
        "comparators": [
            {
                "key": name,
                "label": comparator_label(name),
                "metrics": {k: round(float(v), 6) for k, v in metrics.items()},
            }
            for name, metrics in model.get("month_7_metrics", {}).items()
        ],
        "lift": model.get("pr_auc_lift_bootstrap", {}),
        "calibration": {
            name: {
                "selected": record.get("selected"),
                "month_6_intercept": record.get("month_6_metrics", {}).get("calibration_intercept"),
            }
            for name, record in model.get("calibration", {}).items()
        },
        "drift": {
            "checks": len(drift.get("rows", [])),
            "warnings": drift.get("warnings"),
            "blocks": drift.get("blocks"),
            "reference": reference,
            "top_features": sorted(blocks.items(), key=lambda item: -item[1])[:8],
        },
        "variants": [
            {
                "source": variant["evidence_source"],
                "pr_auc": round(float(variant["metrics"]["pr_auc"]), 6),
                "auroc": round(float(variant["metrics"]["auroc"]), 6),
            }
            for variant in model.get("variant_stress_tests", [])
        ],
        "fairness_reasons": model.get("fairness", {}).get("reasons", []),
        # Surfaced so a reader sees that a person accepted these differences on a date,
        # rather than inferring the numbers improved. The gap is unchanged.
        "fairness_acceptance": (
            {
                "date": acceptance.get("date"),
                "decision": acceptance.get("decision"),
                "feature_decision": acceptance.get("feature_decision"),
            }
            if (acceptance := (model.get("fairness", {}).get("governance_acceptance") or {}))
            else None
        ),
        "linking": {
            "summary": bundle.linking.get("summary", {}),
            "limitation": bundle.linking.get("limitation"),
        },
        "provenance": {
            "files": [
                {
                    "name": record["file_name"],
                    "rows": record["rows"],
                    "fraud_rate": record["prevalence"],
                    "sha256": record["sha256"][:12],
                }
                for record in bundle.curation.get("files", [])
            ],
            "dataset_version": bundle.dataset_version,
            "evidence_revision": bundle.evidence_sha[:7],
        },
    }


def default_policy(frame: pd.DataFrame) -> dict[str, Any]:
    """The scenario the page opens on, in the shape the browser derives at load."""
    labels = frame["fraud_bool"].to_numpy()
    metrics = policy_metrics(labels, frame["catboost_hybrid"].to_numpy(), 0.05)
    actioned = metrics["queue_size"] + metrics["governance_referrals"]
    fraud = int(labels.sum())
    good = int(len(labels) - fraud)
    return {
        "capacity": 0.05,
        "caught": metrics["fraud_caught"],
        "goodReviewed": metrics["false_positive_count"],
        "worked": metrics["queue_size"],
        "referrals": metrics["governance_referrals"],
        "ceiling": metrics["capacity_count"],
        "actioned": actioned,
        "captureRate": metrics["fraud_caught"] / fraud,
        "insultRate": metrics["false_positive_count"] / good,
        "hitRate": metrics["fraud_caught"] / actioned if actioned else 0,
        "reviewRate": actioned / len(labels),
    }


def build(paths: EvidencePaths, output: Path) -> dict[str, Any]:
    bundle = load_bundle(paths)
    if bundle.gaps:
        raise SystemExit(f"evidence missing: {[gap.path for gap in bundle.gaps]}")
    frame = analysis_frame(paths)
    model = bundle.model
    governance = json.loads(RISK_GOVERNANCE.read_text(encoding="utf-8"))

    gates = model.get("promotion_gates", {})
    checks = [
        {
            "key": key,
            "label": CHECK_LABELS.get(key, key.replace("_", " ")),
            "passed": bool(passed),
            "consequence": CHECK_CONSEQUENCE.get(key),
        }
        for key, passed in sorted(gates.items(), key=lambda item: (item[1], item[0]))
    ]

    payload = {
        "meta": {
            "period_label": "Month 7",
            "period_note": "Final period, held back from every modelling decision",
            "applications": int(len(frame)),
            "fraud": int(frame["fraud_bool"].sum()),
            "fraud_rate": round(float(frame["fraud_bool"].mean()), 6),
            "dataset_version": bundle.dataset_version,
            "evidence_revision": bundle.evidence_sha[:7],
            "data_nature": "Synthetic account-opening records. Not observed lending outcomes.",
            "good": int((frame["fraud_bool"] == 0).sum()),
        },
        "decision": {
            "status": "refused" if bundle.refused else "recommended",
            "headline": "Not approved for rollout"
            if bundle.refused
            else f"Recommended: {bundle.recommendation}",
            "checks_total": len(gates),
            "checks_passed": sum(1 for value in gates.values() if value),
            "checks": checks,
            "reasons": bundle.refusal_reasons,
        },
        "governance": governance,
        "trend": monthly_trend(paths.curated_dir),
        "policies": policy_grid(frame),
        "segments": segment_breakdown(frame, bundle),
        "kpi": monthly_kpi(paths),
        "cases": case_sample(frame, paths),
        "analyst": analyst_detail(bundle),
        "default_policy": default_policy(frame),
        "assumptions": {
            "fraud_exposure": {"min": 5000, "max": 20000, "default": 12500, "step": 100},
            "review_cost": {"min": 7, "max": 27, "default": 17, "step": 1},
            "friction_cost": {"min": 0, "max": 300, "default": 150, "step": 10},
            # Two factors sit between fraud caught and money saved. Neither has a source
            # meeting this project's citation bar, so they are not controls the reader can
            # set: they are stated bounds, and every money figure is shown as the range
            # across them rather than as a point that assumes both are perfect.
            "recovery_bounds": {
                "low": round(min(REVIEW_EFFECTIVENESS_RANGE) * min(LOSS_GIVEN_FRAUD_RANGE), 4),
                "high": round(max(REVIEW_EFFECTIVENESS_RANGE) * max(LOSS_GIVEN_FRAUD_RANGE), 4),
                "review_effectiveness": list(REVIEW_EFFECTIVENESS_RANGE),
                "loss_given_fraud": list(LOSS_GIVEN_FRAUD_RANGE),
            },
            "note": (
                "The source data records no loan exposure, review cost, or customer value. Every "
                "money figure on this page is arithmetic over these three inputs, and is shown as a "
                "range because a review does not stop every fraud it finds and a stopped fraud does "
                "not recover the whole balance. Neither of those two factors is an observed figure."
            ),
        },
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return payload


def inline_into_page(payload: dict[str, Any], root: Path) -> dict[str, int]:
    """Inline the stylesheet, evidence payload, and above-the-fold facts into the page.

    A linked stylesheet costs a round trip before first paint, and the decision band
    would otherwise wait for the full payload. The complete payload is also small enough
    to carry in the HTML, so the static artifact works when opened directly from disk.
    The separate JSON remains a transparent fallback and inspection artifact.
    """
    page = root / "dashboard" / "index.html"
    styles = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")
    default = payload["default_policy"]
    critical = {
        "meta": payload["meta"],
        "decision": payload["decision"],
        "policy": default,
        "governance": {
            "incumbent_disposition": payload["governance"]["incumbent_disposition"],
            "uncertainty": payload["governance"]["uncertainty"],
            "reopen_decision_when": payload["governance"]["reopen_decision_when"],
        },
    }
    critical_json = json.dumps(critical, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c")
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c")

    html = page.read_text(encoding="utf-8")
    html = re.sub(
        r"<!--styles:start-->.*?<!--styles:end-->",
        "<!--styles:start--><style>" + styles + "</style><!--styles:end-->",
        html,
        flags=re.S,
    )
    script = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
    html = re.sub(
        r"<!--script:start-->.*?<!--script:end-->",
        "<!--script:start--><script>" + script + "</script><!--script:end-->",
        html,
        flags=re.S,
    )
    critical_markup = (
        '<!--critical:start--><script type="application/json" id="critical">'
        + critical_json
        + "</script><!--critical:end-->"
    )
    html = re.sub(
        r"<!--critical:start-->.*?<!--critical:end-->",
        lambda _: critical_markup,
        html,
        flags=re.S,
    )
    payload_markup = (
        '<!--data:start--><script type="application/json" id="dashboard-data">'
        + payload_json
        + "</script><!--data:end-->"
    )
    html = re.sub(
        r"<!--data:start-->.*?<!--data:end-->",
        lambda _: payload_markup,
        html,
        flags=re.S,
    )
    page.write_text(html, encoding="utf-8")
    write_csp_hashes(html, root)
    return {
        "page_bytes": len(html.encode("utf-8")),
        "critical_bytes": len(critical_json.encode("utf-8")),
        "embedded_payload_bytes": len(payload_json.encode("utf-8")),
    }


def write_csp_hashes(html: str, root: Path) -> None:
    """Pin the inlined style and script by hash so the policy stays strict.

    Inlining them would otherwise force `unsafe-inline`, which is the whole point of
    a content-security policy given away. The hashes change with every build, so the
    header file is generated alongside the page.
    """
    blocks = {
        "style": re.findall(r"<style>(.*?)</style>", html, flags=re.S),
        "script": re.findall(r"<script>(.*?)</script>", html, flags=re.S),
    }
    digests = {
        kind: " ".join(
            "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"
            for body in bodies
        )
        for kind, bodies in blocks.items()
    }
    directives = (
        f"default-src 'none'; script-src {digests['script']}; style-src {digests['style']}; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'"
    )

    headers = root / "dashboard" / "_headers"
    text = headers.read_text(encoding="utf-8")
    # frame-ancestors is header-only. It is meaningless in a meta tag and is kept here.
    text = re.sub(
        r"  Content-Security-Policy: .*",
        f"  Content-Security-Policy: {directives}; frame-ancestors 'none'",
        text,
    )
    headers.write_text(text, encoding="utf-8")

    # The same policy, carried in the page itself. A host that ignores `_headers`, which
    # includes GitHub Pages, would otherwise serve this page with no policy at all. A meta
    # tag cannot express frame-ancestors, so that one directive is lost on such a host and
    # the deviation is recorded rather than left to be discovered.
    page = root / "dashboard" / "index.html"
    markup = page.read_text(encoding="utf-8")
    tag = f'<!--csp:start--><meta http-equiv="Content-Security-Policy" content="{directives}"><!--csp:end-->'
    if "<!--csp:start-->" in markup:
        markup = re.sub(r"<!--csp:start-->.*?<!--csp:end-->", tag, markup, flags=re.S)
    else:
        anchor = '<meta name="viewport" content="width=device-width, initial-scale=1">'
        markup = markup.replace(anchor, anchor + "\n" + tag, 1)
    page.write_text(markup, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--curated-dir", type=Path, default=DEFAULT_CURATED_DIR)
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("evaluation"))
    arguments = parser.parse_args()
    payload = build(
        EvidencePaths(
            curated_dir=arguments.curated_dir,
            artifact_dir=arguments.artifact_dir,
            evidence_dir=arguments.evidence_dir,
        ),
        Path(arguments.output),
    )
    inlined = inline_into_page(payload, ROOT)
    size = Path(arguments.output).stat().st_size
    print(
        json.dumps(
            {
                "policies": len(payload["policies"]["rows"]),
                "months": len(payload["trend"]),
                "cases": len(payload["cases"]),
                "segments": sum(len(s["groups"]) for s in payload["segments"]),
                "bytes": size,
                **inlined,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
