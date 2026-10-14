"""End-to-end, stdlib-only generator invariants; pytest and unittest discover these."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from generator.audit_generated import audit, digest, normalize_phone
from generator.generate import CsvSink

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "generator" / "generate.py"


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


class GeneratorQualityTests(unittest.TestCase):
    def generate(self, root, size):
        inbound, truth = root / "inbound", root / "truth"
        result = subprocess.run([sys.executable, str(GENERATOR), "--seed", "20260906",
                                 "--as-of-date", "2026-09-06", "--customers", str(size),
                                 "--output-dir", str(inbound), "--ground-truth-dir", str(truth)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return inbound, truth, json.loads((inbound / "generation_manifest.json").read_text(encoding="utf-8"))

    def test_empty_csv_sink_writes_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            sink = CsvSink(path, ("id", "value"))
            sink.close()
            self.assertEqual(path.read_bytes(), b"id,value\n")
            self.assertEqual(rows(path), [])

    def test_sizes_reproducible_and_auditable(self):
        for size in (20, 500):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                inbound, truth, manifest = self.generate(root / "one", size)
                other_inbound, other_truth, other_manifest = self.generate(root / "two", size)
                self.assertEqual(manifest, other_manifest)
                self.assertEqual(manifest["golden_customers"], size)
                self.assertEqual(manifest["duplicate_source_records"], round(size * 11000 / 50000))
                self.assertEqual(manifest["rng"]["optional_packages_affect_randomness"], False)
                self.assertIn("runtime", manifest)
                self.assertEqual(manifest["as_of_date"], "2026-09-06")
                for folder, section in (
                    (inbound, "tables"),
                    (truth, "ground_truth_tables"),
                ):
                    for name, info in manifest[section].items():
                        path = folder / name
                        other = other_inbound if section == "tables" else other_truth
                        legacy = "checksums_sha256" if section == "tables" else "ground_truth_checksums_sha256"
                        self.assertEqual(path.read_bytes(), (other / name).read_bytes(), name)
                        self.assertEqual(digest(path), info["sha256"])
                        self.assertEqual(info["sha256"], manifest[legacy][name])
                        if path.suffix == ".csv":
                            self.assertEqual(info["row_count"], len(rows(path)))
                for name, count in manifest["volumes"].items():
                    self.assertEqual(count, len(rows(inbound / (name + ".csv"))))
                report = audit(inbound, truth)
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["transaction_statuses"], dict(Counter(r["status"] for r in rows(inbound / "transactions.csv"))))
                self.assertEqual(report["optional_tables_present"], [name for name in ("membership_events.csv", "customer_visits.csv") if (inbound / name).exists()])

                crm = rows(inbound / "crm_customers.csv")
                mapping = rows(truth / "identity_mapping.csv")
                trajectories = rows(truth / "customer_latent_trajectories.csv")
                customers = {r["crm_customer_id"]: r for r in crm}
                identity = {r["source_customer_id"]: r for r in mapping}
                golden = {r["golden_customer_id"] for r in trajectories}
                self.assertEqual(len(customers), size + manifest["duplicate_source_records"])
                self.assertEqual(set(customers), set(identity))
                self.assertEqual(len(golden), size)
                self.assertEqual({r["golden_customer_id"] for r in mapping}, golden)
                self.assertEqual(sum(manifest["trajectory_distribution"].values()), size)
                for r in crm:
                    self.assertIn(r["status"], ("ACTIVE", "INACTIVE", "CLOSED"))
                    self.assertLessEqual(r["join_date"], r["source_updated_at"][:10])
                phones = defaultdict(set)
                for r in crm:
                    if r["phone_raw"]:
                        phones[normalize_phone(r["phone_raw"])].add(identity[r["crm_customer_id"]]["golden_customer_id"])
                collisions = {phone for phone, ids in phones.items() if len(ids) > 1}
                for r in crm:
                    if r["phone_raw"] and normalize_phone(r["phone_raw"]) in collisions:
                        self.assertEqual(identity[r["crm_customer_id"]]["identity_scenario"], "SHARED_PHONE_TRAP")

                branch_ids = {r["branch_code"] for r in rows(inbound / "branches.csv")}
                catalogue = {r["item_code"]: r for r in rows(inbound / "catalogue_items.csv")}
                transactions = {r["source_transaction_id"]: r for r in rows(inbound / "transactions.csv")}
                duplicates = {r["source_transaction_id"]: r for r in rows(truth / "transaction_duplicates.csv")}
                self.assertEqual(set(transactions), set(duplicates))
                totals = Counter()
                for r in rows(inbound / "transaction_items.csv"):
                    self.assertIn(r["source_transaction_id"], transactions)
                    self.assertIn(r["item_code"], catalogue)
                    self.assertEqual(r["item_type"], catalogue[r["item_code"]]["item_type"])
                    self.assertEqual(int(r["line_amount"]), int(r["qty"]) * int(r["unit_price"]))
                    totals[r["source_transaction_id"]] += int(r["line_amount"])
                for transaction_id, r in transactions.items():
                    with self.subTest(size=size, transaction=transaction_id):
                        self.assertIn(r["status"], ("COMPLETED", "CANCELLED", "REFUNDED", "PARTIAL_REFUND"))
                        self.assertTrue(not r["source_customer_ref"] or r["source_customer_ref"] in customers)
                        self.assertTrue(not r["branch_code"] or r["branch_code"] in branch_ids)
                        self.assertEqual(int(r["gross_amount"]), totals[transaction_id])
                        net = int(r["gross_amount"]) - int(r["discount_amount"])
                        refund = int(r["refund_amount"])
                        self.assertEqual(int(r["net_amount"]), net)
                        self.assertEqual(int(r["actual_revenue"]), 0 if r["status"] in ("CANCELLED", "REFUNDED") else net - refund)
                        self.assertEqual(refund == net, r["status"] == "REFUNDED")
                        self.assertEqual(refund > 0 and refund < net, r["status"] == "PARTIAL_REFUND")
                        self.assertLessEqual(datetime.fromisoformat(r["transaction_datetime"]), datetime.fromisoformat(manifest["observation_period"]["to"]))
                        self.assertIn(duplicates[transaction_id]["golden_customer_id"], golden)
                for name, ref in (("app_events.csv", "source_customer_id"), ("service_cases.csv", "source_customer_ref"), ("consent_events.csv", "source_customer_ref")):
                    self.assertTrue(all(r[ref] in customers for r in rows(inbound / name)))

    def test_audit_detects_corruption_even_with_updated_manifest_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            inbound, truth, manifest = self.generate(Path(directory) / "case", 20)
            path = inbound / "transactions.csv"
            content = path.read_text(encoding="utf-8")
            self.assertIn("COMPLETED", content)
            path.write_text(content.replace("COMPLETED", "INVALID", 1), encoding="utf-8")
            manifest["tables"]["transactions.csv"]["sha256"] = digest(path)
            manifest["checksums_sha256"]["transactions.csv"] = digest(path)
            (inbound / "generation_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            report = audit(inbound, truth)
            self.assertFalse(report["ok"])
            self.assertIn("transaction_status", report["errors"])


if __name__ == "__main__":
    unittest.main()
