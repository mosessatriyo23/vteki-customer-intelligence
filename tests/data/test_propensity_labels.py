"""PROPOSED development propensity labels: retail purchase 30d and renewal 60d."""

import argparse
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from generator.generate import run as generate
from services.data.identity.cli import run as resolve
from services.data.ingestion.validator import sha256
from services.data.models.propensity_labels import (
    RENEWAL_VERSION,
    RETAIL_VERSION,
    UNSUPPORTED_SOURCE,
    booking_status,
    build_propensity_labels,
    join_propensity_training_rows,
    run,
)

CUTOFF = datetime.fromisoformat("2026-01-01T00:00:00+07:00")
MODULE = "services.data.models.propensity_labels"


def tx(tid, ref, days, status="COMPLETED", system="POS", **extra):
    return dict(
        source_transaction_id=tid,
        source_customer_ref=ref,
        source_system=system,
        branch_code="BR-01",
        channel_code="POS_STORE",
        transaction_datetime=(CUTOFF + timedelta(days=days)).isoformat(),
        gross_amount="100",
        discount_amount="0",
        net_amount="100",
        actual_revenue="100",
        status=status,
        **extra,
    )


def item(tid, item_type):
    return dict(source_transaction_id=tid, item_type=item_type)


def member(ref, event_type, occurred_days, expires_days, tier="SILVER"):
    return dict(
        source_customer_ref=ref,
        event_type=event_type,
        occurred_at=(CUTOFF + timedelta(days=occurred_days)).isoformat(),
        expires_at=(CUTOFF + timedelta(days=expires_days)).isoformat(),
        membership_tier=tier,
    )


def build(
    ids,
    transactions=(),
    items=(),
    memberships=(),
    as_of="2026-04-01",
    mapping=None,
    cutoffs=(CUTOFF,),
):
    mapping = mapping or {value: value for value in ids}
    goldens = sorted(set(mapping.values()))
    tables = {
        "mapping.csv": [
            dict(source_customer_id=s, golden_customer_id=g) for s, g in mapping.items()
        ],
        "transactions.csv": list(transactions),
        "transaction_items.csv": list(items),
        "membership_events.csv": list(memberships),
    }
    with tempfile.TemporaryDirectory() as tmp:
        inbound = Path(tmp)
        (inbound / "generation_manifest.json").write_text(
            json.dumps({"as_of_date": as_of}), encoding="utf-8"
        )
        with (
            patch(
                f"{MODULE}.build_profiles",
                return_value=[dict(golden_customer_id=g) for g in goldens],
            ),
            patch(f"{MODULE}.read", side_effect=lambda p: tables[p.name]),
        ):
            rows = build_propensity_labels(inbound, Path("resolution"), list(cutoffs))
    return {row["golden_customer_id"]: row for row in rows}


