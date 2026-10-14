"""Small source-only and temporal-isolation regression tests."""

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from generator.business_events import (
    MEMBERSHIP_FIELDS,
    VISIT_FIELDS,
    make_customer_visits,
    make_membership_events,
)
from generator.labels import LABEL_FIELDS, make_labels


class CsvSink:
    """Minimal CsvSink-compatible fixture, independent of optional generator packages."""

    def __init__(self, path, fields):
        self.stream = path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.stream, fieldnames=fields)
        self.writer.writeheader()

    def write(self, row):
        self.writer.writerow(row)

    def close(self):
        self.stream.close()


def table(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


class BusinessReadinessTests(unittest.TestCase):
    def test_membership_chain_and_future_contract_not_future_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "membership_events.csv"
            sink = CsvSink(path, MEMBERSHIP_FIELDS)

            class AlwaysRenew:
                def random(self):
                    return 0.0

            try:
                make_membership_events(
                    3,
                    [
                        {
                            "crm_customer_id": "a",
                            "member_code": "M1",
                            "join_date": "2025-01-01",
                            "membership_tier": "BRONZE",
                        },
                        {
                            "crm_customer_id": "b",
                            "member_code": "",
                            "join_date": "2025-01-01",
                        },
                    ],
                    datetime(2025, 1, 1, tzinfo=timezone.utc),
                    datetime(2025, 7, 2, tzinfo=timezone.utc),
                    AlwaysRenew(),
                    sink,
                )
            finally:
                sink.close()
            events = rows(path)
            self.assertEqual([e["event_type"] for e in events], ["JOIN", "RENEWAL"])
            self.assertEqual(events[1]["previous_event_id"], events[0]["event_id"])
            self.assertEqual(events[0]["expires_at"][:10], "2025-06-30")
            self.assertEqual(events[1]["occurred_at"][:10], "2025-07-01")
            self.assertGreater(events[1]["expires_at"], "2025-07-02")

    def test_visits_replay_and_label_temporal_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crm = root / "crm.csv"
            txn = root / "transactions.csv"
            items = root / "items.csv"
            visits = root / "visits.csv"
            members = root / "members.csv"
            labels = root / "labels.csv"
            table(
                crm,
                ["crm_customer_id", "join_date"],
                [
                    {"crm_customer_id": "a", "join_date": "2024-01-01"},
                    {"crm_customer_id": "new", "join_date": "2025-03-01"},
                ],
            )
            base = {
                "source_customer_ref": "a",
                "source_system": "POS",
                "branch_code": "BR-01",
                "channel_code": "POS_STORE",
                "transaction_datetime": "2025-01-10T12:00:00+00:00",
                "gross_amount": "100",
                "discount_amount": "0",
                "net_amount": "100",
                "status": "COMPLETED",
            }
            table(
                txn,
                ["source_transaction_id", *base],
                [
                    {"source_transaction_id": "t1", **base},
                    {"source_transaction_id": "t2", **base},
                    {
                        "source_transaction_id": "t3",
                        **{
                            **base,
                            "source_system": "ECOM",
                            "transaction_datetime": "2025-01-15T12:00:00+00:00",
                            "status": "REFUNDED",
                        },
                    },
                    {
                        "source_transaction_id": "t4",
                        **{
                            **base,
                            "transaction_datetime": "2025-02-20T12:00:00+00:00",
                            "status": "PARTIAL_REFUND",
                            "net_amount": "40",
                        },
                    },
                ],
            )
            table(
                items,
                ["source_transaction_id", "item_type"],
                [
                    {"source_transaction_id": "t1", "item_type": "PRODUCT"},
                    {"source_transaction_id": "t4", "item_type": "SERVICE"},
                ],
            )
            sink = CsvSink(visits, VISIT_FIELDS)
            try:
                self.assertEqual(make_customer_visits(3, txn, sink), 2)
            finally:
                sink.close()
            self.assertEqual(
                [r["source_transaction_id"] for r in rows(visits)], ["t1", "t4"]
            )
            table(members, MEMBERSHIP_FIELDS, [])
            sink = CsvSink(labels, LABEL_FIELDS)
            try:
                make_labels(
                    crm,
                    txn,
                    items,
                    visits,
                    members,
                    ["2025-01-01", "2025-04-01"],
                    "2025-05-01",
                    sink,
                )
            finally:
                sink.close()
            first, second, third = rows(labels)
            self.assertEqual(first["source_customer_ref"], "a")
            self.assertEqual(first["churn90"], "0")
            self.assertEqual(first["retail30"], "1")
            self.assertEqual(first["service30"], "0")
            self.assertEqual(first["historical_refund_adjusted_net"], "0.0")
            self.assertEqual(first["future_refund_adjusted_net"], "140.0")
            self.assertEqual(second["outcome_complete"], "0")
            self.assertEqual(second["churn90"], "")
            self.assertEqual(second["historical_refund_adjusted_net"], "140.0")
            self.assertEqual(third["source_customer_ref"], "new")


if __name__ == "__main__":
    unittest.main()
