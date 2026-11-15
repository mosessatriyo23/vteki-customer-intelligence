import argparse
import csv
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from generator.generate import run as generate
from services.data.customer360.profile import build_profiles, build_profiles_as_of
from services.data.identity.cli import run as resolve
from services.data.identity.registry import (
    IdentityHistoryCoverageError,
    IdentityMappingAsOf,
    PersistentIdentityRegistry,
)


def read_mapping(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


class Customer360Tests(unittest.TestCase):

    def test_build_profiles_as_of_uses_registry_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound = root / "inbound"
            output = root / "resolution"
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=20,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", output, synthetic_aliases=True)

            cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
            recorded_at = datetime.fromisoformat("2026-11-15T10:00:00+00:00")
            mapping = {
                row["source_customer_id"]: row["golden_customer_id"]
                for row in read_mapping(output / "mapping.csv")
            }

            with patch.object(
                PersistentIdentityRegistry,
                "get_mapping_as_of_result",
                return_value=IdentityMappingAsOf(
                    status="AVAILABLE",
                    mapping=mapping,
                    coverage_started_at=cutoff,
                ),
            ) as lookup:
                profiles = build_profiles_as_of(
                    inbound,
                    output,
                    cutoff,
                    session=object(),
                    recorded_at=recorded_at,
                )

            lookup.assert_called_once_with(cutoff, recorded_at)
            self.assertTrue(profiles)

    def test_build_profiles_as_of_surfaces_blocked_history_coverage(self):
        cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        blocked = IdentityMappingAsOf(
            status="BLOCKED",
            mapping={},
            coverage_started_at=datetime.fromisoformat("2026-11-15T00:00:00+00:00"),
        )
        with patch.object(
            PersistentIdentityRegistry,
            "get_mapping_as_of_result",
            return_value=blocked,
        ):
            with self.assertRaisesRegex(IdentityHistoryCoverageError, "BLOCKED"):
                build_profiles_as_of(
                    Path("inbound"),
                    Path("resolution"),
                    cutoff,
                    session=object(),
                )

    def test_generated_snapshot_cutoff_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound = root / "inbound"
            output = root / "resolution"
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=20,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", output, synthetic_aliases=True)
            cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
            profiles = build_profiles(inbound, output, cutoff)
            self.assertTrue(profiles)
            self.assertTrue(all(r["first_join_date"] <= "2026-06-01" for r in profiles))
            self.assertTrue(
                all(
                    not r["last_transaction_at"]
                    or datetime.fromisoformat(r["last_transaction_at"]) <= cutoff
                    for r in profiles
                )
            )
            self.assertTrue(
                all(
                    r["identity_status"] in {"PROVISIONAL", "REVIEW_REQUIRED"}
                    for r in profiles
                )
            )
            # Future transaction amounts must not alter historical retained revenue.
            path = inbound / "transactions.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                rows = list(reader)
            for row in rows:
                if datetime.fromisoformat(row["transaction_datetime"]) > cutoff:
                    row["actual_revenue"] = "999999999"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(profiles, build_profiles(inbound, output, cutoff))
            with self.assertRaisesRegex(ValueError, "timezone"):
                build_profiles(inbound, output, datetime(2026, 6, 1))
            (output / "mapping.csv").write_text("corrupted", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                build_profiles(inbound, output, cutoff)
