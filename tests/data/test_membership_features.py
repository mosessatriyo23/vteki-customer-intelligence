"""PROPOSED development as-of membership features for the renewal60 experiment."""

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
from services.data.models.membership_features import (
    MEMBERSHIP_FEATURE_VERSION,
    build_membership_features,
    join_membership_features,
    run,
)

CUTOFF = datetime.fromisoformat("2026-01-01T00:00:00+07:00")
MODULE = "services.data.models.membership_features"


def ev(eid, ref, kind, occurred_days, tier="SILVER", prev="", expires_days=None):
    expires = occurred_days + 180 if expires_days is None else expires_days
    return dict(
        event_id=eid,
        source_customer_ref=ref,
        event_type=kind,
        occurred_at=(CUTOFF + timedelta(days=occurred_days)).isoformat(),
        expires_at=(CUTOFF + timedelta(days=expires)).isoformat(),
        membership_tier=tier,
        previous_event_id=prev,
    )


def build(ids, memberships=(), mapping=None, cutoffs=(CUTOFF,)):
    mapping = mapping or {value: value for value in ids}
    goldens = sorted(set(mapping.values()))
    tables = {
        "mapping.csv": [
            dict(source_customer_id=s, golden_customer_id=g) for s, g in mapping.items()
        ],
        "membership_events.csv": list(memberships),
    }
    with (
        patch(
            f"{MODULE}.build_profiles",
            return_value=[dict(golden_customer_id=g) for g in goldens],
        ),
        patch(f"{MODULE}.read", side_effect=lambda p: tables[p.name]),
    ):
        rows = build_membership_features(Path("in"), Path("res"), list(cutoffs))
    return {row["golden_customer_id"]: row for row in rows}


