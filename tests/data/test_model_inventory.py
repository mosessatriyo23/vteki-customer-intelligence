"""Read-only development model inventory; never a registry promotion."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.data.ingestion.validator import sha256
from services.data.models.model_inventory import PROMOTION_REQUIREMENTS, build_inventory


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class ModelInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_model(self, name="m1", **overrides) -> Path:
        directory = self.root / name
        directory.mkdir()
        write_json(directory / "evaluation.json", {"auc": 0.7})
        manifest = {
            "development_only": True,
            "serving_ready": False,
            "model_version": "moses-test-dev-1.0",
            "feature_version": "fv-1",
            "target": "retail_purchase30",
            "limitations": ["synthetic only"],
            "output_sha256": {"evaluation.json": sha256(directory / "evaluation.json")},
            **overrides,
        }
        write_json(directory / "experiment_manifest.json", manifest)
        return directory

    def test_records_verified_checksums_and_leaves_governance_fields_empty(self):
        directory = self.make_model()
        report = build_inventory([directory])
        entry = report["models"][0]
        self.assertEqual(entry["model_version"], "moses-test-dev-1.0")
        self.assertEqual(entry["artifact_dir"], "m1")
        self.assertTrue(entry["checksums_verified"])
        self.assertEqual(
            entry["manifest_sha256"], sha256(directory / "experiment_manifest.json")
        )
        self.assertEqual(entry["limitations"], ["synthetic only"])
        self.assertEqual(entry["state"], "UNREGISTERED_DEV_ONLY")
        for field in ("trained_by", "validated_by", "calibration_ref"):
            self.assertIsNone(entry[field])
        self.assertEqual(entry["missing_for_promotion"], list(PROMOTION_REQUIREMENTS))
        self.assertFalse(entry["promotable"])
        self.assertFalse(report["registry_authoritative"])
        self.assertFalse(report["serving_ready"])

    def test_checksum_mismatch_is_reported_not_hidden(self):
        directory = self.make_model()
        (directory / "evaluation.json").write_text("{}", encoding="utf-8")
        entry = build_inventory([directory])["models"][0]
        self.assertFalse(entry["checksums_verified"])
        self.assertEqual(entry["checksum_mismatches"], ["evaluation.json"])

    def test_missing_output_file_is_a_mismatch(self):
        directory = self.make_model()
        (directory / "evaluation.json").unlink()
        entry = build_inventory([directory])["models"][0]
        self.assertFalse(entry["checksums_verified"])
        self.assertEqual(entry["checksum_mismatches"], ["evaluation.json"])

    def test_empty_checksum_mapping_is_refused(self):
        directory = self.make_model(output_sha256={})
        with self.assertRaisesRegex(ValueError, "nonempty"):
            build_inventory([directory])

    def test_path_traversal_is_refused(self):
        for index, name in enumerate(
            ("../secret", "..\\secret", "C:secret", "/secret")
        ):
            directory = self.make_model(str(index), output_sha256={name: "x"})
            with self.assertRaisesRegex(ValueError, "filenames"):
                build_inventory([directory])

    def test_same_directory_names_cannot_hide_distinct_models(self):
        first = self.make_model()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_inventory([first, first])

    def test_evaluation_and_parameter_metadata_are_read_from_verified_bytes(self):
        directory = self.make_model()
        report = {
            "model_version": "moses-test-dev-1.0",
            "features": ["recency_days"],
            "feature_version": "fv-1",
            "train_cutoffs": ["2025-12-01T00:00:00+07:00"],
            "test_cutoffs": ["2026-06-01T00:00:00+07:00"],
            "metrics": {"auc": 0.7},
            "limitations": ["report caveat"],
        }
        write_json(directory / "evaluation.json", report)
        manifest = json.loads((directory / "experiment_manifest.json").read_text())
        manifest["output_sha256"]["evaluation.json"] = sha256(
            directory / "evaluation.json"
        )
        write_json(directory / "experiment_manifest.json", manifest)
        entry = build_inventory([directory])["models"][0]
        self.assertEqual(entry["evaluation"], report)
        self.assertIn("report caveat", entry["limitations"])
        self.assertEqual(entry["artifact_sha256"], manifest["output_sha256"])
        self.assertIsNone(entry["validated_by"])

    def test_all_five_governance_fields_absent_unless_manifest_supplies_them(self):
        entry = build_inventory([self.make_model()])["models"][0]
        for field in PROMOTION_REQUIREMENTS:
            self.assertIsNone(entry[field])
        self.assertEqual(entry["missing_for_promotion"], list(PROMOTION_REQUIREMENTS))

    def test_manifest_supplied_governance_fields_pass_through_without_promotion(self):
        supplied = {
            "trained_by": "trainer-a",
            "validated_by": "validator-b",
            "calibration_ref": "cal-ref-1",
            "explainability_ref": "exp-ref-1",
            "leakage_check_result": {"passed": True},
        }
        entry = build_inventory([self.make_model(**supplied)])["models"][0]
        for field, value in supplied.items():
            self.assertEqual(entry[field], value)
        self.assertEqual(entry["missing_for_promotion"], [])
        self.assertEqual(entry["state"], "UNREGISTERED_DEV_ONLY")
        self.assertFalse(entry["promotable"])

    def test_each_artifact_is_opened_once_so_hash_and_parse_share_bytes(self):
        directory = self.make_model()
        opened = []
        real_open = os.open

        def counting_open(path, *args, **kwargs):
            opened.append(Path(path).name)
            return real_open(path, *args, **kwargs)

        with patch("services.data.models.model_inventory.os.open", counting_open):
            build_inventory([directory])
        self.assertEqual(opened.count("evaluation.json"), 1)
        self.assertEqual(opened.count("experiment_manifest.json"), 1)

    def test_file_replaced_between_check_and_open_is_rejected(self):
        directory = self.make_model()
        target = directory / "evaluation.json"
        other = directory / "other.json"
        write_json(other, {"auc": 0.99})
        real_open = os.open

        def swap_then_open(path, *args, **kwargs):
            if Path(path) == target:
                os.replace(other, target)
            return real_open(path, *args, **kwargs)

        with patch("services.data.models.model_inventory.os.open", swap_then_open):
            with self.assertRaisesRegex(ValueError, "changed"):
                build_inventory([directory])

    def test_symlink_swapped_in_after_the_existence_check_is_rejected(self):
        directory = self.make_model()
        target = directory / "evaluation.json"
        outside = self.root / "outside.json"
        write_json(outside, {"auc": 0.99})
        real_open = os.open

        def swap_to_symlink_then_open(path, *args, **kwargs):
            if Path(path) == target and not Path(path).is_symlink():
                target.unlink()
                target.symlink_to(outside)
            return real_open(path, *args, **kwargs)

        try:
            (directory / "probe").symlink_to(outside)
            (directory / "probe").unlink()
        except OSError:
            self.skipTest("symlink creation is not permitted here")

        with patch(
            "services.data.models.model_inventory.os.open", swap_to_symlink_then_open
        ):
            with self.assertRaisesRegex(ValueError, "Symlink|cannot open"):
                build_inventory([directory])

    def test_symlink_artifact_is_rejected(self):
        directory = self.make_model()
        outside = self.root / "outside.json"
        write_json(outside, {"auc": 0.7})
        target = directory / "evaluation.json"
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is not permitted here")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            build_inventory([directory])

    def test_serving_ready_manifest_is_refused(self):
        directory = self.make_model(serving_ready=True)
        with self.assertRaisesRegex(ValueError, "development-only"):
            build_inventory([directory])

    def test_non_development_manifest_is_refused(self):
        directory = self.make_model(development_only=False)
        with self.assertRaisesRegex(ValueError, "development-only"):
            build_inventory([directory])

    def test_missing_manifest_is_refused(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, "experiment_manifest.json"):
            build_inventory([empty])

    def test_output_is_deterministic_and_order_independent(self):
        first, second = self.make_model("a"), self.make_model("b")
        self.assertEqual(
            build_inventory([first, second]), build_inventory([second, first])
        )

    def test_carries_synthetic_data_disclaimer(self):
        report = build_inventory([self.make_model()])
        self.assertIn("data sintetis", report["evaluation_disclaimer"])
        self.assertIn(
            "tidak memprediksi kinerja produksi", report["evaluation_disclaimer"]
        )


if __name__ == "__main__":
    unittest.main()
