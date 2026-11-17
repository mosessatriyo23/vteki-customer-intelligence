import copy
import unittest

from services.data.monitoring.drift import (
    auc_drop,
    characteristic_stability_index,
    classify_drift,
    population_stability_index,
)

EDGES = [0, 10, 20]


class DriftMonitoringTests(unittest.TestCase):
    def test_identity_is_zero_stable_and_not_ready(self):
        data = [-1, 0, 5, 10, 20, None]
        report = population_stability_index(data, data, EDGES)
        self.assertEqual(report["value"], 0)
        self.assertEqual(report["status"], "STABLE")
        self.assertIs(report["training_ready"], False)
        self.assertIs(report["experiment_ready"], False)
        self.assertIs(report["final_model"], False)

    def test_shifted_population_counts_and_contributions(self):
        report = population_stability_index([1, 2, 3, 4], [11, 12, 13, 14], EDGES)
        self.assertEqual(report["status"], "RETRAIN_RECOMMENDED")
        self.assertGreater(report["value"], 0.25)
        self.assertEqual([b["baseline_count"] for b in report["bins"]], [0, 4, 0, 0, 0])
        self.assertEqual([b["current_count"] for b in report["bins"]], [0, 0, 4, 0, 0])
        self.assertAlmostEqual(
            report["value"], sum(b["contribution"] for b in report["bins"])
        )
        self.assertTrue(all(b["contribution"] >= 0 for b in report["bins"]))

    def test_edges_are_lower_inclusive_and_open_ended(self):
        report = population_stability_index([-5, 0, 9.9, 10, 20, 99], [1], EDGES)
        self.assertEqual([b["baseline_count"] for b in report["bins"]], [1, 2, 1, 2, 0])
        self.assertEqual(report["bins"][0]["lower"], None)
        self.assertEqual(report["bins"][0]["upper"], 0)
        self.assertEqual(report["bins"][-2]["upper"], None)

    def test_missing_bin_and_all_missing(self):
        report = population_stability_index([1, None], [None, None], EDGES)
        missing = report["bins"][-1]
        self.assertTrue(missing["missing"])
        self.assertEqual((missing["baseline_count"], missing["current_count"]), (1, 2))
        self.assertGreater(report["value"], 0)
        same = population_stability_index([None], [None, None], EDGES)
        self.assertAlmostEqual(same["value"], 0, delta=1e-5)
        self.assertEqual(same["status"], "STABLE")
        self.assertEqual(same["bins"][-1]["current_count"], 2)

    def test_smoothing_keeps_empty_bins_finite(self):
        report = population_stability_index([1], [11], EDGES, epsilon=0.5)
        self.assertEqual(report["epsilon"], 0.5)
        self.assertTrue(all(0 < b["baseline_share"] < 1 for b in report["bins"]))
        self.assertAlmostEqual(sum(b["current_share"] for b in report["bins"]), 1)

    def test_deterministic_and_no_mutation(self):
        baseline, current, edges = [3, None, 12], [4, 25, None], [0, 10, 20]
        before = copy.deepcopy((baseline, current, edges))
        first = population_stability_index(baseline, current, edges)
        second = population_stability_index(tuple(baseline), tuple(current), edges)
        self.assertEqual(first, second)
        self.assertEqual((baseline, current, edges), before)

    def test_csi_reuses_algorithm_per_feature(self):
        psi = population_stability_index([1, 2], [12, 13], EDGES)
        csi = characteristic_stability_index([1, 2], [12, 13], EDGES)
        self.assertEqual(csi["metric"], "CSI")
        self.assertEqual({**csi, "metric": "PSI"}, psi)

    def test_invalid_inputs(self):
        bad_values = [True, False, float("nan"), float("inf"), "1", object()]
        for bad in bad_values:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    population_stability_index([bad], [1], EDGES)
                with self.assertRaises(ValueError):
                    population_stability_index([1], [bad], EDGES)
                with self.assertRaises(ValueError):
                    population_stability_index([1], [1], [0, bad])
        for edges in ([], [1, 1], [2, 1]):
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                population_stability_index([1], [1], edges)
        for baseline, current in (([], [1]), ([1], [])):
            with self.assertRaises(ValueError):
                population_stability_index(baseline, current, EDGES)
        for epsilon in (0, -1, float("nan"), float("inf"), True, "1"):
            with self.subTest(epsilon=epsilon), self.assertRaises(ValueError):
                population_stability_index([1], [1], EDGES, epsilon)

    def test_drift_thresholds_exact_boundaries(self):
        cases = [
            (0, "STABLE"),
            (0.0999999999, "STABLE"),
            (0.10, "WARNING"),
            (0.2499999999, "WARNING"),
            (0.25, "RETRAIN_RECOMMENDED"),
            (1, "RETRAIN_RECOMMENDED"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(classify_drift(value), expected)
        for bad in (-0.01, True, float("nan"), "0.1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                classify_drift(bad)

    def test_auc_drop_boundary_is_strict_and_float_robust(self):
        for baseline, current in ((0.80, 0.75), (0.70, 0.65), (0.9, 0.85)):
            with self.subTest(baseline=baseline):
                report = auc_drop(baseline, current)
                self.assertFalse(report["retrain_recommended"])
                self.assertEqual(report["status"], "STABLE")
        report = auc_drop(0.80, 0.7499)
        self.assertTrue(report["retrain_recommended"])
        self.assertEqual(report["status"], "RETRAIN_RECOMMENDED")
        self.assertFalse(auc_drop(0.7, 0.8)["retrain_recommended"])
        self.assertIs(report["training_ready"], False)
        self.assertIs(report["experiment_ready"], False)
        self.assertIs(report["final_model"], False)

    def test_unavailable_auc_is_not_fabricated(self):
        for baseline, current in ((None, 0.7), (0.8, None), (None, None)):
            report = auc_drop(baseline, current)
            self.assertIsNone(report["drop"])
            self.assertEqual(report["status"], "UNAVAILABLE")
            self.assertFalse(report["retrain_recommended"])

    def test_invalid_auc(self):
        for bad in (True, float("nan"), float("inf"), "0.5", -0.1, 1.1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                auc_drop(bad, 0.5)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                auc_drop(0.5, bad)


if __name__ == "__main__":
    unittest.main()