class RetailPurchase30Tests(unittest.TestCase):
    def setUp(self):
        self.ids = (
            "at_cutoff",
            "at_30",
            "after_30",
            "cancelled",
            "refunded",
            "service_only",
            "mixed",
            "partial",
            "replay",
        )
        history = [tx(f"h-{i}", i, -10) for i in self.ids]
        future = [
            tx("f1", "at_cutoff", 0),
            tx("f2", "at_30", 30),
            tx("f3", "after_30", 30 + 1e-4),
            tx("f4", "cancelled", 5, "CANCELLED"),
            tx("f5", "refunded", 5, "REFUNDED"),
            tx("f6", "service_only", 5),
            tx("f7", "mixed", 5),
            tx("f8", "partial", 5, "PARTIAL_REFUND"),
            # Replay of a SERVICE-only row; product line lives on the duplicate.
            tx("f9", "replay", 5),
            tx("f9b", "replay", 5),
        ]
        items = [
            item(t, "PRODUCT") for t in ("f1", "f2", "f3", "f4", "f5", "f8", "f9b")
        ] + [
            item("f6", "SERVICE"),
            item("f7", "SERVICE"),
            item("f7", "PRODUCT"),
            item("f9", "SERVICE"),
        ]
        self.rows = build(self.ids, history + future, items)

    def test_window_boundaries_and_statuses(self):
        r = self.rows
        self.assertEqual(r["at_cutoff"]["retail_purchase30"], 0)
        self.assertEqual(r["at_30"]["retail_purchase30"], 1)
        self.assertEqual(r["after_30"]["retail_purchase30"], 0)
        self.assertEqual(r["cancelled"]["retail_purchase30"], 0)
        self.assertEqual(r["refunded"]["retail_purchase30"], 0)
        self.assertEqual(r["partial"]["retail_purchase30"], 1)
        self.assertEqual(r["at_30"]["retail_label_version"], RETAIL_VERSION)

    def test_service_only_not_positive_mixed_positive(self):
        self.assertEqual(self.rows["service_only"]["retail_purchase30"], 0)
        self.assertEqual(self.rows["mixed"]["retail_purchase30"], 1)
        self.assertEqual(self.rows["replay"]["retail_purchase30"], 1)

    def test_ineligible_and_incomplete_are_none(self):
        rows = build(
            ("old", "never", "ecom", "cancelled_hist"),
            [
                tx("o", "old", -365),
                tx("e", "ecom", -5, system="ECOM"),
                tx("c", "cancelled_hist", -5, "CANCELLED"),
                tx("of", "old", 5),
            ],
            [item("of", "PRODUCT")],
        )
        for golden in ("old", "never", "ecom", "cancelled_hist"):
            self.assertFalse(rows[golden]["retail_purchase30_eligible"], golden)
            self.assertIsNone(rows[golden]["retail_purchase30"], golden)
        incomplete = build(
            ("a",),
            [tx("h", "a", -1), tx("f", "a", 5)],
            [item("f", "PRODUCT")],
            as_of="2026-01-30",
        )["a"]
        self.assertTrue(incomplete["retail_purchase30_eligible"])
        self.assertFalse(incomplete["retail_purchase30_outcome_complete"])
        self.assertIsNone(incomplete["retail_purchase30"])
        complete = build(
            ("a",),
            [tx("h", "a", -1), tx("f", "a", 5)],
            [item("f", "PRODUCT")],
            as_of="2026-01-31",
        )["a"]
        self.assertEqual(complete["retail_purchase30"], 1)

    def test_two_sources_map_to_one_golden(self):
        rows = build(
            (),
            [tx("h", "s1", -3), tx("f", "s2", 3)],
            [item("f", "PRODUCT")],
            mapping={"s1": "G", "s2": "G"},
        )
        self.assertEqual(list(rows), ["G"])
        self.assertEqual(rows["G"]["retail_purchase30"], 1)

    def test_unknown_reference_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown transaction"):
            build(("a",), [tx("x", "ghost", -1)])
        with self.assertRaisesRegex(ValueError, "Unknown customer reference"):
            build(("a",), memberships=[member("ghost", "JOIN", -1, 10)])


