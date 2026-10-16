import json
import tempfile
import unittest
from pathlib import Path

from services.data.models.diagnostics import confusion, run, summarize


class ModelDiagnosticsTests(unittest.TestCase):
    def test_confusion_and_readiness(self):
        def row(g, cutoff, label, recency, status):
            return dict(
                golden_customer_id=g,
                cutoff_at=cutoff,
                outcome_end_at=(
                    "2026-06-01T00:00:00+07:00"
                    if cutoff.startswith("2026-01")
                    else "2026-10-01T00:00:00+07:00"
                ),
                churn90=str(label),
                clv90="0" if label else "100",
                recency_days=str(recency),
                eligible="True",
                outcome_complete="True",
                identity_status=status,
            )

        train = "2026-01-01T00:00:00+07:00"
        test = "2026-07-01T00:00:00+07:00"
        rows = [
            row("a", train, 1, 120, "PROVISIONAL"),
            row("b", train, 0, 10, "PROVISIONAL"),
            row("a", test, 1, 10, "REVIEW_REQUIRED"),
            row("b", test, 0, 120, "PROVISIONAL"),
        ]
        summary = summarize(rows, rows)
        self.assertFalse(summary["training_ready"])
        self.assertEqual(summary["holdout"]["rule"]["fn"], 1)
        self.assertEqual(summary["holdout"]["rule"]["fp"], 1)
        self.assertEqual(summary["holdout"]["always_nonchurn"]["fn"], 1)
        self.assertEqual(summary["holdout"]["rule"]["balanced_accuracy"], 0)
        self.assertEqual(summary["by_identity_status"]["REVIEW_REQUIRED"]["fn"], 1)
        self.assertIsNone(
            summary["by_identity_status"]["REVIEW_REQUIRED"]["balanced_accuracy"]
        )
        self.assertEqual(confusion([])["prevalence"], None)
        with self.assertRaisesRegex(ValueError, "complete and eligible"):
            summarize([{**rows[0], "eligible": "False"}, *rows[1:]], rows)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            summarize([*rows, rows[0]], rows)

    def test_manifest_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "model_manifest.json").write_text(
                json.dumps(dict(experiment_ready=True, final_model=True)),
                encoding="utf-8",
            )
            for name in ("labels.csv", "training_rows.csv", "metrics.json"):
                (source / name).write_text("", encoding="utf-8")
            output = Path(tmp) / "report"
            with self.assertRaisesRegex(ValueError, "development"):
                run(source, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
