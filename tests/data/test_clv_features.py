"""Tests for development-only point-in-time CLV aggregates."""

import unittest
from datetime import datetime, timedelta

from services.data.models.clv_features import build_clv_aggregates


class ClvFeatureTests(unittest.TestCase):
    def test_window_status_gross_revenue_and_deduplication(self):
        cutoff = datetime.fromisoformat("2026-06-01T12:00:00+07:00")
        base = {
            "source_customer_ref": "source-a",
            "source_system": "POS",
            "discount_amount": "10",
            "net_amount": "90",
            "status": "COMPLETED",
        }

        def transaction(identifier, days, gross, status="COMPLETED"):
            return {
                **base,
                "source_transaction_id": identifier,
                "transaction_datetime": (cutoff + timedelta(days=days)).isoformat(),
                "gross_amount": str(gross),
                "status": status,
            }

        included = transaction("included", -1, 100)
        rows = [
            included,
            dict(included),
            transaction("partial", -365 + 0.5, 200, "PARTIAL_REFUND"),
            transaction("left-boundary", -365, 300),
            transaction("future", 1, 400),
            transaction("refunded", -2, 500, "REFUNDED"),
        ]
        result = build_clv_aggregates(rows, {"source-a": "golden-a"}, cutoff)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["historical_spend_12m_gross"], 300)
        self.assertEqual(row["average_transaction_value_12m"], 150)
        self.assertEqual(row["transaction_count_12m"], 2)
        self.assertEqual(row["frequency_per_month_12m"], 2 / 12)
        self.assertTrue(row["history_sufficient_12m"])
        self.assertIsNone(row["retention_factor"])
        self.assertFalse(row["training_ready"])
        self.assertEqual(row["availability_time_status"], "UNPROVEN")

    def test_future_mutation_does_not_change_as_of_aggregate(self):
        cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        rows = [
            {
                "source_transaction_id": "past",
                "source_customer_ref": "source-a",
                "source_system": "POS",
                "transaction_datetime": (cutoff - timedelta(days=1)).isoformat(),
                "gross_amount": "100",
                "discount_amount": "0",
                "net_amount": "100",
                "status": "COMPLETED",
            },
            {
                "source_transaction_id": "future",
                "source_customer_ref": "source-a",
                "source_system": "POS",
                "transaction_datetime": (cutoff + timedelta(days=1)).isoformat(),
                "gross_amount": "200",
                "discount_amount": "0",
                "net_amount": "200",
                "status": "COMPLETED",
            },
        ]
        before = build_clv_aggregates(rows, {"source-a": "golden-a"}, cutoff)
        rows[1]["gross_amount"] = "999999"
        self.assertEqual(
            before,
            build_clv_aggregates(rows, {"source-a": "golden-a"}, cutoff),
        )

    def test_timezone_and_invalid_timestamp_are_rejected(self):
        aware = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        with self.assertRaisesRegex(ValueError, "cutoff must be timezone-aware"):
            build_clv_aggregates([], {}, datetime(2026, 6, 1))
        row = {
            "source_transaction_id": "one",
            "source_customer_ref": "source-a",
            "source_system": "POS",
            "transaction_datetime": "2026-05-01T00:00:00",
            "gross_amount": "100",
            "discount_amount": "0",
            "net_amount": "100",
            "status": "COMPLETED",
        }
        with self.assertRaisesRegex(
            ValueError, "transaction_datetime must be timezone-aware"
        ):
            build_clv_aggregates([row], {"source-a": "golden-a"}, aware)


if __name__ == "__main__":
    unittest.main()