class Renewal60Tests(unittest.TestCase):
    def test_eligibility_window_boundaries(self):
        cases = {
            "exp_minus_30": -30,  # outside (cutoff-30d, ...]
            "exp_minus_29": -29,
            "exp_at_cutoff": 0,
            "exp_at_60": 60,
            "exp_after_60": 61,
        }
        rows = build(
            tuple(cases),
            memberships=[member(k, "JOIN", -300, v) for k, v in cases.items()],
        )
        self.assertFalse(rows["exp_minus_30"]["renewal60_eligible"])
        self.assertTrue(rows["exp_minus_29"]["renewal60_eligible"])
        self.assertTrue(rows["exp_at_cutoff"]["renewal60_eligible"])
        self.assertTrue(rows["exp_at_60"]["renewal60_eligible"])
        self.assertFalse(rows["exp_after_60"]["renewal60_eligible"])
        self.assertIsNone(rows["exp_after_60"]["renewal60"])
        self.assertEqual(rows["exp_at_60"]["renewal60"], 0)
        self.assertEqual(rows["exp_at_60"]["renewal_label_version"], RENEWAL_VERSION)

    def test_latest_event_at_or_before_cutoff_drives_eligibility(self):
        rows = build(
            ("renewed_far", "no_member", "future_join"),
            memberships=[
                member("renewed_far", "JOIN", -400, 10),
                member("renewed_far", "RENEWAL", -5, 360),
                member("future_join", "JOIN", 1, 20),
            ],
        )
        self.assertFalse(rows["renewed_far"]["renewal60_eligible"])
        self.assertFalse(rows["no_member"]["renewal60_eligible"])
        self.assertFalse(rows["future_join"]["renewal60_eligible"])
        self.assertIsNone(rows["no_member"]["renewal60"])

    def test_outcome_boundaries_and_join_not_renewal(self):
        ids = ("at_cutoff", "at_60", "after_60", "join_only", "upgrade")
        memberships = [member(i, "JOIN", -300, 30) for i in ids] + [
            member("at_cutoff", "RENEWAL", 0, 20),
            member("at_60", "RENEWAL", 60, 425),
            member("after_60", "RENEWAL", 60 + 1e-4, 425),
            member("join_only", "JOIN", 10, 375),
            # Tier change on a RENEWAL counts only as renewal, never as upgrade.
            member("upgrade", "RENEWAL", 20, 385, tier="PLATINUM"),
        ]
        rows = build(ids, memberships=memberships)
        self.assertEqual(rows["at_cutoff"]["renewal60"], 0)
        self.assertEqual(rows["at_60"]["renewal60"], 1)
        self.assertEqual(rows["after_60"]["renewal60"], 0)
        self.assertEqual(rows["join_only"]["renewal60"], 0)
        self.assertEqual(rows["upgrade"]["renewal60"], 1)
        self.assertFalse(any("upgrade" in key for key in rows["upgrade"]))

    def test_incomplete_horizon_is_none_and_targets_independent(self):
        rows = build(
            ("a",),
            [tx("h", "a", -1), tx("f", "a", 5)],
            [item("f", "PRODUCT")],
            [member("a", "JOIN", -300, 10), member("a", "RENEWAL", 5, 375)],
            as_of="2026-02-15",
        )
        self.assertEqual(rows["a"]["retail_purchase30"], 1)
        self.assertFalse(rows["a"]["renewal60_outcome_complete"])
        self.assertIsNone(rows["a"]["renewal60"])

    def test_two_sources_map_to_one_golden(self):
        rows = build(
            (),
            memberships=[
                member("s1", "JOIN", -300, 20),
                member("s2", "RENEWAL", 15, 385),
            ],
            mapping={"s1": "G", "s2": "G"},
        )
        self.assertTrue(rows["G"]["renewal60_eligible"])
        self.assertEqual(rows["G"]["renewal60"], 1)


class BookingTests(unittest.TestCase):
    def test_booking_unsupported_service_items_and_visits_never_label(self):
        self.assertEqual(booking_status()["status"], UNSUPPORTED_SOURCE)
        rows = build(
            ("a",),
            [tx("h", "a", -1), tx("f", "a", 5)],
            [item("f", "SERVICE")],
        )
        self.assertFalse(any("booking" in key for key in rows["a"]))
        self.assertEqual(rows["a"]["retail_purchase30"], 0)
        features = [dict(golden_customer_id="a", cutoff_at=CUTOFF.isoformat())]
        with self.assertRaisesRegex(ValueError, UNSUPPORTED_SOURCE):
            join_propensity_training_rows(
                features, list(rows.values()), "service_booking30"
            )


