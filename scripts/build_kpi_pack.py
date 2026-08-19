"""Monthly Fraud KPI pack, read out of the Fraud Schema.

The posting names this twice: routine Monthly Fraud KPI reporting, and vendor performance
reporting. The project could compare models but had no recurring operational report, which
is the artifact a fraud desk actually runs on.

Every figure here is aggregated in PostgreSQL from `analytics.fact_daily_strategy`, which
`fraud_strategy.operations` builds from the scores and queue the desk writes. Nothing is
recomputed in pandas. That is the point of wiring the schema: the reporting layer reads
the system of record rather than a parallel copy of it.

"Vendor performance" is the incumbent score proxy measured against the challenger at
identical review capacity. `credit_risk_score` stands in for a third-party decision score
and is never described as a verified vendor product.

    PYTHONPATH=src uv run python scripts/build_kpi_pack.py

Outputs `evaluation/monthly_kpi.json` plus three operational fact tables in
`powerbi/data/`. Requires `FRAUD_DATABASE_URL` and a database populated by
`fraud_strategy.cli operate`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraud_strategy.config import DATASET_VERSION  # noqa: E402
from fraud_strategy.modeling import code_sha  # noqa: E402
from fraud_strategy.operations import OPERATING_CAPACITY  # noqa: E402

EVIDENCE_DIR = Path("evaluation")
OUTPUT_DIR = Path("powerbi/data")

MONTHLY_SQL = """
SELECT d.month_label,
       m.model_version,
       m.approval_state,
       sum(f.application_count) AS applications,
       sum(f.fraud_count) AS fraud_count,
       sum(f.fraud_caught) AS fraud_caught,
       sum(f.good_customer_reviews) AS good_customer_reviews,
       sum(f.application_count) FILTER (WHERE a.action_code <> 'clear') AS queue_size
FROM analytics.fact_daily_strategy f
JOIN analytics.dim_date d USING (date_key)
JOIN analytics.dim_model m USING (model_key)
JOIN analytics.dim_action a USING (action_key)
GROUP BY d.date_key, d.month_label, m.model_version, m.approval_state
ORDER BY d.date_key, m.model_version
"""

CHANNEL_SQL = """
SELECT d.month_label,
       m.model_version,
       c.channel_label,
       sum(f.application_count) AS applications,
       sum(f.fraud_count) AS fraud_count,
       sum(f.fraud_caught) AS fraud_caught,
       sum(f.good_customer_reviews) AS good_customer_reviews
FROM analytics.fact_daily_strategy f
JOIN analytics.dim_date d USING (date_key)
JOIN analytics.dim_model m USING (model_key)
JOIN analytics.dim_channel c USING (channel_key)
GROUP BY d.date_key, d.month_label, m.model_version, c.channel_label
ORDER BY d.date_key, m.model_version, c.channel_label
"""

RISK_BAND_SQL = """
SELECT d.month_label,
       m.model_version,
       g.segment_value AS risk_band,
       sum(f.application_count) AS applications,
       sum(f.fraud_count) AS fraud_count,
       sum(f.fraud_caught) AS fraud_caught
