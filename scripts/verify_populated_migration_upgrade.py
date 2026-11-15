"""Verify Alembic upgrades with pre-existing transaction, visit, and membership rows."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DATABASE_NAME = "vteki_populated_upgrade_fixture"
PRE_EVENT_HISTORY_REVISION = "0014_identity_batch_assignment_unique"


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
        raise SystemExit("The migration upgrade fixture requires PostgreSQL.")
    target_url = admin_url.set(database=DATABASE_NAME)
    admin_conninfo = admin_url.set(
        drivername="postgresql",
        database="postgres",
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

    migration_environment = os.environ.copy()
    migration_url = target_url.render_as_string(hide_password=False)
    migration_environment["DATABASE_URL"] = migration_url
    migration_environment["MIGRATION_DATABASE_URL"] = migration_url
    engine = None
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "upgrade",
                PRE_EVENT_HISTORY_REVISION,
            ],
            check=True,
            env=migration_environment,
        )

        engine = create_engine(migration_url)
        batch_id = "populated-migration-upgrade-batch"
        transaction_id = "populated-migration-upgrade-tx"
        customer_id = "populated-migration-upgrade-customer"
        branch_code = "MIGRATION-CI"
        old_occurred_at = datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc)
        captured_at = datetime.now(timezone.utc) - timedelta(days=1)
        visit_time = old_occurred_at + timedelta(hours=1)
        membership_time = old_occurred_at + timedelta(hours=2)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO stg.ingestion_batches (
                        batch_id, schema_version, seed, as_of_date,
                        manifest_payload, table_checksums, status,
                        rejection_reasons, row_counts, loaded_at, published_at
                    ) VALUES (
                        :batch_id, '2.0.0', NULL, :as_of_date,
                        CAST('{}' AS jsonb), CAST('{}' AS jsonb), 'PUBLISHED',
                        NULL, CAST('{}' AS jsonb), :loaded_at, :published_at
                    )
                    """
                ),
                {
                    "batch_id": batch_id,
                    "as_of_date": date(2025, 1, 3),
                    "loaded_at": captured_at,
                    "published_at": captured_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source.branches (
                        branch_code, branch_name, city, region, active_flag,
                        source_batch_id, created_at
                    ) VALUES (
                        :branch_code, 'Migration Branch', 'Test City',
                        'Test Region', TRUE, :batch_id, :created_at
                    )
                    """
                ),
                {
                    "branch_code": branch_code,
                    "batch_id": batch_id,
                    "created_at": captured_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source.crm_customers (
                        crm_customer_id, full_name, phone_raw, email_raw,
                        birth_month, gender, city, member_code,
                        membership_tier, join_date, preferred_branch_code,
                        status, source_updated_at, source_batch_id, created_at
                    ) VALUES (
                        :customer_id, 'Migration Fixture', NULL, NULL,
                        1, 'U', 'Test City', 'MEM-MIGRATION',
                        'BRONZE', :join_date, :branch_code, 'ACTIVE',
                        :source_updated_at, :batch_id, :created_at
                    )
                    """
                ),
                {
                    "customer_id": customer_id,
                    "join_date": date(2025, 1, 1),
                    "branch_code": branch_code,
                    "source_updated_at": captured_at,
                    "batch_id": batch_id,
                    "created_at": captured_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source.transactions (
                        source_transaction_id, source_customer_ref, source_system,
                        branch_code, channel_code, transaction_datetime,
                        gross_amount, discount_amount, net_amount, refund_amount,
                        actual_revenue, status, source_batch_id, created_at
                    ) VALUES (
                        :transaction_id, :customer_id, 'POS', :branch_code,
                        'STORE', :occurred_at, 1000, 0, 1000, 0,
                        1000, 'COMPLETED', :batch_id, :created_at
                    )
                    """
                ),
                {
                    "transaction_id": transaction_id,
                    "customer_id": customer_id,
                    "branch_code": branch_code,
                    "occurred_at": old_occurred_at,
                    "batch_id": batch_id,
                    "created_at": captured_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source.customer_visits (
                        visit_id, source_customer_ref, source_transaction_id,
                        branch_code, visit_datetime, status, source_batch_id,
                        created_at
                    ) VALUES (
                        'populated-migration-visit', :customer_id,
                        :transaction_id, :branch_code, :occurred_at, 'COMPLETED',
                        :batch_id, :created_at
                    )
                    """
                ),
                {
                    "customer_id": customer_id,
                    "transaction_id": transaction_id,
                    "branch_code": branch_code,
                    "occurred_at": visit_time,
                    "batch_id": batch_id,
                    "created_at": captured_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source.membership_events (
                        event_id, source_customer_ref, member_code, event_type,
                        occurred_at, period_start, expires_at, membership_tier,
                        previous_event_id, source_batch_id, created_at
                    ) VALUES (
                        'populated-migration-membership', :customer_id,
                        'MEM-MIGRATION', 'RENEWAL', :occurred_at,
                        :period_start, :expires_at, 'BRONZE', NULL,
                        :batch_id, :created_at
                    )
                    """
                ),
                {
                    "customer_id": customer_id,
                    "occurred_at": membership_time,
                    "period_start": membership_time,
                    "expires_at": membership_time + timedelta(days=365),
                    "batch_id": batch_id,
                    "created_at": captured_at,
                },
            )

        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env=migration_environment,
        )

        with engine.connect() as connection:
            transaction_event = (
                connection.execute(
                    text(
                        """
                    SELECT source_batch_id, source_transaction_batch_id,
                           occurred_at, available_at
                    FROM source.transaction_event_history
                    WHERE source_transaction_id = :transaction_id
                      AND event_type = 'TRANSACTION_RECORDED'
                    """
                    ),
                    {"transaction_id": transaction_id},
                )
                .mappings()
                .one()
            )
            assert transaction_event["source_batch_id"] == batch_id
            assert transaction_event["source_transaction_batch_id"] == batch_id
            assert transaction_event["occurred_at"] == old_occurred_at
            assert transaction_event["available_at"] == captured_at

            events = (
                connection.execute(
                    text(
                        """
                    SELECT event_type, source_event_id, occurred_at,
                           available_at, recorded_at
                    FROM source.business_event_history
                    WHERE source_customer_ref = :customer_id
                    ORDER BY occurred_at
                    """
                    ),
                    {"customer_id": customer_id},
                )
                .mappings()
                .all()
            )
            assert {row["event_type"] for row in events} == {
                "VISIT_COMPLETED",
                "MEMBERSHIP_RENEWAL",
            }
            assert {row["occurred_at"] for row in events} == {
                visit_time,
                membership_time,
            }
            assert all(row["source_event_id"] for row in events)
            assert all(row["recorded_at"] >= row["available_at"] for row in events)

        print(
            "PASS: populated transaction, visit, and membership rows upgraded "
            "through Alembic head."
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