class JoinTests(unittest.TestCase):
    def test_join_filters_per_target_and_rejects_unknown(self):
        ids = ("both", "retail_only", "neither")
        rows = build(
            ids,
            [tx("h1", "both", -1), tx("h2", "retail_only", -1)],
            memberships=[member("both", "JOIN", -300, 10)],
        )
        labels = list(rows.values())
        features = [
            dict(golden_customer_id=i, cutoff_at=CUTOFF.isoformat(), recency_days=1)
            for i in ids
        ]
        retail = join_propensity_training_rows(features, labels, "retail_purchase30")
        renewal = join_propensity_training_rows(features, labels, "renewal60")
        self.assertEqual(
            [r["golden_customer_id"] for r in retail], ["both", "retail_only"]
        )
        self.assertEqual([r["golden_customer_id"] for r in renewal], ["both"])
        row = renewal[0]
        self.assertEqual(row["target"], "renewal60")
        self.assertEqual(row["target_version"], RENEWAL_VERSION)
        self.assertEqual(row["horizon_days"], 60)
        self.assertEqual(row["recency_days"], 1)
        self.assertIs(row["experiment_ready"], False)
        self.assertTrue(row["eligible"] and row["outcome_complete"])
        self.assertEqual(row["target_value"], 0)
        self.assertNotIn("target", features[0])
        with self.assertRaisesRegex(ValueError, "Unknown propensity target"):
            join_propensity_training_rows(features, labels, "churn90")
        with self.assertRaisesRegex(ValueError, "exactly match"):
            join_propensity_training_rows(features[:1], labels, "renewal60")


class CliTests(unittest.TestCase):
    def test_manifest_checksums_counts_and_refusals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound, resolution, output = (
                root / p for p in ("inbound", "resolution", "output")
            )
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=30,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", resolution, synthetic_aliases=True)
            cutoffs = [
                datetime.fromisoformat("2026-03-01T00:00:00+07:00"),
                datetime.fromisoformat("2026-08-01T00:00:00+07:00"),
            ]
            result = run(inbound, resolution, output, cutoffs)
            manifest = json.loads(
                (output / "propensity_manifest.json").read_text(encoding="utf-8")
            )
            for flag in ("training_ready", "experiment_ready", "final_model"):
                self.assertIs(manifest[flag], False)
            self.assertIs(manifest["development_only"], True)
            self.assertEqual(
                manifest["target_versions"],
                {"retail_purchase30": RETAIL_VERSION, "renewal60": RENEWAL_VERSION},
            )
            self.assertIn("PROPOSED", manifest["proposed_rules"]["renewal60"])
            self.assertEqual(manifest["booking"]["status"], UNSUPPORTED_SOURCE)
            for name, digest in manifest["output_sha256"].items():
                self.assertEqual(digest, sha256(output / name))
            for path, digest in manifest["input_sha256"].items():
                self.assertEqual(digest, sha256(Path(path)))
            names = {Path(p).name for p in manifest["input_sha256"]}
            self.assertTrue(
                {
                    "transactions.csv",
                    "transaction_items.csv",
                    "membership_events.csv",
                    "mapping.csv",
                    "resolution_manifest.json",
                }
                <= names
            )
            with (output / "propensity_labels.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                label_rows = list(csv.DictReader(stream))
            self.assertEqual(len(label_rows), result["label_rows"])
            for target, counts in manifest["row_counts"].items():
                self.assertEqual(counts["total"], len(label_rows))
                self.assertEqual(
                    counts["eligible"] + counts["ineligible"], counts["total"]
                )
                self.assertEqual(
                    counts["complete"] + counts["incomplete"], counts["total"]
                )
                self.assertEqual(
                    counts["positives"],
                    sum(r[target] == "1" for r in label_rows),
                )
            # Late cutoff + 60d is past as_of -> renewal incomplete, null.
            late = [r for r in label_rows if r["cutoff_at"].startswith("2026-08")]
            self.assertTrue(all(r["renewal60"] == "" for r in late))
            with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
                run(inbound, resolution, output, cutoffs)
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                run(inbound, resolution, root / "ground_truth" / "out", cutoffs)
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                run(root / "ground_truth", resolution, root / "o2", cutoffs)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                run(root / "missing", resolution, root / "o3", cutoffs)
            with self.assertRaisesRegex(ValueError, "separate from inputs"):
                run(inbound, resolution, inbound / "nested", cutoffs)
            self.assertFalse((root / "o2").exists())
            self.assertFalse((root / "o3").exists())


if __name__ == "__main__":
    unittest.main()