FROM analytics.fact_daily_strategy f
JOIN analytics.dim_date d USING (date_key)
JOIN analytics.dim_model m USING (model_key)
JOIN analytics.dim_segment g USING (segment_key)
WHERE g.segment_type = 'risk_band'
GROUP BY d.date_key, d.month_label, m.model_version, g.segment_value
ORDER BY d.date_key, m.model_version, g.segment_value
"""


def write_table(directory: Path, name: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    with (directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)
            written += 1
    return written


def rate(numerator: float, denominator: float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def fetch(cursor: Any, sql: str) -> list[dict[str, Any]]:
    cursor.execute(sql)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def monthly_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per period and model, with month-over-month movement inside each model's series."""
    rows: list[dict[str, Any]] = []
    previous: dict[str, dict[str, Any]] = {}
    for record in raw:
        applications = int(record["applications"])
        fraud = int(record["fraud_count"])
        caught = int(record["fraud_caught"])
        good = int(record["good_customer_reviews"])
        queue = int(record["queue_size"] or 0)
        row = {
            "period": record["month_label"],
            "model_version": record["model_version"],
            "approval_state": record["approval_state"],
            "applications": applications,
            "fraud_attempts": fraud,
            "fraud_rate_bps": round((rate(fraud, applications) or 0) * 10_000, 2),
            "queue_size": queue,
            "review_rate": round(rate(queue, applications) or 0, 6),
            "fraud_caught": caught,
            "catch_rate": round(rate(caught, fraud) or 0, 6),
            "investigator_yield": round(rate(caught, queue) or 0, 6),
            "good_customers_reviewed": good,
            "friction_rate": round(rate(good, applications - fraud) or 0, 6),
            "fraud_missed": fraud - caught,
            # A score threshold cannot land on an exact headcount when the score has ties,
            # because every application at the cutting value has to be treated the same
            # way. The incumbent proxy is a low-cardinality integer score, so its tied
            # block is large and the queue overshoots. A desk staffing to a fixed reviewer
            # count pays for that overshoot in overtime, so it is reported rather than
            # rounded away.
            "capacity_headcount": int(applications * OPERATING_CAPACITY),
            "capacity_overshoot": queue - int(applications * OPERATING_CAPACITY),
        }
        prior = previous.get(record["model_version"])
        row["catch_rate_change"] = round(row["catch_rate"] - prior["catch_rate"], 6) if prior else None
        row["fraud_rate_bps_change"] = (
            round(row["fraud_rate_bps"] - prior["fraud_rate_bps"], 2) if prior else None
        )
        previous[record["model_version"]] = row
        rows.append(row)
    return rows


