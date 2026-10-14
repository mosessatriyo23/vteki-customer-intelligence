"""Source business events; stdlib only, sinks are caller-owned CsvSink objects."""
from __future__ import annotations

import csv
from datetime import datetime, time, timedelta, timezone
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

# Standalone stdlib-only helpers; no imports from generate.py (which may load optional packages).
JAKARTA_TZ = timezone(timedelta(hours=7), name="Asia/Jakarta")
MEMBERSHIP_TIERS = ("BRONZE", "SILVER", "GOLD", "PLATINUM")
NAMESPACE = uuid.UUID("e752ae52-a0fa-4c02-87b5-8274778ce746")


def stable_id(seed: int, kind: str, index: str) -> str:
	return str(uuid.uuid5(NAMESPACE, f"{seed}:{kind}:{index}"))


def iso_datetime(value: datetime) -> str:
	if value.tzinfo is None:
		value = value.replace(tzinfo=JAKARTA_TZ)
	return value.astimezone(JAKARTA_TZ).replace(microsecond=0).isoformat()

MEMBERSHIP_FIELDS = (
	"event_id", "source_customer_ref", "member_code", "event_type", "occurred_at",
	"period_start", "expires_at", "membership_tier", "previous_event_id",
)
VISIT_FIELDS = (
	"visit_id", "source_customer_ref", "source_transaction_id", "branch_code",
	"visit_datetime", "status",
)


def transaction_fingerprint(row: Mapping[str, Any]) -> tuple[str, ...]:
	"""Business replay key, deliberately excludes transport transaction ID."""
	return tuple(str(row.get(key, "")).strip() for key in (
		"source_customer_ref", "source_system", "branch_code", "channel_code",
		"transaction_datetime", "gross_amount", "discount_amount", "net_amount", "status",
	))


def make_membership_events(seed: int, source_rows: Iterable[Mapping[str, Any]],
	start: datetime, end: datetime, rng: Any, output: Any) -> int:
	"""Emit join/renewal chains, not future expiry observations; return rows written.

	Join dates are business dates, not source_updated_at or clamped to observation
	start. Historical joins are needed to describe contracts active at start.
	Each CRM source has its own chain; no hidden identity mapping is consulted.
	"""
	if start.tzinfo is None:
		start = start.replace(tzinfo=JAKARTA_TZ)
	if end.tzinfo is None:
		end = end.replace(tzinfo=JAKARTA_TZ)
	if start > end:
		raise ValueError("start must not exceed end")
	count = 0
	seen = set()
	for row in source_rows:
		customer = str(row.get("crm_customer_id", "")).strip()
		member = str(row.get("member_code", "")).strip()
		if not customer or not member or customer in seen:
			continue
		seen.add(customer)
		joined = datetime.combine(datetime.fromisoformat(str(row["join_date"])).date(),
			time.min, tzinfo=end.tzinfo or JAKARTA_TZ)
		if joined > end:
			continue
		tier = str(row.get("membership_tier", ""))
		if tier not in MEMBERSHIP_TIERS:
			tier = "BRONZE"
		cursor, previous, sequence = joined, "", 0
		while cursor <= end:
			expiry = cursor + timedelta(days=180)
			event_id = stable_id(seed, "membership-event", f"{customer}:{sequence}")
			output.write({
				"event_id": event_id, "source_customer_ref": customer, "member_code": member,
				"event_type": "JOIN" if sequence == 0 else "RENEWAL",
				"occurred_at": iso_datetime(cursor), "period_start": iso_datetime(cursor),
				"expires_at": iso_datetime(expiry), "membership_tier": tier,
				"previous_event_id": previous,
			})
			count += 1
			# An expiry is contractual data, never an emitted future event.
			cursor = expiry + timedelta(days=1)
			if cursor > end or rng.random() >= 0.65:
				break
			position = MEMBERSHIP_TIERS.index(tier)
			if position < len(MEMBERSHIP_TIERS) - 1 and rng.random() < 0.20:
				tier = MEMBERSHIP_TIERS[position + 1]
			previous, sequence = event_id, sequence + 1
	return count


def make_customer_visits(seed: int, transactions_path: str | Path, output: Any,
	duplicate_map: Mapping[str, str] | None = None) -> int:
	"""One completed visit per eligible POS business transaction (first replay wins).

	Optional duplicate_map maps replay IDs to canonical IDs for deduplication only;
	links always reference an actual retained CSV transaction. Fingerprints are a
	source-only fallback and may collapse genuine identical purchases.
	"""
	seen_ids, seen_fingerprints = set(), set()
	count = 0
	with Path(transactions_path).open(newline="", encoding="utf-8") as stream:
		for row in csv.DictReader(stream):
			if (row["source_system"] != "POS" or row["status"] not in
				("COMPLETED", "PARTIAL_REFUND") or not row["source_customer_ref"].strip()):
				continue
			transaction_id = row["source_transaction_id"]
			key = (duplicate_map or {}).get(transaction_id, transaction_id)
			fingerprint = transaction_fingerprint(row)
			if key in seen_ids or fingerprint in seen_fingerprints:
				continue
			seen_ids.add(key)
			seen_fingerprints.add(fingerprint)
			output.write({
				"visit_id": stable_id(seed, "customer-visit", transaction_id),
				"source_customer_ref": row["source_customer_ref"],
				"source_transaction_id": transaction_id, "branch_code": row["branch_code"],
				"visit_datetime": row["transaction_datetime"], "status": "COMPLETED",
			})
			count += 1
	return count
