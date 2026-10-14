"""Point-in-time labels from observable source CSVs only (never ground truth)."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from .business_events import JAKARTA_TZ, transaction_fingerprint

LABEL_FIELDS = (
    "source_customer_ref",
    "prediction_at",
    "outcome_complete",
    "churn90",
    "retail30",
    "service30",
    "renewal60",
    "historical_net_amount",
    "future_net_amount",
    "historical_refund_adjusted_net",
    "future_refund_adjusted_net",
)


def _read(path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _net(row: dict[str, str]) -> float:
    """Observable refund-adjusted revenue with backward-compatible fallback."""
    try:
        if row.get("actual_revenue", "") != "":
            return float(row["actual_revenue"])
        net = float(row.get("net_amount", "0") or 0)
        refund = float(row.get("refund_amount", "0") or 0)
        return (
            max(0.0, net - refund)
            if row.get("status") not in ("CANCELLED", "REFUNDED")
            else 0.0
        )
    except ValueError:
        return 0.0


def make_labels(
    crm_path: str | Path,
    transactions_path: str | Path,
    transaction_items_path: str | Path,
    visits_path: str | Path,
    membership_events_path: str | Path,
    prediction_dates: Iterable[date | datetime | str],
    observation_end: date | datetime | str,
    output: Any,
) -> int:
    """Write one row per source customer per eligible prediction date.

    Prediction is at 00:00 on the supplied date (or exact datetime). Windows
    are (prediction_at, prediction_at + N days]. Incomplete windows have blank
    outcomes; a 90-day complete observation is required for all labels.
    Historical sums include qualifying events <= prediction_at. No truth joins.
    """
    customers = _read(crm_path)
    transactions = _read(transactions_path)
    items = _read(transaction_items_path)
    visits = _read(visits_path)
    memberships = _read(membership_events_path)
    if isinstance(observation_end, str):
        observation_end = (
            _moment(observation_end)
            if "T" in observation_end
            else date.fromisoformat(observation_end)
        )
    if isinstance(observation_end, date) and not isinstance(observation_end, datetime):
        observation_end = datetime.combine(observation_end, time.max, tzinfo=JAKARTA_TZ)
    item_types: dict[str, set[str]] = defaultdict(set)
    for item in items:
        item_types[item.get("source_transaction_id", "")].add(item.get("item_type", ""))
    by_customer: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_ids, seen_fingerprints = set(), set()
    for txn in transactions:
        key = txn.get("source_transaction_id", "")
        fingerprint = transaction_fingerprint(txn)
        if not key or key in seen_ids or fingerprint in seen_fingerprints:
            continue
        seen_ids.add(key)
        seen_fingerprints.add(fingerprint)
        if txn.get("source_customer_ref", "").strip():
            by_customer[txn["source_customer_ref"]].append(txn)
    visits_by_customer: dict[str, list[datetime]] = defaultdict(list)
    seen_visits = set()
    for visit in visits:
        if visit.get("status") != "COMPLETED":
            continue
        key = (
            visit.get("source_customer_ref"),
            visit.get("source_transaction_id"),
            visit.get("visit_datetime"),
        )
        if key in seen_visits:
            continue
        seen_visits.add(key)
        visits_by_customer[visit["source_customer_ref"]].append(
            _moment(visit["visit_datetime"])
        )
    members_by_customer: dict[str, list[datetime]] = defaultdict(list)
    seen_members = set()
    for event in memberships:
        if event.get("event_type") != "RENEWAL":
            continue
        key = event.get("event_id") or (
            event.get("source_customer_ref"),
            event.get("occurred_at"),
        )
        if key in seen_members:
            continue
        seen_members.add(key)
        members_by_customer[event["source_customer_ref"]].append(
            _moment(event["occurred_at"])
        )
    count = 0
    for raw_prediction in prediction_dates:
        prediction = (
            (
                _moment(raw_prediction)
                if "T" in raw_prediction
                else datetime.combine(date.fromisoformat(raw_prediction), time.min)
            )
            if isinstance(raw_prediction, str)
            else (
                datetime.combine(raw_prediction, time.min)
                if not isinstance(raw_prediction, datetime)
                else raw_prediction
            )
        )
        end = observation_end
        if prediction.tzinfo and end.tzinfo is None:
            end = end.replace(tzinfo=prediction.tzinfo)
        if end.tzinfo and prediction.tzinfo is None:
            prediction = prediction.replace(tzinfo=end.tzinfo)
        complete = end >= prediction + timedelta(days=90)
        for customer in customers:
            ref = customer.get("crm_customer_id", "").strip()
            if not ref or date.fromisoformat(customer["join_date"]) > prediction.date():
                continue

            def local(moment: datetime) -> datetime:
                if prediction.tzinfo and moment.tzinfo is None:
                    return moment.replace(tzinfo=prediction.tzinfo)
                if not prediction.tzinfo and moment.tzinfo:
                    return moment.replace(tzinfo=None)
                return moment

            historical = 0.0
            future = 0.0
            historical_pre_refund = 0.0
            future_pre_refund = 0.0
            activity = False
            retail = service = False
            for txn in by_customer[ref]:
                occurred = local(_moment(txn["transaction_datetime"]))
                status = txn.get("status")
                amount = _net(txn) if status in ("COMPLETED", "PARTIAL_REFUND") else 0.0
                pre_refund = (
                    float(txn.get("net_amount") or 0)
                    if status in ("COMPLETED", "PARTIAL_REFUND", "REFUNDED")
                    else 0.0
                )
                if occurred <= prediction:
                    historical += amount
                    historical_pre_refund += pre_refund
                elif occurred <= prediction + timedelta(days=90):
                    future += amount
                    future_pre_refund += pre_refund
                    if amount > 0:
                        activity = True
                        if occurred <= prediction + timedelta(days=30):
                            types = item_types.get(txn["source_transaction_id"], set())
                            retail |= "PRODUCT" in types
                            service |= "SERVICE" in types
            if not activity:
                activity = any(
                    prediction < local(t) <= prediction + timedelta(days=90)
                    for t in visits_by_customer[ref]
                )
            renewal = any(
                prediction < local(t) <= prediction + timedelta(days=60)
                for t in members_by_customer[ref]
            )
            activity |= any(
                prediction < local(t) <= prediction + timedelta(days=90)
                for t in members_by_customer[ref]
            )
            output.write(
                {
                    "source_customer_ref": ref,
                    "prediction_at": prediction.isoformat(),
                    "outcome_complete": int(complete),
                    "churn90": int(not activity) if complete else "",
                    "retail30": int(retail) if complete else "",
                    "service30": int(service) if complete else "",
                    "renewal60": int(renewal) if complete else "",
                    "historical_net_amount": historical_pre_refund,
                    "future_net_amount": future_pre_refund if complete else "",
                    "historical_refund_adjusted_net": historical,
                    "future_refund_adjusted_net": future if complete else "",
                }
            )
            count += 1
    return count
