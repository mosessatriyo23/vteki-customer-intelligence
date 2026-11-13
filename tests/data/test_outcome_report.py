import csv
import json
import tempfile
import unittest
from pathlib import Path

from services.data.models.outcome_report import run, summarize_outcomes


class OutcomeReportTests(unittest.TestCase):
    def setUp(self):
        self.labels = [
            dict(
                golden_customer_id="secret-a",
                cutoff_at="2025-01",
                outcome_complete=True,
                eligible=True,
                churn90=1,
            ),
            dict(
                golden_customer_id="secret-b",
                cutoff_at="2025-01",
                outcome_complete=False,
                eligible=True,
                churn90=None,
            ),
        ]
        self.segments = [
            dict(
                golden_customer_id="secret-a",
                cutoff_at="2025-01",
                lifecycle_status="ACTIVE",
            ),
            dict(
                golden_customer_id="secret-b", cutoff_at="2025-01", lifecycle_status=""
            ),
        ]

    def test_summary_is_aggregated_and_sorted_without_ids(self):
        report = summarize_outcomes(self.labels, self.segments)
        self.assertEqual(report["outcomes_by_cutoff"]["2025-01"]["churn_1"], 1)
        self.assertEqual(report["outcomes_by_cutoff"]["2025-01"]["incomplete"], 1)
        self.assertEqual(report["lifecycle_by_cutoff"]["2025-01"]["UNCLASSIFIED"], 1)
        self.assertNotIn("secret", json.dumps(report))
        self.assertFalse(report["training_ready"])

    def test_validation(self):
        for labels, segments in (
            ([*self.labels, self.labels[0]], self.segments),
            (self.labels, [*self.segments, self.segments[0]]),
            (self.labels, self.segments[:1]),
            ([{**self.labels[0], "eligible": "yes"}, self.labels[1]], self.segments),
            ([{**self.labels[0], "churn90": True}, self.labels[1]], self.segments),
            ([{**self.labels[1], "churn90": 0}, self.labels[0]], self.segments),
            ([{**self.labels[0], "churn90": None}, self.labels[1]], self.segments),
            (
                self.labels,
                [{**self.segments[0], "lifecycle_status": "UNKNOWN"}, self.segments[1]],
            ),
        ):
            with self.subTest(labels=labels):
                with self.assertRaises(ValueError):
                    summarize_outcomes(labels, segments)

    def test_csv_publish_manifest_replay_and_invalid_no_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            labels = root / "labels.csv"
            segments = root / "segments.csv"

            def write(path, rows):
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            write(
                labels,
                [
                    dict(
                        golden_customer_id="secret-a",
                        cutoff_at="2025-01",
                        outcome_complete="True",
                        eligible="True",
                        churn90="1",
                    ),
                    dict(
                        golden_customer_id="secret-b",
                        cutoff_at="2025-01",
                        outcome_complete="False",
                        eligible="True",
                        churn90="",
                    ),
                ],
            )
            write(
                segments,
                [
                    dict(
                        golden_customer_id="secret-a",
                        cutoff_at="2025-01",
                        lifecycle_status="ACTIVE",
                    ),
                    dict(
                        golden_customer_id="secret-b",
                        cutoff_at="2025-01",
                        lifecycle_status="",
                    ),
                ],
            )
            output = root / "report"
            run(labels, segments, output)
            self.assertNotIn(
                "secret", (output / "report.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["output_sha256"]["report.json"]), 64)
            with self.assertRaises(ValueError):
                run(labels, segments, output)
            invalid_output = root / "invalid"
            write(
                labels,
                [
                    dict(
                        golden_customer_id="secret-a",
                        cutoff_at="2025-01",
                        outcome_complete="maybe",
                        eligible="True",
                        churn90="1",
                    )
                ],
            )
            with self.assertRaises(ValueError):
                run(labels, segments, invalid_output)
            self.assertFalse(invalid_output.exists())


if __name__ == "__main__":
    unittest.main()
