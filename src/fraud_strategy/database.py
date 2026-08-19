"""PostgreSQL migration runner with immutable script hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import pyarrow.parquet as pq

from .config import DATASET_VERSION, HYBRID_FEATURES


def migration_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise FileNotFoundError(f"no migrations found in {directory}")
    return files


def apply_migrations(dsn: str, directory: Path = Path("db/migrations")) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as connection:
        for path in migration_files(directory):
            version = path.name.split("_", 1)[0]
            sql = path.read_text(encoding="utf-8")
            script_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS governance")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS governance.schema_migrations (
                        version text PRIMARY KEY,
                        applied_at timestamptz NOT NULL DEFAULT now(),
                        script_sha256 text NOT NULL CHECK (length(script_sha256) = 64)
                    )
                    """
                )
                cursor.execute(
                    "SELECT script_sha256 FROM governance.schema_migrations WHERE version = %s", (version,)
                )
                existing = cursor.fetchone()
                if existing:
                    if existing[0] != script_hash:
                        raise RuntimeError(f"applied migration {version} changed on disk")
                    continue
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO governance.schema_migrations(version, script_sha256) VALUES (%s, %s)",
                    (version, script_hash),
                )
                applied.append(version)
    return applied


def register_dataset_version(cursor: Any, manifest: dict[str, Any]) -> None:
    cursor.execute(
        """
        INSERT INTO core.dataset_versions(
            dataset_version, source_name, source_sha256, acquired_at,
            row_count, evidence_source, manifest
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (dataset_version) DO UPDATE SET manifest = EXCLUDED.manifest
        """,
        (
            DATASET_VERSION,
            "Bank Account Fraud suite",
            manifest["files"][0]["sha256"],
            "2026-08-05",
            int(manifest["total_rows"]),
            "baf_suite",
            json.dumps(manifest),
        ),
    )


def copy_artifact(cursor: Any, artifact: dict[str, Any], *, batch_size: int) -> int:
    parquet = pq.ParquetFile(artifact["curated_path"])
    selected_columns = list(
        dict.fromkeys(
            ["application_id", "month", "source", "evidence_source", "fraud_bool", *HYBRID_FEATURES]
        )
    )
    loaded = 0
    for record_batch in parquet.iter_batches(batch_size=batch_size, columns=selected_columns):
        frame = record_batch.to_pandas()
        with cursor.copy(
            """
            COPY core.applications(
                application_id, dataset_version, period, channel,
                evidence_source, approved_features, target_fraud
            ) FROM STDIN
            """
        ) as copy:
            for row in frame.itertuples(index=False):
                values = row._asdict()
                approved = {
                    feature: (None if pd.isna(values.get(feature)) else values.get(feature))
                    for feature in HYBRID_FEATURES
                }
                copy.write_row(
                    (
                        values["application_id"],
                        DATASET_VERSION,
                        int(values["month"]),
                        values["source"],
                        values["evidence_source"],
                        json.dumps(approved, default=str),
                        bool(values["fraud_bool"]),
                    )
                )
        loaded += len(frame)
    return loaded


def load_applications(
    dsn: str,
    manifest: dict[str, Any],
    *,
    evidence_sources: list[str] | None = None,
    batch_size: int = 20_000,
) -> int:
    """Load curated application rows, guarding each evidence source separately.

    The guard is per source rather than one count over the whole table. Operational use
    needs only the modeling population, `baf_base`, and a single count would read that
    perfectly good load as a corrupt partial load of the six-file suite and fail closed on
    it. Per source, each file is either absent, complete, or genuinely torn.
    """
    artifacts = [
        artifact
        for artifact in manifest["files"]
        if evidence_sources is None or artifact["evidence_source"] in evidence_sources
    ]
    if not artifacts:
        raise ValueError(f"no curated artifact matches evidence sources {evidence_sources}")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            register_dataset_version(cursor, manifest)
            loaded = 0
            for artifact in artifacts:
                expected_rows = int(artifact["rows"])
                cursor.execute(
                    """
                    SELECT count(*) FROM core.applications
                    WHERE dataset_version = %s AND evidence_source = %s
                    """,
                    (DATASET_VERSION, artifact["evidence_source"]),
                )
                existing_rows = int(cursor.fetchone()[0])
                if existing_rows == expected_rows:
                    continue
                if existing_rows:
                    raise RuntimeError(
                        f"partial load of {artifact['evidence_source']} found "
                        f"({existing_rows}/{expected_rows}); fail closed and investigate"
                    )
                copied = copy_artifact(cursor, artifact, batch_size=batch_size)
                if copied != expected_rows:
                    raise RuntimeError(
                        f"loaded {copied} rows for {artifact['evidence_source']}, expected {expected_rows}"
                    )
                loaded += copied
        connection.commit()
    return loaded


def load_curated_suite(dsn: str, manifest: dict[str, Any], *, batch_size: int = 20_000) -> int:
    """Load every curated artifact. Kept as the name the M3 migrate command calls."""
    return load_applications(dsn, manifest, batch_size=batch_size)