class FeatureTests(unittest.TestCase):
    def test_no_history_defaults(self):
        row = build(("a",))["a"]
        self.assertIs(row["has_membership_history"], False)
        for key in (
            "current_tier_ordinal",
            "days_since_last_membership_event",
            "days_to_expiry",
            "membership_tenure_days",
        ):
            self.assertIsNone(row[key], key)
        self.assertEqual(row["renewal_count_365d"], 0)
        self.assertIs(row["tier_upgraded_last_event"], False)
        self.assertEqual(row["feature_version"], MEMBERSHIP_FEATURE_VERSION)
        self.assertEqual(
            MEMBERSHIP_FEATURE_VERSION, "moses-membership-features-proposed-dev-1.0"
        )
        self.assertIs(row["training_ready"], False)
        self.assertEqual(row["cutoff_at"], CUTOFF.isoformat())

    def test_join_only_values(self):
        row = build(("a",), [ev("e1", "a", "JOIN", -100, "GOLD")])["a"]
        self.assertIs(row["has_membership_history"], True)
        self.assertEqual(row["current_tier_ordinal"], 2)
        self.assertEqual(row["days_since_last_membership_event"], 100)
        self.assertEqual(row["days_to_expiry"], 80)
        self.assertEqual(row["membership_tenure_days"], 100)
        self.assertEqual(row["renewal_count_365d"], 0)
        self.assertIs(row["tier_upgraded_last_event"], False)

    def test_tier_ordinals(self):
        ids = ("b", "s", "g", "p")
        tiers = dict(b="BRONZE", s="SILVER", g="GOLD", p="PLATINUM")
        rows = build(ids, [ev(f"e{i}", i, "JOIN", -1, tiers[i]) for i in ids])
        self.assertEqual([rows[i]["current_tier_ordinal"] for i in ids], [0, 1, 2, 3])

    def test_event_at_cutoff_visible_day_after_invisible(self):
        rows = build(
            ("at", "after"),
            [
                ev("e1", "at", "JOIN", 0, "GOLD"),
                ev("e2", "after", "JOIN", -200, "BRONZE"),
                ev("e3", "after", "RENEWAL", 1, "PLATINUM", "e2"),
            ],
        )
        self.assertIs(rows["at"]["has_membership_history"], True)
        self.assertEqual(rows["at"]["days_since_last_membership_event"], 0)
        after = rows["after"]
        self.assertEqual(after["current_tier_ordinal"], 0)
        self.assertEqual(after["days_since_last_membership_event"], 200)
        self.assertEqual(after["days_to_expiry"], -20)
        self.assertEqual(after["renewal_count_365d"], 0)
        self.assertIs(after["tier_upgraded_last_event"], False)

    def test_future_only_history_is_no_history(self):
        row = build(("a",), [ev("e1", "a", "JOIN", 1)])["a"]
        self.assertIs(row["has_membership_history"], False)
        self.assertIsNone(row["days_to_expiry"])

    def test_negative_days_to_expiry_not_clipped(self):
        row = build(("a",), [ev("e1", "a", "JOIN", -190)])["a"]
        self.assertEqual(row["days_to_expiry"], -10)
        self.assertEqual(row["days_since_last_membership_event"], 190)

    def test_renewal_count_365d_boundary(self):
        memberships = [
            ev("j", "a", "JOIN", -900),
            ev("r1", "a", "RENEWAL", -365, prev="j"),  # excluded, open lower bound
            ev("r2", "a", "RENEWAL", -364, prev="r1"),
            ev("r3", "a", "RENEWAL", 0, prev="r2"),  # included, closed upper bound
        ]
        self.assertEqual(build(("a",), memberships)["a"]["renewal_count_365d"], 2)

    def test_renewal_count_with_expired_membership_and_tenure_from_join(self):
        row = build(
            ("a",),
            [ev("j", "a", "JOIN", -500), ev("r", "a", "RENEWAL", -320, prev="j")],
        )["a"]
        self.assertEqual(row["renewal_count_365d"], 1)
        self.assertEqual(row["membership_tenure_days"], 500)
        self.assertLess(row["days_to_expiry"], 0)

    def test_tier_upgraded_cases(self):
        rows = build(
            ("up", "same", "join", "down"),
            [
                ev("u1", "up", "JOIN", -300, "SILVER"),
                ev("u2", "up", "RENEWAL", -10, "GOLD", "u1"),
                ev("s1", "same", "JOIN", -300, "SILVER"),
                ev("s2", "same", "RENEWAL", -10, "SILVER", "s1"),
                ev("j1", "join", "JOIN", -10, "PLATINUM"),
                ev("d1", "down", "JOIN", -300, "GOLD"),
                ev("d2", "down", "RENEWAL", -10, "BRONZE", "d1"),
            ],
        )
        self.assertIs(rows["up"]["tier_upgraded_last_event"], True)
        self.assertIs(rows["same"]["tier_upgraded_last_event"], False)
        self.assertIs(rows["join"]["tier_upgraded_last_event"], False)
        self.assertIs(rows["down"]["tier_upgraded_last_event"], False)

    def test_future_renewal_does_not_change_upgrade_flag(self):
        row = build(
            ("a",),
            [
                ev("e1", "a", "JOIN", -300, "SILVER"),
                ev("e2", "a", "RENEWAL", 5, "PLATINUM", "e1"),
            ],
        )["a"]
        self.assertIs(row["tier_upgraded_last_event"], False)

    def test_two_sources_one_golden(self):
        row = build(
            (),
            [
                ev("e1", "s1", "JOIN", -300, "SILVER"),
                ev("e2", "s2", "RENEWAL", -5, "GOLD", "e1"),
            ],
            mapping={"s1": "G", "s2": "G"},
        )["G"]
        self.assertEqual(row["current_tier_ordinal"], 2)
        self.assertEqual(row["membership_tenure_days"], 300)

    def test_one_row_per_customer_per_cutoff(self):
        later = CUTOFF + timedelta(days=30)
        tables = {
            "mapping.csv": [dict(source_customer_id="a", golden_customer_id="a")],
            "membership_events.csv": [ev("e1", "a", "JOIN", 10)],
        }
        with (
            patch(f"{MODULE}.read", side_effect=lambda p: tables[p.name]),
            patch(
                f"{MODULE}.build_profiles",
                return_value=[dict(golden_customer_id="a")],
            ),
        ):
            rows = build_membership_features(Path("in"), Path("res"), [later, CUTOFF])
        self.assertEqual(
            [r["cutoff_at"] for r in rows], [CUTOFF.isoformat(), later.isoformat()]
        )
        self.assertEqual([r["has_membership_history"] for r in rows], [False, True])

    def test_validation(self):
        with self.assertRaisesRegex(ValueError, "Unknown customer reference"):
            build(("a",), [ev("e1", "ghost", "JOIN", -1)])
        naive = datetime(2026, 1, 1)
        with self.assertRaises(ValueError):
            build(("a",), cutoffs=(naive,))
        with self.assertRaises(ValueError):
            build(("a",), cutoffs=(datetime.fromisoformat("2026-01-01T00:00:00Z"),))


