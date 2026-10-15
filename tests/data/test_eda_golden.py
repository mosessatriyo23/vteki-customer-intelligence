import argparse
import csv
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from generator.generate import run as generate
from services.data.eda.golden import distribution, run, summarize_segments
from services.data.identity.cli import run as resolve
from services.data.ingestion.validator import sha256
from services.data.segmentation.snapshot import build_segments


class GoldenEdaTests(unittest.TestCase):
    @staticmethod
    def _prepare(root: Path) -> tuple[Path, Path, datetime]:
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
        return inbound, resolution, datetime.fromisoformat("2026-06-01T00:00:00+07:00")

    def test_quantiles(self):
        stats = distribution([0, 1, 2, None, 3])
        self.assertEqual(
            (stats["count"], stats["missing"], stats["min"], stats["max"]),
            (4, 1, 0, 3),
        )
        self.assertEqual(stats["quantiles"], {"p25": 0.75, "p50": 1.5, "p75": 2.25})
        empty = distribution([None])
        self.assertEqual((empty["count"], empty["missing"]), (0, 1))

    def test_generated_run_recomputes_segments_and_protects_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound, resolution, cutoff = self._prepare(root)
            expected = summarize_segments(
                build_segments(inbound, resolution, cutoff), cutoff
            )

            output = root / "golden-report"
            self.assertEqual(run(inbound, resolution, cutoff, output), expected)
            payload = (output / "summary.json").read_text(encoding="utf-8")
            self.assertEqual(json.loads(payload), expected)
            for forbidden in ("crm_customer_id", "golden_customer_id", "full_name"):
                self.assertNotIn(forbidden, payload)
                manifest_raw = (output / "eda_manifest.json").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(forbidden, manifest_raw)
            self.assertNotIn(
                "golden_customer_id",
                (output / "report.md").read_text(encoding="utf-8"),
            )
            manifest = json.loads(manifest_raw)
            self.assertEqual(
                manifest["source_sha256_after"], manifest["source_sha256_before"]
            )
            self.assertEqual(
                manifest["resolver_sha256_after"], manifest["resolver_sha256_before"]
            )
            for name, digest in manifest["output_sha256"].items():
                self.assertEqual(digest, sha256(output / name))
            self.assertEqual(manifest["batch_validation"]["valid"], True)
            with self.assertRaisesRegex(ValueError, "must not be overwritten"):
                run(inbound, resolution, cutoff, output)

    def test_tampered_resolver_and_batch_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound, resolution, cutoff = self._prepare(root)
            output = root / "report"
            mapping = resolution / "mapping.csv"
            original = mapping.read_bytes()
            mapping.write_bytes(original + b"\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                run(inbound, resolution, cutoff, output)
            self.assertFalse(output.exists())
            mapping.write_bytes(original)
            transactions = inbound / "transactions.csv"
            transactions.write_bytes(transactions.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "validation failed"):
                run(inbound, resolution, cutoff, output)
            self.assertFalse(output.exists())

    def test_future_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbound, resolution, cutoff = self._prepare(root)
            first = summarize_segments(
                build_segments(inbound, resolution, cutoff), cutoff
            )
            path = inbound / "transactions.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                rows = list(reader)
            mutated = False
            for row in rows:
                if datetime.fromisoformat(row["transaction_datetime"]) > cutoff:
                    row["actual_revenue"] = "999999999"
                    mutated = True
            self.assertTrue(mutated)
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(
                first,
                summarize_segments(build_segments(inbound, resolution, cutoff), cutoff),
            )


if __name__ == "__main__":
    unittest.main()
