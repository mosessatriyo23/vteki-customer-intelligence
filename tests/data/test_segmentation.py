import argparse
import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from generator.generate import run as generate
from services.data.features.snapshot import build_features
from services.data.identity.cli import run as resolve
from services.data.segmentation.snapshot import build_segments, lifecycle, score


class SegmentationTests(unittest.TestCase):
    def test_lifecycle_boundaries_priority_and_fallback(self):
        self.assertEqual(lifecycle(30, None, 0, 0, 0, False, lifetime_count=0), "NEW")
        self.assertEqual(
            lifecycle(31, None, 0, 0, 0, False, lifetime_count=0), "NEVER_TRANSACTED"
        )
        for recency, label in (
            (90, "OCCASIONAL"),
            (91, "AT_RISK"),
            (180, "AT_RISK"),
            (181, "DORMANT"),
            (365, "DORMANT"),
            (366, "CHURNED"),
        ):
            expected = "UNCLASSIFIED" if label == "CHURNED" else label
            self.assertEqual(
                lifecycle(400, recency, 0, 0, 0, False, lifetime_count=1), expected
            )
        self.assertEqual(
            lifecycle(400, 366, 0, 0, 0, False, 181, lifetime_count=1), "CHURNED"
        )
        self.assertEqual(
            lifecycle(400, 366, 0, 0, 0, False, 180, lifetime_count=1), "UNCLASSIFIED"
        )
        self.assertEqual(
            lifecycle(60, 1, 5, 5, 500000, False, lifetime_count=5), "LOYAL"
        )
        self.assertEqual(
            lifecycle(59, 1, 3, 5, 500000, False, lifetime_count=5), "ACTIVE"
        )
        self.assertEqual(
            lifecycle(400, 1, 5, 5, 500000, True, lifetime_count=5), "REACTIVATED"
        )
        self.assertEqual(score(30, (31, 61, 91, 181), True), 5)
        self.assertEqual(score(181, (31, 61, 91, 181), True), 1)

    def test_new_requires_at_most_two_lifetime_purchases(self):
        for tenure, count, expected in (
            (30, 2, "NEW"),
            (30, 3, "ACTIVE"),
            (31, 2, "OCCASIONAL"),
        ):
            with self.subTest(tenure=tenure, count=count):
                self.assertEqual(
                    lifecycle(tenure, 1, count, count, 0, False, lifetime_count=count),
                    expected,
                )
        with self.assertRaises(TypeError):
            lifecycle(30, 1, 3, 3, 0, False)

    def test_new_uses_deduplicated_cutoff_lifetime_history(self):
        cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        profile = dict(
            golden_customer_id="g1",
            first_join_date="2026-05-02",
            identity_status="PROVISIONAL",
        )

        def purchase(days, status="COMPLETED"):
            return dict(
                source_customer_ref="s1",
                source_system="POS",
                branch_code="B1",
                channel_code="POS",
                transaction_datetime=(cutoff - timedelta(days=days)).isoformat(),
                gross_amount="100000",
                discount_amount="0",
                net_amount="100000",
                actual_revenue="100000",
                status=status,
            )

        rows = [purchase(2), purchase(1, "PARTIAL_REFUND")]

        def read_rows(path):
            if path.name == "mapping.csv":
                return [dict(source_customer_id="s1", golden_customer_id="g1")]
            if path.name == "transactions.csv":
                return rows
            return []

        with (
            patch(
                "services.data.segmentation.snapshot.build_profiles",
                return_value=[profile],
            ),
            patch("services.data.segmentation.snapshot.read", side_effect=read_rows),
        ):

            def segment():
                return build_segments(
                    Path("inbound"), Path("resolution"), cutoff, window_days=90
                )[0]

            original = segment()
            self.assertEqual(original["lifecycle"], "NEW")
            rows.extend([dict(rows[0]), purchase(-1), purchase(0, "CANCELLED")])
            self.assertEqual(segment(), original)
            rows.append(purchase(0))
            self.assertEqual(segment()["lifecycle"], "ACTIVE")
            # A purchase outside the rolling window still counts toward lifetime.
            rows[-1] = purchase(100)
            historical = segment()
            self.assertEqual(historical["frequency"], 2)
            self.assertEqual(historical["lifecycle"], "OCCASIONAL")
            self.assertEqual(historical["monetary"], original["monetary"])
            # The lifecycle-only rule change must not alter model feature inputs.
            features = build_features(Path("inbound"), Path("resolution"), [cutoff])
            self.assertEqual(features[0]["purchase_count_365d"], 3)
            self.assertEqual(features[0]["retained_revenue_365d"], 300000)
            with patch(
                "services.data.segmentation.snapshot.lifecycle", return_value="NEW"
            ):
                legacy_features = build_features(
                    Path("inbound"), Path("resolution"), [cutoff]
                )
            self.assertEqual(features, legacy_features)

    def test_future_mutation_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound = root / "inbound"
            resolution = root / "identity"
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=20,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", resolution, synthetic_aliases=True)
            cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
            first = build_segments(inbound, resolution, cutoff)
            self.assertTrue(first)
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
            self.assertEqual(first, build_segments(inbound, resolution, cutoff))
            self.assertTrue(
                all(
                    1 <= row[key] <= 5
                    for row in first
                    for key in ("r_score", "f_score", "m_score")
                )
            )
            with self.assertRaises(ValueError):
                build_segments(inbound, resolution, cutoff, 30)
