"""Deterministic validation and typed Parquet curation for the BAF suite."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    BASE_COLUMNS,
    BINARY_COLUMNS,
    DATASET_VERSION,
    MISSING_INDICATORS,
    NEGATIVE_IS_MISSING,
    SENTINEL_MINUS_ONE,
    SOURCE_FILES,
)
from .io import sha256_file, stable_id, write_json


class DataContractError(ValueError):
    """Raised when source data violates the approved immutable contract."""


def expected_columns(file_name: str) -> list[str]:
    columns = list(BASE_COLUMNS)
    if file_name in {"Variant III.csv", "Variant V.csv"}:
        columns.extend(["x1", "x2"])
    return columns


def validate_source(path: Path, *, verify_checksum: bool = True) -> dict[str, Any]:
    if path.name not in SOURCE_FILES:
        raise DataContractError(f"unapproved source file: {path.name}")
    contract = SOURCE_FILES[path.name]
    if not path.is_file():
        raise DataContractError(f"missing source file: {path}")
    if verify_checksum:
        observed_hash = sha256_file(path)
        if observed_hash != contract["sha256"]:
            raise DataContractError(f"checksum mismatch for {path.name}: {observed_hash}")
    else:
        observed_hash = "not-recomputed"

    header = pd.read_csv(path, nrows=0).columns.tolist()
    if header != expected_columns(path.name):
        raise DataContractError(f"schema mismatch for {path.name}: {header}")

    rows = 0
    positives = 0
    months: set[int] = set()
    for chunk in pd.read_csv(path, usecols=["fraud_bool", "month"], chunksize=250_000):
        rows += len(chunk)
        target_values = set(chunk["fraud_bool"].dropna().astype(int).unique())
        if not target_values.issubset({0, 1}):
            raise DataContractError(f"non-binary target in {path.name}: {sorted(target_values)}")
        positives += int(chunk["fraud_bool"].sum())
        months.update(int(value) for value in chunk["month"].unique())
    if rows != contract["rows"]:
        raise DataContractError(f"row-count mismatch for {path.name}: {rows}")
    if months != set(range(8)):
        raise DataContractError(f"month coverage mismatch for {path.name}: {sorted(months)}")
    prevalence = positives / rows
    if not 0.005 <= prevalence <= 0.03:
        raise DataContractError(f"target prevalence outside approved bounds for {path.name}: {prevalence}")
    return {
        "file_name": path.name,
        "sha256": observed_hash,
        "rows": rows,
        "columns": len(header),
        "positive_count": positives,
        "prevalence": prevalence,
        "months": sorted(months),
    }


def normalize_frame(frame: pd.DataFrame, file_name: str) -> pd.DataFrame:
    if frame.columns.tolist() != expected_columns(file_name):
        raise DataContractError(f"cannot normalize unexpected schema for {file_name}")
    result = frame.copy()
    for column in SENTINEL_MINUS_ONE:
        missing = result[column].eq(-1)
        result[f"{column}__missing"] = missing.astype("int8")
        result[column] = result[column].mask(missing).astype("float64")
    for column in NEGATIVE_IS_MISSING:
        missing = result[column].lt(0)
        result[f"{column}__missing"] = missing.astype("int8")
        result[column] = result[column].mask(missing).astype("float64")
    for column in BINARY_COLUMNS:
        result[column] = result[column].astype("int8")
    result["month"] = result["month"].astype("int8")
    for column in ["payment_type", "employment_status", "housing_status", "source", "device_os"]:
        result[column] = result[column].astype("category")
    return result


def curate_source(
    source_path: Path,
    destination_dir: Path,
    *,
    verify_checksum: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    validation = validate_source(source_path, verify_checksum=verify_checksum)
    frame = pd.read_csv(source_path)
    frame = normalize_frame(frame, source_path.name)

    identifiers = np.fromiter(
        (stable_id(DATASET_VERSION, source_path.name, row_number) for row_number in range(len(frame))),
        dtype="U32",
        count=len(frame),
    )
    if len(np.unique(identifiers)) != len(frame):
        raise DataContractError(f"duplicate generated application IDs in {source_path.name}")
    frame.insert(0, "application_id", identifiers)
    frame.insert(1, "dataset_version", DATASET_VERSION)
    frame.insert(2, "evidence_source", SOURCE_FILES[source_path.name]["evidence_source"])

    destination_dir.mkdir(parents=True, exist_ok=True)
    output_path = destination_dir / f"{source_path.stem.lower().replace(' ', '_')}.parquet"
    frame.to_parquet(output_path, engine="pyarrow", compression="zstd", index=False)
    observed = pd.read_parquet(
        output_path,
        columns=[
            "application_id",
            "fraud_bool",
            "month",
            "dataset_version",
            "evidence_source",
            *MISSING_INDICATORS,
        ],
    )
    if len(observed) != validation["rows"] or not observed["application_id"].is_unique:
        raise DataContractError(f"curated artifact integrity failure: {output_path}")
    if observed["fraud_bool"].sum() != validation["positive_count"]:
        raise DataContractError(f"target changed during curation: {output_path}")
    return {
        **validation,
        "evidence_source": SOURCE_FILES[source_path.name]["evidence_source"],
        "curated_path": output_path.as_posix(),
        "curated_sha256": sha256_file(output_path),
        "curated_columns": len(frame.columns),
        "missing_indicators": MISSING_INDICATORS,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def curate_suite(
    raw_dir: Path,
    curated_dir: Path,
    *,
    verify_checksum: bool = True,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    artifacts = [
        curate_source(raw_dir / file_name, curated_dir, verify_checksum=verify_checksum)
        for file_name in SOURCE_FILES
    ]
    manifest = {
        "dataset_version": DATASET_VERSION,
        "contract": "M2-approved BAF Base modeling / Variants I-V stress-test contract",
        "files": artifacts,
        "total_rows": sum(item["rows"] for item in artifacts),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(manifest_path or curated_dir / "manifest.json", manifest)
    return manifest
