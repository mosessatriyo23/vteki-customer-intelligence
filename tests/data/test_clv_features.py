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

    def test_out_of_window_conflicting_versions_do_not_shadow_valid_row(self):
        cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        base = {
            "source_transaction_id": "same-id",
            "source_customer_ref": "source-a",
            "source_system": "POS",
            "discount_amount": "0",
            "net_amount": "100",
        }
        future = {
            **base,
            "transaction_datetime": (cutoff + timedelta(days=1)).isoformat(),
            "gross_amount": "999",
            "status": "COMPLETED",
        }
        valid = {
            **base,
            "transaction_datetime": (cutoff - timedelta(days=1)).isoformat(),
            "gross_amount": "100",
            "status": "COMPLETED",
        }
        cancelled = {**base, "status": "CANCELLED"}
        self.assertEqual(
            build_clv_aggregates([future, valid], {"source-a": "golden-a"}, cutoff)[0][
                "historical_spend_12m_gross"
            ],
            100,
        )
        self.assertEqual(
            build_clv_aggregates([cancelled, valid], {"source-a": "golden-a"}, cutoff)[
                0
            ]["historical_spend_12m_gross"],
            100,
        )

    def test_conflicting_eligible_records_are_rejected_order_independently(self):
        cutoff = datetime.fromisoformat("2026-06-01T00:00:00+07:00")
        base = {
            "source_transaction_id": "same-id",
            "source_customer_ref": "source-a",
            "source_system": "POS",
            "discount_amount": "0",
            "net_amount": "100",
            "status": "COMPLETED",
        }
        first = {
            **base,
            "transaction_datetime": (cutoff - timedelta(days=1)).isoformat(),
            "gross_amount": "100",
        }
        conflicting = {**first, "gross_amount": "200"}
        for rows in ([first, conflicting], [conflicting, first]):
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(
                    ValueError, "Conflicting in-window records"
                ):
                    build_clv_aggregates(rows, {"source-a": "golden-a"}, cutoff)

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


class ClvActualRevenueTests(unittest.TestCase):
    CUTOFF = datetime.fromisoformat("2026-06-01T12:00:00+07:00")

    def _row(self, identifier, days, gross, discount, refund, status="COMPLETED"):
        net = gross - discount
        return {
            "source_transaction_id": identifier,
            "source_customer_ref": "source-a",
            "source_system": "POS",
            "transaction_datetime": (self.CUTOFF + timedelta(days=days)).isoformat(),
            "gross_amount": str(gross),
            "discount_amount": str(discount),
            "net_amount": str(net),
            "refund_amount": str(refund),
            "actual_revenue": str(net - refund),
            "status": status,
        }

    def test_sums_actual_revenue_after_discount_and_partial_refund(self):
        from services.data.models.clv_features import (
            build_clv_actual_revenue_aggregates,
        )

        rows = [
            self._row("a", -1, 100, 10, 0),
            self._row("b", -5, 200, 20, 50, "PARTIAL_REFUND"),
            self._row("old", -365, 900, 0, 0),
            {
                **self._row("cancelled", -2, 500, 0, 0, "CANCELLED"),
                "actual_revenue": "0",
            },
        ]
        row = build_clv_actual_revenue_aggregates(
            rows, {"source-a": "golden-a"}, self.CUTOFF
        )[0]
        self.assertEqual(row["historical_spend_12m_actual_revenue"], 220)
        self.assertEqual(row["average_transaction_value_12m"], 110)
        self.assertEqual(row["transaction_count_12m"], 2)
        self.assertNotIn("historical_spend_12m_gross", row)
        self.assertEqual(row["revenue_basis"], "actual_revenue")
        self.assertEqual(
            row["feature_version"], "clv-actual-revenue-365d-dev-1.0-christ-v1.4"
        )
        self.assertFalse(row["training_ready"])
        self.assertEqual(row["availability_time_status"], "UNPROVEN")
        self.assertIsNone(row["retention_factor"])

    def test_gross_builder_is_unchanged(self):
        rows = [self._row("b", -5, 200, 20, 50, "PARTIAL_REFUND")]
        row = build_clv_aggregates(rows, {"source-a": "golden-a"}, self.CUTOFF)[0]
        self.assertEqual(row["historical_spend_12m_gross"], 200)

    def test_conflicting_actual_revenue_for_same_id_is_rejected(self):
        from services.data.models.clv_features import (
            build_clv_actual_revenue_aggregates,
        )

        first = self._row("same", -1, 100, 0, 0)
        second = {
            **first,
            "status": "PARTIAL_REFUND",
            "refund_amount": "30",
            "actual_revenue": "70",
        }
        with self.assertRaisesRegex(ValueError, "Conflicting in-window records"):
            build_clv_actual_revenue_aggregates(
                [first, second], {"source-a": "golden-a"}, self.CUTOFF
            )

    def test_invalid_actual_revenue_is_rejected(self):
        from services.data.models.clv_features import (
            build_clv_actual_revenue_aggregates,
        )

        for bad in ("", "-5", "1.5", "abc"):
            row = {**self._row("x", -1, 100, 0, 0), "actual_revenue": bad}
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "actual_revenue"):
                    build_clv_actual_revenue_aggregates(
                        [row], {"source-a": "golden-a"}, self.CUTOFF
                    )


if __name__ == "__main__":
    unittest.main()
