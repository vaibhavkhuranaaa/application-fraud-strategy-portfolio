from pathlib import Path

from fraud_strategy.database import migration_files


def test_postgres_migrations_define_all_governed_schemas() -> None:
    files = migration_files(Path("db/migrations"))
    assert [path.name for path in files] == ["001_fraud_schema.sql", "002_analytics.sql"]
    sql = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for schema in ("core", "scoring", "linking", "strategy", "analytics", "governance"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in sql
    assert "automatic_decline" not in sql
    assert "governance_referral" in sql
    assert "JOIN core.applications a ON a.application_id = q.application_id" in sql
