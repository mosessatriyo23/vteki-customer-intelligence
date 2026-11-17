"""Synthetic event-time regressions, not availability-time/bitemporal certification.

Keep the current identity snapshot fixed. No ground-truth artifact is an input to
features or scoring; the generator writes its evaluation artifacts separately.
"""

import argparse
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from generator.generate import run as generate
from services.data.features.cli import run as publish_features
from services.data.features.snapshot import build_features
from services.data.identity.cli import run as resolve
from services.data.ingestion.validator import BatchValidator, sha256
from services.data.models.baseline import predict_churn


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def append_source_row(inbound, name, row):
    """Append a valid source row and refresh the synthetic fixture's metadata."""
    path = inbound / name
    with path.open(newline="", encoding="utf-8") as stream:
        fields = csv.DictReader(stream).fieldnames
    with path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=fields).writerow(row)
    manifest_path = inbound / "generation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tables"][name]["row_count"] += 1
    manifest["tables"][name]["sha256"] = sha256(path)
    manifest["checksums_sha256"][name] = sha256(path)
    manifest["volumes"][name.removesuffix(".csv")] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


class SyntheticDataLeakageTests(unittest.TestCase):
    def test_future_t_plus_1_and_h_plus_2_do_not_change_features_or_baseline(self):
        # T+1 / H+2 are next-day and two-days-later source events, respectively.
        for days_after in (1, 2):
            with (
                self.subTest(days_after=days_after),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                inbound, resolution = root / "inbound", root / "resolution"
                generate(
                    argparse.Namespace(
                        seed=20260906,
                        customers=20,
                        as_of_date=date(2026, 9, 6),
                        output_dir=inbound,
                        ground_truth_dir=root / "evaluation_only",
                    )
                )
                report = BatchValidator().validate(inbound)
                self.assertTrue(report.valid, report.to_dict())
                resolve(
                    inbound / "crm_customers.csv", resolution, synthetic_aliases=True
                )
                cutoff = datetime.fromisoformat("2026-06-01T12:00:00+07:00")
                future_at = cutoff + timedelta(days=days_after)
                before = build_features(inbound, resolution, [cutoff])
                later_before = build_features(inbound, resolution, [future_at])
                publish_features(inbound, resolution, root / "before", [cutoff])

                # Reuse source references, not latent identity/duplicate truth.
                template = next(
                    row
                    for row in read_csv(inbound / "transactions.csv")
                    if row["source_customer_ref"]
                    and row["status"] == "COMPLETED"
                    and datetime.fromisoformat(row["transaction_datetime"]) <= cutoff
                )
                item = next(
                    row
                    for row in read_csv(inbound / "transaction_items.csv")
                    if row["source_transaction_id"] == template["source_transaction_id"]
                )
                amount = 999_999_999
                transaction_id = f"leakage-future-{days_after}"
                transaction = dict(
                    template,
                    source_transaction_id=transaction_id,
                    transaction_datetime=future_at.isoformat(),
                    source_system="ECOM",
                    channel_code="WEB_STORE",
                    branch_code="",
                    gross_amount=str(amount),
                    discount_amount="0",
                    net_amount=str(amount),
                    refund_amount="0",
                    actual_revenue=str(amount),
                )
                append_source_row(inbound, "transactions.csv", transaction)
                append_source_row(
                    inbound,
                    "transaction_items.csv",
                    dict(
                        item,
                        source_item_id=f"leakage-item-{days_after}",
                        source_transaction_id=transaction_id,
                        qty="1",
                        unit_price=str(amount),
                        line_amount=str(amount),
                    ),
                )
                # An ECOM purchase needs no physical visit. Validate accounting,
                # references, chronology, row counts and checksums after injection.
                report = BatchValidator().validate(inbound)
                self.assertTrue(report.valid, report.to_dict())
                after = build_features(inbound, resolution, [cutoff])
                self.assertTrue(before)
                self.assertEqual(after, before)
                self.assertEqual(
                    [predict_churn(row["recency_days"]) for row in after],
                    [predict_churn(row["recency_days"]) for row in before],
                )
                publish_features(inbound, resolution, root / "after", [cutoff])
                self.assertEqual(
                    (root / "before" / "features.csv").read_bytes(),
                    (root / "after" / "features.csv").read_bytes(),
                )
                self.assertTrue(all(row["training_ready"] is False for row in after))
                self.assertTrue(
                    all(
                        row["identity_time_policy"] == "CURRENT_SNAPSHOT_RETROSPECTIVE"
                        for row in after
                    )
                )

                # Positive control: the injected event must affect the mapped
                # customer once its event time is reached (inclusive boundary).
                mapping = {
                    row["source_customer_id"]: row["golden_customer_id"]
                    for row in read_csv(resolution / "mapping.csv")
                }
                golden = mapping[template["source_customer_ref"]]
                previous = next(
                    row for row in later_before if row["golden_customer_id"] == golden
                )
                current = next(
                    row
                    for row in build_features(inbound, resolution, [future_at])
                    if row["golden_customer_id"] == golden
                )
                for window in (60, 90, 365):
                    key = f"purchase_count_{window}d"
                    self.assertEqual(current[key], previous[key] + 1)
                for window in (90, 365):
                    key = f"retained_revenue_{window}d"
                    self.assertEqual(current[key], previous[key] + amount)
                self.assertEqual(current["recency_days"], 0)


if __name__ == "__main__":
    unittest.main()