class JoinTests(unittest.TestCase):
    def base(self):
        return [
            dict(
                golden_customer_id=g,
                cutoff_at=CUTOFF.isoformat(),
                feature_version="x",
                training_ready=False,
                recency_days=3,
            )
            for g in ("has", "none")
        ]

    def test_default_fill_and_passthrough(self):
        member_rows = list(build(("has",), [ev("e1", "has", "JOIN", -10)]).values())
        joined = {
            r["golden_customer_id"]: r
            for r in join_membership_features(self.base(), member_rows)
        }
        self.assertEqual(joined["has"]["recency_days"], 3)
        self.assertEqual(joined["has"]["feature_version"], "x")
        self.assertIs(joined["has"]["has_membership_history"], True)
        self.assertEqual(joined["has"]["membership_tenure_days"], 10)
        none = joined["none"]
        self.assertIs(none["has_membership_history"], False)
        self.assertIsNone(none["current_tier_ordinal"])
        self.assertIsNone(none["days_since_last_membership_event"])
        self.assertIsNone(none["days_to_expiry"])
        self.assertIsNone(none["membership_tenure_days"])
        self.assertEqual(none["renewal_count_365d"], 0)
        self.assertIs(none["tier_upgraded_last_event"], False)
        self.assertEqual(none["membership_feature_version"], MEMBERSHIP_FEATURE_VERSION)
        self.assertNotIn("has_membership_history", self.base()[0])

    def test_subset_violation_rejected(self):
        member_rows = list(build(("ghost",), [ev("e1", "ghost", "JOIN", -10)]).values())
        with self.assertRaisesRegex(ValueError, "subset"):
            join_membership_features(self.base(), member_rows)
        other = [dict(member_rows[0], golden_customer_id="has", cutoff_at="2027")]
        with self.assertRaisesRegex(ValueError, "subset"):
            join_membership_features(self.base(), other)


class CliTests(unittest.TestCase):
    def test_manifest_checksums_and_refusals(self):
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
                (output / "membership_manifest.json").read_text(encoding="utf-8")
            )
            self.assertIs(manifest["training_ready"], False)
            self.assertIs(manifest["development_only"], True)
            self.assertEqual(manifest["feature_version"], MEMBERSHIP_FEATURE_VERSION)
            for name, digest in manifest["output_sha256"].items():
                self.assertEqual(digest, sha256(output / name))
            for path, digest in manifest["input_sha256"].items():
                self.assertEqual(digest, sha256(Path(path)))
            self.assertIn(
                "membership_events.csv",
                {Path(p).name for p in manifest["input_sha256"]},
            )
            with (output / "membership_features.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), manifest["row_count"])
            self.assertEqual(len(rows), result["rows"])
            self.assertEqual({r["cutoff_at"][:7] for r in rows}, {"2026-03", "2026-08"})
            expected = sum(r["has_membership_history"] == "True" for r in rows)
            self.assertAlmostEqual(manifest["coverage"], expected / len(rows))
            self.assertGreater(manifest["coverage"], 0)
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

    def test_input_changed_during_run_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inbound, resolution, output = (
                root / p for p in ("inbound", "resolution", "output")
            )
            generate(
                argparse.Namespace(
                    seed=20260906,
                    customers=10,
                    as_of_date=date(2026, 9, 6),
                    output_dir=inbound,
                    ground_truth_dir=root / "truth",
                )
            )
            resolve(inbound / "crm_customers.csv", resolution, synthetic_aliases=True)

            def tamper(*args, **kwargs):
                with (inbound / "membership_events.csv").open("a") as stream:
                    stream.write("\n")
                return []

            with patch(f"{MODULE}.build_membership_features", side_effect=tamper):
                with self.assertRaisesRegex(ValueError, "Inputs changed"):
                    run(inbound, resolution, output, [CUTOFF])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
