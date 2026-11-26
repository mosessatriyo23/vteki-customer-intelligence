"""Verify migration 0027 upgrade and rollback against a disposable PostgreSQL DB."""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DATABASE_NAME = "vteki_prediction_usage_rollback_fixture"
BASE_REVISION = "0026_campaign_contact_measurement_status"
USAGE_COLUMNS = {
    "usage_approved",
    "usage_decided_by",
    "usage_decided_at",
    "usage_note",
    "model_author",
}


def migration_env(database_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["MIGRATION_DATABASE_URL"] = database_url
    return env


def run_alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        check=True,
        env=migration_env(database_url),
    )


def get_usage_columns(connection) -> set[str]:
    return (
        set(
            connection.execute(
                text(
                    """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'ml'
                  AND table_name = 'prediction_review_runs'
                """
                )
            ).scalars()
        )
        & USAGE_COLUMNS
    )


def main() -> None:
    if os.getenv("VTEKI_ALLOW_TEST_DATABASE_RESET") != "1":
        raise SystemExit(
            "Set VTEKI_ALLOW_TEST_DATABASE_RESET=1 to create and drop the "
            "dedicated migration test database."
        )
    admin_url_value = os.getenv("VTEKI_TEST_POSTGRES_ADMIN_URL")
    if not admin_url_value:
        raise SystemExit("VTEKI_TEST_POSTGRES_ADMIN_URL is required.")

    admin_url = make_url(admin_url_value)
    if admin_url.get_backend_name() != "postgresql":
        raise SystemExit("Migration 0027 upgrade/rollback requires PostgreSQL.")
    database_url = admin_url.set(database=DATABASE_NAME).render_as_string(
        hide_password=False
    )
    admin_conninfo = admin_url.set(
        drivername="postgresql", database="postgres"
    ).render_as_string(hide_password=False)

    with psycopg.connect(admin_conninfo, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(DATABASE_NAME)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE_NAME))
        )

    engine = None
    try:
        run_alembic(database_url, "upgrade", BASE_REVISION)
        engine = create_engine(database_url)
        with engine.begin() as connection:
            legacy_run_id = connection.execute(
                text(
                    """
                    INSERT INTO ml.prediction_review_runs (
                        model_version, feature_set_version, label_version,
                        prediction_type, producer_version, manifest_hash,
                        record_count, review_status, manifest, submitted_by
                    ) VALUES (
                        'rollback-fixture-v1', 'feature-v1', 'label-v1',
                        'CHURN', 'producer-v1', 'fixture-hash',
                        1, 'reviewed', '{}'::jsonb, 10
                    )
                    RETURNING id
                    """
                )
            ).scalar_one()
        run_alembic(database_url, "upgrade", "head")

        with engine.begin() as connection:
            assert get_usage_columns(connection) == USAGE_COLUMNS
            untouched = connection.execute(
                text(
                    """
                    SELECT usage_approved, usage_decided_by, usage_decided_at,
                           usage_note, model_author
                    FROM ml.prediction_review_runs
                    WHERE id = :run_id
                    """
                ),
                {"run_id": legacy_run_id},
            ).one()
            assert tuple(untouched) == (None, None, None, None, None)
            connection.execute(
                text(
                    """
                    UPDATE ml.prediction_review_runs
                    SET usage_approved = TRUE,
                        usage_decided_by = 12,
                        usage_decided_at = clock_timestamp(),
                        usage_note = 'isolated rollback verification',
                        model_author = 10
                    WHERE id = :run_id
                    """
                ),
                {"run_id": legacy_run_id},
            )

        run_alembic(database_url, "downgrade", "-1")
        with engine.begin() as connection:
            assert get_usage_columns(connection) == set()
            legacy = connection.execute(
                text(
                    """
                    SELECT model_version, review_status, submitted_by
                    FROM ml.prediction_review_runs
                    WHERE id = :run_id
                    """
                ),
                {"run_id": legacy_run_id},
            ).one()
            assert tuple(legacy) == ("rollback-fixture-v1", "reviewed", 10)

        run_alembic(database_url, "upgrade", "head")
        with engine.connect() as connection:
            assert get_usage_columns(connection) == USAGE_COLUMNS
            restored = connection.execute(
                text(
                    """
                    SELECT usage_approved, usage_decided_by, usage_decided_at,
                           usage_note, model_author
                    FROM ml.prediction_review_runs
                    WHERE id = :run_id
                    """
                ),
                {"run_id": legacy_run_id},
            ).one()
            assert tuple(restored) == (None, None, None, None, None)

        print(
            "PASS: migration 0027 upgraded, rolled back, and upgraded again "
            "without changing pre-existing run data."
        )
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(admin_conninfo, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(DATABASE_NAME)
                )
            )


if __name__ == "__main__":
    main()
