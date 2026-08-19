"""Command-line interface for the portable M3 worker image."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from .config import (
    BASE_SOURCE,
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_CURATED_DIR,
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_RAW_DIR,
)
from .data import curate_suite
from .database import apply_migrations, load_applications, load_curated_suite
from .io import write_json
from .linking import run_linking_program
from .modeling import run_model_program
from .operations import OPERATING_CAPACITY, OPERATING_PERIOD, run_operations_program
from .suspects import run_suspect_report

app = typer.Typer(no_args_is_help=True, help="Governed application-fraud M3 worker commands.")


@app.command("curate")
def curate_command(
    raw_dir: Path = typer.Option(DEFAULT_RAW_DIR),
    curated_dir: Path = typer.Option(DEFAULT_CURATED_DIR),
    verify_checksum: bool = typer.Option(True),
) -> None:
    manifest = curate_suite(raw_dir, curated_dir, verify_checksum=verify_checksum)
    typer.echo(json.dumps({"dataset_version": manifest["dataset_version"], "rows": manifest["total_rows"]}))


@app.command("train")
def train_command(
    curated_dir: Path = typer.Option(DEFAULT_CURATED_DIR),
    artifact_dir: Path = typer.Option(DEFAULT_ARTIFACT_DIR),
    evidence_dir: Path = typer.Option(DEFAULT_EVIDENCE_DIR),
    trials: int = typer.Option(6, min=2, max=30),
    bootstrap_resamples: int = typer.Option(1_000, min=100, max=5_000),
) -> None:
    result = run_model_program(
        curated_dir,
        artifact_dir,
        evidence_dir,
        trials=trials,
        bootstrap_resamples=bootstrap_resamples,
    )
    typer.echo(json.dumps({"champion": result["champion"], "gates": result["promotion_gates"]}))


def hmac_key() -> bytes:
    value = os.environ.get("FRAUD_LINK_HMAC_KEY", "")
    if len(value.encode()) < 16:
        raise typer.BadParameter("FRAUD_LINK_HMAC_KEY must be set to at least 16 bytes")
    return value.encode()


@app.command("link-evaluate")
def link_evaluate_command(
    evidence_dir: Path = typer.Option(DEFAULT_EVIDENCE_DIR),
    applications: int = typer.Option(50_000, min=3_000),
) -> None:
    result = run_linking_program(hmac_key(), evidence_dir, applications=applications)
    typer.echo(json.dumps({"all_gates_pass": result["all_gates_pass"], "summary": result["summary"]}))


@app.command("suspect-report")
def suspect_report_command(
    evidence_dir: Path = typer.Option(DEFAULT_EVIDENCE_DIR),
    applications: int = typer.Option(50_000, min=3_000),
    days: int = typer.Option(20, min=1, max=90),
) -> None:
    """Daily suspect-application report from linking analysis, on the fixture only."""
    result = run_suspect_report(hmac_key(), evidence_dir, applications=applications, days=days)
    typer.echo(json.dumps({"totals": result["totals"], "validation": result["validation"]}))


@app.command("migrate")
def migrate_command(
    dsn: str = typer.Option(..., envvar="FRAUD_DATABASE_URL"),
    load_data: bool = typer.Option(False, help="Load the curated six-file suite after migrations."),
    manifest_path: Path = typer.Option(DEFAULT_CURATED_DIR / "manifest.json"),
) -> None:
    applied = apply_migrations(dsn)
    loaded = 0
    if load_data:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        loaded = load_curated_suite(dsn, manifest)
    typer.echo(json.dumps({"migrations_applied": applied, "rows_loaded": loaded}))


@app.command("operate")
def operate_command(
    dsn: str = typer.Option(..., envvar="FRAUD_DATABASE_URL"),
    curated_dir: Path = typer.Option(DEFAULT_CURATED_DIR),
    artifact_dir: Path = typer.Option(DEFAULT_ARTIFACT_DIR),
    evidence_dir: Path = typer.Option(DEFAULT_EVIDENCE_DIR),
    manifest_path: Path = typer.Option(DEFAULT_CURATED_DIR / "manifest.json"),
    capacity: float = typer.Option(OPERATING_CAPACITY),
    period: int = typer.Option(OPERATING_PERIOD, min=0, max=7),
    load_population: bool = typer.Option(True, help="Load the modeling population before scoring."),
) -> None:
    """Score the population, open the review queue, and refresh the KPI grain."""
    apply_migrations(dsn)
    loaded = 0
    if load_population:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        loaded = load_applications(dsn, manifest, evidence_sources=[BASE_SOURCE])
    result = run_operations_program(
        dsn, curated_dir, artifact_dir, evidence_dir, capacity=capacity, period=period
    )
    typer.echo(json.dumps({"applications_loaded": loaded, **result}))


@app.command("run-m3")
def run_m3_command(
    raw_dir: Path = typer.Option(DEFAULT_RAW_DIR),
    curated_dir: Path = typer.Option(DEFAULT_CURATED_DIR),
    artifact_dir: Path = typer.Option(DEFAULT_ARTIFACT_DIR),
    evidence_dir: Path = typer.Option(DEFAULT_EVIDENCE_DIR),
    trials: int = typer.Option(6, min=2, max=30),
    bootstrap_resamples: int = typer.Option(1_000, min=100, max=5_000),
) -> None:
    manifest = curate_suite(raw_dir, curated_dir, verify_checksum=True)
    write_json(evidence_dir / "data_curation.json", manifest)
    model = run_model_program(
        curated_dir,
        artifact_dir,
        evidence_dir,
        trials=trials,
        bootstrap_resamples=bootstrap_resamples,
    )
    linking = run_linking_program(hmac_key(), evidence_dir)
    summary = {
        "dataset_rows": manifest["total_rows"],
        "model_champion": model["champion"],
        "model_promotion_gates": model["promotion_gates"],
        "linking_gates": linking["gates"],
        "strategy_recommendation": model["strategy_frontier"]["recommendation"],
    }
    write_json(evidence_dir / "m3_summary.json", summary)
    typer.echo(json.dumps(summary))


if __name__ == "__main__":
    app()