def vendor_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Incumbent score proxy against the challenger at identical review capacity."""
    by_period: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_period.setdefault(row["period"], {})[row["model_version"]] = row
    comparison: list[dict[str, Any]] = []
    for period, models in by_period.items():
        incumbent = next((row for name, row in models.items() if name.startswith("incumbent")), None)
        challenger = next((row for name, row in models.items() if not name.startswith("incumbent")), None)
        if not incumbent or not challenger:
            continue
        comparison.append(
            {
                "period": period,
                "incumbent_catch_rate": incumbent["catch_rate"],
                "challenger_catch_rate": challenger["catch_rate"],
                "catch_rate_gap": round(challenger["catch_rate"] - incumbent["catch_rate"], 6),
                "incumbent_fraud_caught": incumbent["fraud_caught"],
                "challenger_fraud_caught": challenger["fraud_caught"],
                "additional_fraud_caught": challenger["fraud_caught"] - incumbent["fraud_caught"],
                "review_capacity": OPERATING_CAPACITY,
                "queue_size": challenger["queue_size"],
            }
        )
    return sorted(comparison, key=lambda item: item["period"])


def build(dsn: str, output_dir: Path, evidence_dir: Path) -> dict[str, Any]:
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        monthly_raw = fetch(cursor, MONTHLY_SQL)
        channel_raw = fetch(cursor, CHANNEL_SQL)
        risk_raw = fetch(cursor, RISK_BAND_SQL)
        cursor.execute(
            """
                SELECT r.recommendation, r.refusal_reasons, m.model_version, m.approval_state
                FROM strategy.scenario_runs r
                JOIN scoring.model_versions m USING (model_version)
                ORDER BY m.model_version
                """
        )
        runs = [
            {
                "model_version": row[2],
                "approval_state": row[3],
                "recommendation": row[0],
                "refusal_reasons": row[1],
            }
            for row in cursor.fetchall()
        ]

    if not monthly_raw:
        raise RuntimeError("analytics.fact_daily_strategy is empty; run `fraud_strategy.cli operate` first")

    monthly = monthly_rows(monthly_raw)
    vendor = vendor_comparison(monthly)

    monthly_columns = list(monthly[0].keys())
    write_table(output_dir, "fact_monthly_kpi", monthly_columns, [list(row.values()) for row in monthly])
    write_table(
        output_dir,
        "fact_channel_kpi",
        [
            "period",
            "model_version",
            "channel",
            "applications",
            "fraud_attempts",
            "fraud_caught",
            "good_customers_reviewed",
        ],
        [
            [
                row["month_label"],
                row["model_version"],
                row["channel_label"],
                int(row["applications"]),
                int(row["fraud_count"]),
                int(row["fraud_caught"]),
                int(row["good_customer_reviews"]),
            ]
            for row in channel_raw
        ],
    )
    write_table(
        output_dir,
        "fact_risk_band_kpi",
        ["period", "model_version", "risk_band", "applications", "fraud_attempts", "fraud_caught"],
        [
            [
                row["month_label"],
                row["model_version"],
                row["risk_band"],
                int(row["applications"]),
                int(row["fraud_count"]),
                int(row["fraud_caught"]),
            ]
            for row in risk_raw
        ],
    )
    write_table(
        output_dir,
        "fact_vendor_performance",
        list(vendor[0].keys()) if vendor else ["period"],
        [list(row.values()) for row in vendor],
    )

    pack = {
        "evidence_id": "m9-monthly-fraud-kpi-v1",
        "dataset_version": DATASET_VERSION,
        "code_sha": code_sha(),
        "source": "PostgreSQL Fraud Schema, analytics.fact_daily_strategy",
        "review_capacity": OPERATING_CAPACITY,
        "periods": sorted({row["period"] for row in monthly}),
        "monthly": monthly,
        "vendor_performance": vendor,
        "channel": [
            {
                "period": row["month_label"],
                "model_version": row["model_version"],
                "channel": row["channel_label"],
                "applications": int(row["applications"]),
                "fraud_attempts": int(row["fraud_count"]),
                "fraud_caught": int(row["fraud_caught"]),
                "good_customers_reviewed": int(row["good_customer_reviews"]),
            }
            for row in channel_raw
        ],
        "risk_bands": [
            {
                "period": row["month_label"],
                "model_version": row["model_version"],
                "risk_band": row["risk_band"],
                "applications": int(row["applications"]),
                "fraud_attempts": int(row["fraud_count"]),
                "fraud_caught": int(row["fraud_caught"]),
            }
            for row in risk_raw
        ],
        "scenario_runs": runs,
        "limitations": [
            "BAF is privacy-preserving synthetic account-opening data, not observed originations.",
            "Periods are relative BAF months labelled Period 0 to Period 7, not calendar months.",
            "`credit_risk_score` is an incumbent score proxy standing in for a third-party decision "
            "score. It is not a verified vendor product and its performance here is not a vendor SLA.",
            "Catch rate assumes review prevents the fraud it finds; review effectiveness and "
            "loss-given-fraud are not modelled, so every figure is an upper bound.",
            "No period in this pack authorises a policy. Both scenario runs carry the recorded refusal.",
            "Reviewer hit rate is a leading indicator, available within days, because a review confirms "
            "fraud at review time. Catch rate shares that numerator but divides by all fraud in the "
            "period including what slipped past review, so it is lagging by 30 to 90 days and longer. "
            "The most recent periods here will get worse as labels arrive, so the rise in attempt rate "
            "is a floor rather than a point estimate. See docs/label-latency.md.",
            "`capacity_overshoot` is the queue above the reviewer headcount the capacity implies. "
            "It is a property of cutting a tied score, not a modelling error: applications at the "
            "cutting value cannot be split, so a low-cardinality score overshoots by its tied block.",
        ],
    }
    (evidence_dir / "monthly_kpi.json").write_text(
        json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return pack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("FRAUD_DATABASE_URL", ""))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--evidence-dir", default=str(EVIDENCE_DIR))
    arguments = parser.parse_args()
    if not arguments.dsn:
        raise SystemExit("FRAUD_DATABASE_URL is required")

    pack = build(arguments.dsn, Path(arguments.output_dir), Path(arguments.evidence_dir))
    latest = pack["monthly"][-1]
    print(
        json.dumps(
            {
                "periods": len(pack["periods"]),
                "monthly_rows": len(pack["monthly"]),
                "latest_period": latest["period"],
                "latest_catch_rate": latest["catch_rate"],
                "vendor_rows": len(pack["vendor_performance"]),
                "recommendation": pack["scenario_runs"][0]["recommendation"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
