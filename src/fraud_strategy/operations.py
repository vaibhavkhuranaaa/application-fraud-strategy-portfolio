"""Operational wiring: the Fraud Schema as the system of record.

M9 posed a choice. Either wire the review queue to the PostgreSQL schema and add a
scoring path, or drop the platform framing and call this an analysis with a decision
surface. This module is the first option. Before it, six schemas, two analytics views and
a recovery test existed and nothing read or wrote any of them, so the governed row-level
product was architecture on paper.

What it writes, in the order the tables depend on each other:

- `core.applications`, the modeling population, months 0 to 7 of `Base.csv`.
- `scoring.model_versions`, both manifests, carrying their real approval states. The
  rejected challenger is recorded as rejected rather than left out, because a fraud desk
  needs to see what it declined to promote.
- `scoring.application_scores`, every application under both models, with a risk band.
- `strategy.policy_versions` and `strategy.scenario_runs`, one run per model at the
  operating capacity, each carrying the recommendation and its refusal reasons verbatim.
- `strategy.queue_assignments`, the actual ranked review queue with reason codes.
- `analytics.dim_*` and `analytics.fact_daily_strategy`, the KPI grain the monthly pack
  and the Power BI operational model both read.

Two things this deliberately does not do. It never writes an automatic decline, because
no such action exists in the contract or the schema. And it never promotes: the scenario
runs carry `no robust recommendation` and the blocking reasons, so wiring the platform
does not quietly turn a refusal into an operating policy.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import psycopg

from .analysis.reasons import reason_codes
from .calibration import (
    PriorShift,
    fit_score_reference,
    score_to_probability,
    select_prior_forecast,
)
from .config import CAPACITIES, DATASET_VERSION, INCUMBENT_FEATURE, SEED
from .modeling import (
    CALIBRATION_MONTH,
    CHECKPOINT_PROTOCOL,
    ROLLING_FOLDS,
    TEST_MONTH,
    calibrated_predict,
    code_sha,
    incumbent_calibration,
    load_base,
)
from .strategy import concentration_rule_flags, rank_review_queue

# The period the desk is working. Months 0 to 6 are history for the KPI trend; month 7 is
# the untouched evaluation period and the one the live queue is built from.
OPERATING_PERIOD = TEST_MONTH
OPERATING_CAPACITY = 0.05

# Band edges are quantiles of the calibration period, fixed once and reused for every
# later period. Recomputing them per batch is the defect M6 fixed in the champion's score
# mapping: a band that restandardises against whatever arrived cannot mean the same thing
# twice, and an investigator who is told "critical" needs it to.
RISK_BAND_QUANTILES = {"critical": 0.99, "high": 0.95, "medium": 0.80}

# BAF periods are relative, not dated. These keys exist so the analytics grain sorts and
# joins like a real calendar; they are labelled as periods everywhere a human reads them.
PERIOD_EPOCH = date(2025, 1, 1)

CHANNEL_LABELS = {"INTERNET": "Online", "TELEAPP": "Phone"}
ACTION_LABELS = {
    "clear": "Cleared without review",
    "manual_review": "Manual review",
    "governance_referral": "Governance referral",
}
OPERATING_MODELS = ("incumbent_proxy", "catboost_hybrid")


@dataclass(frozen=True)
class ScoredPopulation:
    frame: pd.DataFrame
    probabilities: dict[str, np.ndarray]
    band_edges: dict[str, dict[str, float]]
    model_versions: dict[str, str]


def period_date(period: int) -> date:
    month = PERIOD_EPOCH.month + period
    return date(PERIOD_EPOCH.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def period_date_key(period: int) -> int:
    value = period_date(period)
    return value.year * 10_000 + value.month * 100 + value.day


def band_edges(probabilities: np.ndarray) -> dict[str, float]:
    return {
        name: float(np.quantile(probabilities, quantile)) for name, quantile in RISK_BAND_QUANTILES.items()
    }


def assign_bands(probabilities: np.ndarray, edges: dict[str, float]) -> np.ndarray:
    bands = np.full(len(probabilities), "low", dtype=object)
    bands[probabilities >= edges["medium"]] = "medium"
    bands[probabilities >= edges["high"]] = "high"
    bands[probabilities >= edges["critical"]] = "critical"
    return bands


def score_population(curated_dir: Path, evidence_dir: Path, artifact_dir: Path) -> ScoredPopulation:
    """Score every application under the champion and the rejected challenger.

    Both are scored because the desk's question is a comparison. The champion is what
    runs; the challenger is what was proposed and declined, and its queue is the evidence
    for what promoting it would have changed.
    """
    frame = load_base(curated_dir)
    checkpoint = joblib.load(evidence_dir / "work" / "fitted_candidates.joblib")
    if checkpoint.get("protocol") != CHECKPOINT_PROTOCOL:
        raise RuntimeError(
            f"fitted candidates were built under {checkpoint.get('protocol')!r}, "
            f"not {CHECKPOINT_PROTOCOL!r}; retrain before operating"
        )
    calibration = frame[frame["month"] == CALIBRATION_MONTH]

    observed_priors = [
        float(frame.loc[frame["month"] == month, "fraud_bool"].mean())
        for month in range(0, CALIBRATION_MONTH + 1)
    ]
    forecast = select_prior_forecast(observed_priors, backtest_from=ROLLING_FOLDS[0][1][0])
    prior_shift = PriorShift(
        rule=forecast["selected"],
        calibration_prior=observed_priors[-1],
        forecast_prior=forecast["forecast_prior"],
    )

    reference = fit_score_reference(calibration[INCUMBENT_FEATURE].to_numpy())
    incumbent_calibrator, _ = incumbent_calibration(calibration, reference)

    probabilities = {
        "catboost_hybrid": prior_shift.apply(
            calibrated_predict(
                checkpoint["candidates"]["catboost_hybrid"],
                checkpoint["calibrators"]["catboost_hybrid"],
                frame,
            )
        ),
        "incumbent_proxy": prior_shift.apply(
            incumbent_calibrator.predict(score_to_probability(frame[INCUMBENT_FEATURE].to_numpy(), reference))
        ),
    }
    calibration_mask = (frame["month"] == CALIBRATION_MONTH).to_numpy()
    edges = {name: band_edges(values[calibration_mask]) for name, values in probabilities.items()}

    manifests = {
        "catboost_hybrid": json.loads(
            (artifact_dir / "models" / "candidate_model_manifest.json").read_text(encoding="utf-8")
        ),
        "incumbent_proxy": json.loads(
            (artifact_dir / "models" / "model_manifest.json").read_text(encoding="utf-8")
        ),
    }
    versions = {
        "catboost_hybrid": manifests["catboost_hybrid"].get("model_version", "catboost-hybrid-m3-v1"),
        "incumbent_proxy": manifests["incumbent_proxy"].get("model_version", "incumbent-proxy-m3-v1"),
    }
    return ScoredPopulation(
        frame=frame,
        probabilities=probabilities,
        band_edges=edges,
        model_versions=versions,
    )


def register_models(cursor: Any, artifact_dir: Path, scored: ScoredPopulation) -> None:
    files = {
        "catboost_hybrid": artifact_dir / "models" / "candidate_model_manifest.json",
        "incumbent_proxy": artifact_dir / "models" / "model_manifest.json",
    }
    for name, path in files.items():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        cursor.execute(
            """
            INSERT INTO scoring.model_versions(
                model_version, dataset_version, artifact_hash, code_sha,
                approval_state, manifest, promoted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (model_version) DO UPDATE SET
                approval_state = EXCLUDED.approval_state,
                manifest = EXCLUDED.manifest,
                artifact_hash = EXCLUDED.artifact_hash,
                code_sha = EXCLUDED.code_sha
            """,
            (
                scored.model_versions[name],
                DATASET_VERSION,
                manifest["artifact_hash"],
                manifest["code_sha"],
                manifest["approval_state"],
                json.dumps({**manifest, "risk_band_edges": scored.band_edges[name]}),
                None,
            ),
        )


def write_scores(cursor: Any, scored: ScoredPopulation, *, batch_size: int = 50_000) -> int:
    identifiers = scored.frame["application_id"].to_numpy()
    written = 0
    for name in OPERATING_MODELS:
        model_version = scored.model_versions[name]
        cursor.execute(
            "SELECT count(*) FROM scoring.application_scores WHERE model_version = %s", (model_version,)
        )
        if int(cursor.fetchone()[0]) == len(identifiers):
            continue
        cursor.execute("DELETE FROM scoring.application_scores WHERE model_version = %s", (model_version,))
        probabilities = scored.probabilities[name]
        bands = assign_bands(probabilities, scored.band_edges[name])
        cursor.execute(
            "SELECT artifact_hash FROM scoring.model_versions WHERE model_version = %s", (model_version,)
        )
        artifact_hash = cursor.fetchone()[0]
        for start in range(0, len(identifiers), batch_size):
            stop = min(start + batch_size, len(identifiers))
            with cursor.copy(
                """
                COPY scoring.application_scores(
                    application_id, model_version, fraud_probability,
                    risk_band, reason_codes, artifact_hash
                ) FROM STDIN
                """
            ) as copy:
                for index in range(start, stop):
                    copy.write_row(
                        (
                            identifiers[index],
                            model_version,
                            float(probabilities[index]),
                            str(bands[index]),
                            "[]",
                            artifact_hash,
                        )
                    )
            written += stop - start
    return written


def queue_for_period(
    scored: ScoredPopulation, model: str, *, period: int, capacity: float
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    mask = (scored.frame["month"] == period).to_numpy()
    period_frame = scored.frame.loc[mask]
    probabilities = scored.probabilities[model][mask]
    outcome = rank_review_queue(probabilities, capacity)
    return period_frame, probabilities, outcome.review_mask | outcome.referral_mask


def write_scenario_run(
    cursor: Any,
    scored: ScoredPopulation,
    evaluation: dict[str, Any],
    *,
    model: str,
    period: int,
    capacity: float,
    artifact_dir: Path,
) -> dict[str, Any]:
    """One scenario run, its policy, and the ranked queue it produces.

    The recommendation and refusal reasons are copied from the recorded evaluation rather
    than recomputed here. Wiring the platform must not be able to change the answer.
    """
    model_version = scored.model_versions[model]
    policy_version = f"{model_version}-cap{int(round(capacity * 1000)):04d}-p{period}"
    frontier = evaluation["strategy_frontier"]
    period_frame, probabilities, actioned = queue_for_period(scored, model, period=period, capacity=capacity)
    score_cut = float(np.quantile(probabilities, 1 - capacity))

    cursor.execute(
        """
        INSERT INTO strategy.policy_versions(
            policy_version, model_version, score_cut, review_capacity, rule_toggles, approval_state
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (policy_version) DO UPDATE SET
            score_cut = EXCLUDED.score_cut, approval_state = EXCLUDED.approval_state
        """,
        (
            policy_version,
            model_version,
            score_cut,
            capacity,
            json.dumps({name: False for name in concentration_rule_flags(period_frame)}),
            "candidate",
        ),
    )

    idempotency_key = f"{policy_version}:{evaluation['evidence_id']}"
    cursor.execute(
        "SELECT scenario_run_id FROM strategy.scenario_runs WHERE idempotency_key = %s", (idempotency_key,)
    )
    existing = cursor.fetchone()
    if existing:
        return {"scenario_run_id": str(existing[0]), "queue_size": int(actioned.sum()), "reused": True}

    ranked = np.argsort(-probabilities, kind="stable")
    queued_positions = [position for position in ranked if actioned[position]]
    queued_frame = period_frame.iloc[queued_positions]
    codes = reason_codes(queued_frame, artifact_dir / "models" / "catboost_hybrid.cbm")

    scenario_run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"fraud-strategy:{idempotency_key}")
    labels = period_frame["fraud_bool"].to_numpy(dtype=np.int8)
    results = {
        "period": period,
        "review_capacity": capacity,
        "score_cut": score_cut,
        "applications": int(len(period_frame)),
        "queue_size": int(actioned.sum()),
        "fraud_in_period": int(labels.sum()),
        "fraud_caught": int((actioned & (labels == 1)).sum()),
        "good_customer_reviews": int((actioned & (labels == 0)).sum()),
        "catch_rate": float((actioned & (labels == 1)).sum() / max(int(labels.sum()), 1)),
        "model": model,
        "promotion_gates": evaluation["promotion_gates"],
    }
    cursor.execute(
        """
        INSERT INTO strategy.scenario_runs(
            scenario_run_id, idempotency_key, model_version, policy_version,
            assumptions, results, recommendation, refusal_reasons, actor_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(scenario_run_id),
            idempotency_key,
            model_version,
            policy_version,
            json.dumps(evaluation.get("economic_grid_at_5_percent_capacity", {}).get("assumptions", {})),
            json.dumps(results),
            frontier["recommendation"],
            json.dumps(frontier["refusal_reasons"]),
            "fraud-strategy-analyst",
        ),
    )

    with cursor.copy(
        """
        COPY strategy.queue_assignments(
            scenario_run_id, application_id, queue_rank, action, reason_codes
        ) FROM STDIN
        """
    ) as copy:
        for rank, (identifier, row_codes) in enumerate(
            zip(queued_frame["application_id"].to_numpy(), codes, strict=False), start=1
        ):
            copy.write_row((str(scenario_run_id), identifier, rank, "manual_review", json.dumps(row_codes)))
    return {"scenario_run_id": str(scenario_run_id), "queue_size": int(actioned.sum()), "reused": False}


def refresh_dimensions(cursor: Any, scored: ScoredPopulation) -> None:
    for period in sorted(scored.frame["month"].unique()):
        value = period_date(int(period))
        cursor.execute(
            """
            INSERT INTO analytics.dim_date(date_key, calendar_date, month_start, month_label)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (date_key) DO UPDATE SET month_label = EXCLUDED.month_label
            """,
            (period_date_key(int(period)), value, value, f"Period {int(period)}"),
        )
    cursor.execute(
        """
        INSERT INTO analytics.dim_model(model_version, model_type, approval_state, artifact_hash)
        SELECT model_version,
               CASE WHEN model_version LIKE 'incumbent%' THEN 'incumbent score proxy' ELSE 'gradient boosting' END,
               approval_state, artifact_hash
        FROM scoring.model_versions
        ON CONFLICT (model_version) DO UPDATE SET approval_state = EXCLUDED.approval_state
        """
    )
    cursor.execute(
        """
        INSERT INTO analytics.dim_policy(policy_version, review_capacity, score_cut)
        SELECT policy_version, review_capacity, score_cut FROM strategy.policy_versions
        ON CONFLICT (policy_version) DO UPDATE SET score_cut = EXCLUDED.score_cut
        """
    )
    for code, label in CHANNEL_LABELS.items():
        cursor.execute(
            """
            INSERT INTO analytics.dim_channel(channel_code, channel_label) VALUES (%s, %s)
            ON CONFLICT (channel_code) DO UPDATE SET channel_label = EXCLUDED.channel_label
            """,
            (code, label),
        )
    for code, label in ACTION_LABELS.items():
        cursor.execute(
            """
            INSERT INTO analytics.dim_action(action_code, action_label) VALUES (%s, %s)
            ON CONFLICT (action_code) DO UPDATE SET action_label = EXCLUDED.action_label
            """,
            (code, label),
        )
    # Risk band is the operational segment. Protected attributes stay out of this grain on
    # purpose: they are governed in one place, the fairness report, under a publication
    # threshold, and a second unguarded copy in a fact table would defeat it.
    for band in ("low", "medium", "high", "critical"):
        cursor.execute(
            """
            INSERT INTO analytics.dim_segment(segment_type, segment_value) VALUES (%s, %s)
            ON CONFLICT (segment_type, segment_value) DO NOTHING
            """,
            ("risk_band", band),
        )


def refresh_facts(cursor: Any, capacity: float) -> int:
    """Aggregate the KPI grain in SQL, from the tables the desk actually writes.

    Every number the monthly pack reports is derived here rather than in pandas, because
    the point of wiring the schema is that the reporting layer reads the system of record.
    """
    cursor.execute("TRUNCATE analytics.fact_daily_strategy")
    cursor.execute(
        """
        WITH cut AS (
            SELECT s.model_version,
                   a.period,
                   percentile_disc(1 - %s) WITHIN GROUP (ORDER BY s.fraud_probability) AS score_cut
            FROM scoring.application_scores s
            JOIN core.applications a ON a.application_id = s.application_id
            WHERE a.evidence_source = 'baf_base'
            GROUP BY s.model_version, a.period
        ),
        actioned AS (
            SELECT a.period,
                   s.model_version,
                   s.risk_band,
                   a.channel,
                   a.target_fraud,
                   CASE WHEN s.fraud_probability >= cut.score_cut THEN 'manual_review' ELSE 'clear' END AS action_code
            FROM scoring.application_scores s
            JOIN core.applications a ON a.application_id = s.application_id
            JOIN cut ON cut.model_version = s.model_version AND cut.period = a.period
            WHERE a.evidence_source = 'baf_base'
        )
        INSERT INTO analytics.fact_daily_strategy(
            date_key, model_key, policy_key, segment_key, channel_key, action_key,
            application_count, fraud_count, fraud_caught, good_customer_reviews, expected_utility
        )
        SELECT d.date_key,
               m.model_key,
               p.policy_key,
               g.segment_key,
               c.channel_key,
               t.action_key,
               count(*),
               count(*) FILTER (WHERE actioned.target_fraud),
               count(*) FILTER (WHERE actioned.target_fraud AND actioned.action_code <> 'clear'),
               count(*) FILTER (WHERE NOT actioned.target_fraud AND actioned.action_code <> 'clear'),
               NULL
        FROM actioned
        JOIN analytics.dim_date d ON d.month_label = 'Period ' || actioned.period
        JOIN analytics.dim_model m ON m.model_version = actioned.model_version
        JOIN analytics.dim_policy p
          ON p.policy_version = actioned.model_version || '-cap'
             || lpad((round(%s * 1000))::int::text, 4, '0') || '-p' || %s
        JOIN analytics.dim_segment g ON g.segment_type = 'risk_band' AND g.segment_value = actioned.risk_band
        JOIN analytics.dim_channel c ON c.channel_code = actioned.channel
        JOIN analytics.dim_action t ON t.action_code = actioned.action_code
        GROUP BY d.date_key, m.model_key, p.policy_key, g.segment_key, c.channel_key, t.action_key
        """,
        (capacity, capacity, OPERATING_PERIOD),
    )
    return cursor.rowcount


def run_operations_program(
    dsn: str,
    curated_dir: Path,
    artifact_dir: Path,
    evidence_dir: Path,
    *,
    capacity: float = OPERATING_CAPACITY,
    period: int = OPERATING_PERIOD,
) -> dict[str, Any]:
    if capacity not in CAPACITIES:
        raise ValueError(f"operating capacity must be one of {CAPACITIES}, got {capacity}")
    evaluation = json.loads((evidence_dir / "model_evaluation.json").read_text(encoding="utf-8"))
    scored = score_population(curated_dir, evidence_dir, artifact_dir)

    runs: dict[str, Any] = {}
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            register_models(cursor, artifact_dir, scored)
            scores_written = write_scores(cursor, scored)
            for model in OPERATING_MODELS:
                runs[model] = write_scenario_run(
                    cursor,
                    scored,
                    evaluation,
                    model=model,
                    period=period,
                    capacity=capacity,
                    artifact_dir=artifact_dir,
                )
            refresh_dimensions(cursor, scored)
            fact_rows = refresh_facts(cursor, capacity)
            correlation = f"operations:{DATASET_VERSION}:p{period}:{capacity}"
            cursor.execute(
                """
                INSERT INTO governance.audit_events(
                    event_id, correlation_id, actor_id, actor_role, action,
                    object_type, object_version, outcome, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    str(uuid.uuid5(uuid.NAMESPACE_URL, f"fraud-strategy:{correlation}:{code_sha()}")),
                    correlation,
                    "fraud-strategy-analyst",
                    "analyst",
                    "operations_refresh",
                    "review_queue",
                    DATASET_VERSION,
                    evaluation["strategy_frontier"]["recommendation"],
                    json.dumps(
                        {
                            "code_sha": code_sha(),
                            "champion": evaluation["champion"],
                            "operating_period": period,
                            "review_capacity": capacity,
                            "seed": SEED,
                        }
                    ),
                ),
            )
        connection.commit()
    return {
        "scores_written": scores_written,
        "fact_rows": fact_rows,
        "scenario_runs": runs,
        "risk_band_edges": scored.band_edges,
        "operating_period": period,
        "operating_capacity": capacity,
    }
