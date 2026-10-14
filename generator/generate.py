"""Generate deterministic synthetic customer intelligence source data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import re
import sys
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

NAMESPACE = uuid.UUID("e752ae52-a0fa-4c02-87b5-8274778ce746")
GENERATOR_VERSION = "2.0.0"
SCHEMA_VERSION = "2.0.0"
DEFAULT_SEED = 20260906
JAKARTA_TZ = timezone(timedelta(hours=7), name="Asia/Jakarta")
OBSERVATION_DAYS = 548
REGIONS = {
	"DI Yogyakarta": ["Yogyakarta", "Sleman", "Bantul", "Kulon Progo", "Gunungkidul"],
	"Jawa Tengah": ["Magelang", "Klaten", "Solo", "Semarang", "Purworejo"],
	"Jawa Timur": ["Surabaya", "Malang", "Kediri", "Madiun", "Jember"],
	"Jawa Barat": ["Bandung", "Bogor", "Depok", "Bekasi", "Cirebon"],
}
TRAJECTORIES = ("LOYAL_STABLE", "DECLINING", "ONE_TIME", "SEASONAL", "NEW", "DORMANT")
TRAJECTORY_PROBABILITIES = (0.22, 0.19, 0.17, 0.14, 0.14, 0.14)
SOURCE_SYSTEMS = ("CRM", "POS", "APP")
FIRST_NAMES = ("Adi", "Agus", "Ayu", "Budi", "Citra", "Dewi", "Dian", "Eka", "Fitri", "Hana", "Indra", "Intan", "Lina", "Made", "Nadia", "Raka", "Sari", "Tari", "Wahyu", "Yuni")
LAST_NAMES = ("Adinata", "Anggraini", "Darmawan", "Hidayat", "Kusuma", "Mahendra", "Permata", "Prasetyo", "Putra", "Putri", "Santoso", "Setiawan", "Utami", "Wijaya", "Wulandari")
PRODUCTS = (
	"Daily Cleanser", "Hydrating Lotion", "Hair Shampoo", "Hair Conditioner", "Body Wash",
	"Hand Cream", "Sunscreen Lotion", "Lip Balm", "Hair Serum", "Body Lotion",
	"Face Towel", "Travel Pouch", "Comb", "Nail Care Set", "Reusable Bottle",
)
SERVICE_TYPES = ("Haircut", "Hair Styling", "Hair Coloring", "Manicure", "Pedicure", "Makeup")
CASE_CATEGORIES = ("BOOKING_DELAY", "BILLING", "STAFF_SERVICE", "PRODUCT_AVAILABILITY")
APP_EVENT_TYPES = ("APP_OPEN", "PRODUCT_VIEW", "SEARCH", "CART_ADD")
CRM_FIELDS = (
	"crm_customer_id", "full_name", "phone_raw", "email_raw", "birth_month", "gender",
	"city", "member_code", "membership_tier", "join_date", "preferred_branch_code",
	"status", "source_updated_at",
)
CRM_GENDERS = ("F", "M", "U")
MEMBERSHIP_TIERS = ("BRONZE", "SILVER", "GOLD", "PLATINUM")
CUSTOMER_STATUSES = ("ACTIVE", "INACTIVE", "CLOSED")
TRANSACTION_STATUSES = ("COMPLETED", "CANCELLED", "REFUNDED", "PARTIAL_REFUND")
MEMBERSHIP_EVENT_FIELDS = (
	"event_id", "source_customer_ref", "member_code", "event_type", "occurred_at",
	"period_start", "expires_at", "membership_tier", "previous_event_id",
)
VISIT_FIELDS = (
	"visit_id", "source_customer_ref", "source_transaction_id", "branch_code",
	"visit_datetime", "status",
)


class RandomSource:
	"""Single stdlib MT19937 stream; reproducibility scoped to the same Python runtime."""

	def __init__(self, seed: int) -> None:
		self.generator = random.Random(seed)

	def random(self) -> float:
		return float(self.generator.random())

	def integer(self, low: int, high: int | None = None) -> int:
		if high is None:
			return int(self.generator.randrange(low))
		return int(self.generator.randrange(low, high))

	def choice(self, values: tuple[Any, ...] | list[Any], probabilities: tuple[float, ...] | None = None) -> Any:  # noqa: ANN401
		if probabilities is None:
			return values[self.integer(len(values))]
		threshold = self.random()
		cumulative = 0.0
		for value, probability in zip(values, probabilities):
			cumulative += probability
			if threshold < cumulative:
				return value
		return values[-1]

	def gamma(self, shape: float, scale: float) -> float:
		return float(self.generator.gammavariate(shape, scale))

	@staticmethod
	def rng_name() -> str:
		return "stdlib:random.Random (MT19937)"


class CsvSink:
	"""Stream deterministic UTF-8 CSV; header is written even when there are no rows."""

	def __init__(self, path: Path, fields: tuple[str, ...]) -> None:
		self.path = path
		self.fields = fields
		self.count = 0
		self.stream = path.open("w", newline="", encoding="utf-8")
		self.writer = csv.DictWriter(self.stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
		self.writer.writeheader()

	def write(self, row: dict[str, Any]) -> None:
		self.count += 1
		self.writer.writerow(row)

	def flush(self) -> None:
		self.stream.flush()

	def close(self) -> None:
		self.stream.close()


def stable_id(seed: int, kind: str, index: int | str) -> str:
	return str(uuid.uuid5(NAMESPACE, f"{seed}:{kind}:{index}"))


def as_of_bounds(as_of: date) -> tuple[datetime, datetime]:
	start = datetime.combine(as_of - timedelta(days=OBSERVATION_DAYS), time.min, tzinfo=JAKARTA_TZ)
	end = datetime.combine(as_of, time(hour=23, minute=59, second=59), tzinfo=JAKARTA_TZ)
	return start, end


def random_moment(rng: RandomSource, start: datetime, end: datetime) -> datetime:
	span = max(1, int((end - start).total_seconds()) + 1)
	return start + timedelta(seconds=rng.integer(span))


def customer_start(row: Mapping[str, Any], start: datetime) -> datetime:
	return max(start, datetime.combine(date.fromisoformat(str(row["join_date"])), time.min, tzinfo=JAKARTA_TZ))


def iso_datetime(value: datetime) -> str:
	if value.tzinfo is None:
		value = value.replace(tzinfo=JAKARTA_TZ)
	return value.astimezone(JAKARTA_TZ).replace(microsecond=0).isoformat()


def json_value(value: Any) -> str:
	return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def safe_slug(value: str) -> str:
	return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".") or "customer"


class NameFactory:
	def __init__(self, seed: int) -> None:
		self.seed = seed

	def name(self, rng: RandomSource) -> str:
		return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def typo_name(name: str, rng: RandomSource) -> str:
	words = name.split()
	if not words:
		return name
	word_index = rng.integer(len(words))
	word = words[word_index]
	if len(word) < 4:
		return name
	position = rng.integer(1, len(word) - 1)
	if rng.random() < 0.5:
		word = word[:position] + word[position + 1:]
	else:
		word = word[:position] + word[position + 1] + word[position] + word[position + 2:]
	words[word_index] = word
	return " ".join(words)


def make_phone(rng: RandomSource) -> str:
	national = "8" + "".join(str(rng.integer(10)) for _ in range(10))
	return f"+62{national}" if rng.random() < 0.5 else f"0{national}"


def format_phone(phone: str, rng: RandomSource) -> str:
	digits = re.sub(r"\D", "", phone)
	national = digits[2:] if digits.startswith("62") else digits[1:]
	prefix = "+62" if rng.random() < 0.5 else "0"
	if rng.random() < 0.5:
		return f"{prefix}{national}"
	separator = " " if rng.random() < 0.5 else "-"
	return f"{prefix}{national[:3]}{separator}{national[3:7]}{separator}{national[7:]}"


def make_email(name: str, index: int, rng: RandomSource) -> str:
	slug = safe_slug(name)
	domains = ("example.id", "mail.id", "inbox.id", "customer.test")
	# Canonical addresses are deterministic and unique by index; variants only add decoration.
	return f"{slug}.{index:06d}@{rng.choice(domains)}"


def make_branches(rng: RandomSource, seed: int, output: CsvSink) -> list[dict[str, Any]]:
	branches: list[dict[str, Any]] = []
	for region_index, (region, cities) in enumerate(REGIONS.items()):
		for branch_in_region in range(5):
			index = region_index * 5 + branch_in_region
			row = {
				"branch_code": f"BR-{index + 1:02d}",
				"branch_name": f"VTEKI {cities[branch_in_region % len(cities)]} {branch_in_region + 1}",
				"city": cities[branch_in_region % len(cities)],
				"region": region,
				"active_flag": True,
			}
			branches.append(row)
			output.write(row)
	return branches


def make_catalogue(seed: int, rng: RandomSource, output: CsvSink) -> list[dict[str, Any]]:
	items: list[dict[str, Any]] = []
	retail_categories = ("PERSONAL_CARE", "HAIR_CARE", "ACCESSORIES", "NAIL_CARE")
	for index in range(160):
		is_retail = index < 100
		if is_retail:
			name = f"{PRODUCTS[index % len(PRODUCTS)]} {index // len(PRODUCTS) + 1:02d}"
			category = retail_categories[index % len(retail_categories)]
			price = rng.integer(25_000, 650_001)
			duration = ""
			facts = {"item_type": "retail_product", "currency": "IDR", "size_ml": rng.choice((50, 100, 150, 250))}
			suitability = ["retail", "all_branches"]
		else:
			service_index = index - 100
			service = SERVICE_TYPES[service_index % len(SERVICE_TYPES)]
			name = f"{service} Session {service_index // len(SERVICE_TYPES) + 1:02d}"
			category = "PERSONAL_CARE"
			duration = rng.choice((30, 45, 60, 90))
			price = rng.integer(75_000, 900_001)
			facts = {"item_type": "non_medical_service", "currency": "IDR", "duration_minutes": duration}
			suitability = ["appointment_required", "non_medical", "all_branches"]
		row = {
			"item_code": f"ITM-{index + 1:04d}",
			"item_type": "PRODUCT" if is_retail else "SERVICE",
			"name": name,
			"category": category,
			"subcategory": "RETAIL_GOODS" if is_retail else SERVICE_TYPES[(index - 100) % len(SERVICE_TYPES)].upper().replace(" ", "_"),
			"list_price": price,
			"duration_minutes": duration,
			"availability_flag": rng.random() >= 0.04,
			"approved_facts": json_value(facts),
			"suitability_flags": json_value(suitability),
			"status": "ACTIVE" if rng.random() >= 0.03 else "DISCONTINUED",
		}
		items.append(row)
		output.write(row)
	return items


def make_customers(
	seed: int,
	customer_count: int,
	duplicate_count: int,
	start: datetime,
	end: datetime,
	rng: RandomSource,
	names: NameFactory,
	customer_output: CsvSink,
	truth_output: CsvSink,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
	source_rows: list[dict[str, Any]] = []
	golden_ids: list[str] = []
	source_ids_by_golden: list[str] = []
	canonical: list[dict[str, Any]] = []
	shared_phone_by_index: dict[int, str] = {}
	used_phones: set[str] = set()

	for index in range(0, customer_count - 1, 100):
		if rng.random() < 0.35:
			shared = make_phone(rng)
			shared_phone_by_index[index] = shared
			shared_phone_by_index[index + 1] = shared
			used_phones.add(re.sub(r"\D", "", shared))

	for index in range(customer_count):
		golden_id = stable_id(seed, "golden-customer", index)
		name = names.name(rng)
		if index in shared_phone_by_index:
			phone = shared_phone_by_index[index]
		else:
			phone = make_phone(rng)
			while re.sub(r"\D", "", phone) in used_phones:
				phone = make_phone(rng)
			used_phones.add(re.sub(r"\D", "", phone))
		city = rng.choice(tuple(city for cities in REGIONS.values() for city in cities))
		created_at = random_moment(rng, start, end)
		updated_at = random_moment(rng, created_at, end)
		has_membership = rng.random() >= 0.20
		canonical.append({
			"golden_id": golden_id,
			"name": name,
			"phone": phone,
			"email": make_email(name, index, rng),
			"birth_month": rng.integer(1, 13),
			"gender": rng.choice(CRM_GENDERS),
			"member_code": f"MBR-{seed % 100:02d}-{index + 1:06d}" if has_membership else "",
			"membership_tier": rng.choice(MEMBERSHIP_TIERS) if has_membership else "",
			"join_date": created_at.date().isoformat(),
			"preferred_branch_code": f"BR-{rng.integer(1, 21):02d}",
			"status": rng.choice(CUSTOMER_STATUSES, (0.84, 0.12, 0.04)),
			"source_updated_at": iso_datetime(updated_at),
			"city": city,
		})
		golden_ids.append(golden_id)

	def add_source(source_index: int, customer_index: int, duplicate: bool) -> None:
		person = canonical[customer_index]
		source_system = rng.choice(SOURCE_SYSTEMS)
		source_id = stable_id(seed, "source-customer", source_index)
		name = typo_name(person["name"], rng) if duplicate and rng.random() < 0.48 else person["name"]
		email = str(person["email"])
		if duplicate and rng.random() < 0.35:
			local, domain = email.split("@")
			email = f"{local}+src{source_index}@{domain}"
		elif duplicate and rng.random() < 0.50:
			email = email.upper()
		phone = format_phone(person["phone"], rng)
		phone_raw = "" if rng.random() < 0.05 else phone
		email_raw = "" if rng.random() < 0.08 else email.lower()
		if email_raw and rng.random() < 0.20:
			email_raw = f" {email_raw} "
		source_row = {
			"crm_customer_id": source_id,
			"full_name": name,
			"phone_raw": phone_raw,
			"email_raw": email_raw,
			"birth_month": person["birth_month"],
			"gender": person["gender"],
			"city": person["city"],
			"member_code": person["member_code"],
			"membership_tier": person["membership_tier"],
			"join_date": person["join_date"],
			"preferred_branch_code": person["preferred_branch_code"],
			"status": person["status"],
			"source_updated_at": person["source_updated_at"],
		}
		customer_output.write(source_row)
		truth_output.write({
			"source_customer_id": source_id,
			"golden_customer_id": person["golden_id"],
			"source_system": source_system,
			"identity_scenario": "SHARED_PHONE_TRAP" if customer_index in shared_phone_by_index else ("DUPLICATE_VARIANT" if duplicate else "GOLDEN_SOURCE"),
		})
		source_rows.append(source_row)
		if not duplicate:
			source_ids_by_golden.append(source_id)

	for index in range(customer_count):
		add_source(index, index, False)
	for duplicate_index in range(duplicate_count):
		add_source(customer_count + duplicate_index, rng.integer(customer_count), True)
	return source_rows, golden_ids, source_ids_by_golden


def ramadan_windows(start: date, end: date) -> list[tuple[date, date]]:
	windows = []
	for year, month, day in ((2025, 2, 28), (2026, 2, 18), (2027, 2, 8)):
		first = date(year, month, day)
		last = first + timedelta(days=30)
		if last >= start and first <= end:
			windows.append((first, last))
	return windows


def seasonal_multiplier(value: date, windows: list[tuple[date, date]]) -> float:
	if any(first <= value <= last for first, last in windows):
		return 1.75
	if value.month in (6, 7, 12):
		return 1.25
	return 1.0


def injected_campaign_effects(start: date, end: date) -> dict[str, Any]:
	effects: list[dict[str, Any]] = []
	for first, last in ramadan_windows(start, end):
		effects.append({
			"campaign_id": f"RAMADAN_{first.year}",
			"effect_kind": "synthetic_purchase_frequency_uplift",
			"window_start": first.isoformat(),
			"window_end": last.isoformat(),
			"purchase_frequency_multiplier": 1.75,
		})
	year = start.year
	while year <= end.year:
		for month in (6, 7, 12):
			first = date(year, month, 1)
			next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
			last = next_month - timedelta(days=1)
			if last >= start and first <= end:
				effects.append({
					"campaign_id": f"HOLIDAY_{year}_{month:02d}",
					"effect_kind": "synthetic_purchase_frequency_uplift",
					"window_start": first.isoformat(),
					"window_end": last.isoformat(),
					"purchase_frequency_multiplier": 1.25,
				})
		year += 1
	return {
		"description": "Synthetic calendar effects applied to transaction interval generation.",
		"effects": effects,
	}


def transaction_dates(
	trajectory: str,
	start: datetime,
	end: datetime,
	rng: RandomSource,
	ramadan: list[tuple[date, date]],
) -> list[datetime]:
	span_days = max(1, (end - start).days)
	dates: list[datetime] = []
	if trajectory == "ONE_TIME":
		dates.append(start + timedelta(days=rng.integer(span_days)))
	elif trajectory == "SEASONAL":
		for month in (3, 7, 12):
			for year in (start.year, end.year):
				if not (start.year <= year <= end.year):
					continue
				day = min(rng.integer(1, 29), 28)
				moment = datetime(year, month, day, tzinfo=start.tzinfo)
				if start <= moment <= end:
					dates.extend(moment + timedelta(days=rng.integer(5)) for _ in range(rng.integer(2, 5)))
	elif trajectory == "NEW":
		activation = start + timedelta(days=int(span_days * 0.55))
		cursor = activation
		while cursor < end:
			cursor += timedelta(days=max(4.0, rng.gamma(2.2, 11.0)))
			if cursor < end:
				dates.append(cursor)
	elif trajectory == "DORMANT":
		dates.extend(start + timedelta(days=rng.integer(span_days)) for _ in range(rng.integer(1, 4)))
	else:
		cursor = start + timedelta(days=rng.integer(30))
		while cursor < end:
			elapsed = max(0.0, (cursor - start).total_seconds() / max(1.0, (end - start).total_seconds()))
			scale = 5.0 if trajectory == "LOYAL_STABLE" else 4.6 * (1.0 + 2.2 * elapsed)
			gap = max(2.0, rng.gamma(3.0, scale) / seasonal_multiplier(cursor.date(), ramadan))
			cursor += timedelta(days=gap)
			if cursor < end:
				dates.append(cursor)
	if trajectory not in ("ONE_TIME", "SEASONAL") and rng.random() < 0.22:
		dates.append(start + timedelta(days=rng.integer(span_days)))
	return sorted(dates)


def make_transactions(
	seed: int,
	customers: list[dict[str, Any]],
	branches: list[dict[str, Any]],
	catalogue: list[dict[str, Any]],
	start: datetime,
	end: datetime,
	rng: RandomSource,
	transaction_output: CsvSink,
	item_output: CsvSink,
	trajectory_output: CsvSink,
	duplicate_truth: CsvSink,
) -> Counter[str]:
	trajectories: Counter[str] = Counter()
	product_ids = [item["item_code"] for item in catalogue if item["item_type"] == "PRODUCT"]
	service_ids = [item["item_code"] for item in catalogue if item["item_type"] == "SERVICE"]
	item_types = {item["item_code"]: item["item_type"] for item in catalogue}
	prices = {item["item_code"]: item["list_price"] for item in catalogue}
	ramadan = ramadan_windows(start.date(), end.date())
	sequence = 0
	for customer_index, customer in enumerate(customers):
		crm_customer_id = str(customer["crm_customer_id"])
		joined = datetime.combine(date.fromisoformat(str(customer["join_date"])), time.min, tzinfo=JAKARTA_TZ)
		active_start = max(start, joined)
		trajectory = rng.choice(TRAJECTORIES, TRAJECTORY_PROBABILITIES)
		trajectories[trajectory] += 1
		trajectory_output.write({
			"golden_customer_id": stable_id(seed, "golden-customer", customer_index),
			"trajectory": trajectory,
			"observed_from": start.date().isoformat(),
			"observed_to": end.date().isoformat(),
		})
		dates = transaction_dates(trajectory, active_start, end, rng, ramadan)
		for occurred in dates:
			transaction_id = stable_id(seed, "transaction", sequence)
			sequence += 1
			branch = rng.choice(branches)
			source_system = rng.choice(("POS", "ECOM"))
			channel_code = "POS_STORE" if source_system == "POS" else rng.choice(("MOBILE_APP", "WEB_STORE"))
			line_count = rng.integer(1, 5)
			gross_amount = 0
			lines: list[dict[str, Any]] = []
			for line_number in range(line_count):
				item_code = rng.choice(service_ids if rng.random() < 0.12 else product_ids)
				quantity = rng.integer(1, 4)
				unit_price = prices[item_code]
				line_amount = quantity * unit_price
				gross_amount += line_amount
				lines.append({
					"source_item_id": stable_id(seed, "transaction-item", f"{sequence}:{line_number}"),
					"source_transaction_id": transaction_id,
					"item_type": item_types[item_code],
					"item_code": item_code,
					"qty": quantity,
					"unit_price": unit_price,
					"line_amount": line_amount,
				})
			discount_amount = rng.integer(0, gross_amount // 5 + 1)
			status = rng.choice(TRANSACTION_STATUSES, (0.94, 0.02, 0.02, 0.02))
			net_amount = gross_amount - discount_amount
			refund_amount = 0
			if status == "REFUNDED":
				refund_amount = net_amount
			elif status == "PARTIAL_REFUND":
				refund_amount = rng.integer(1, max(2, net_amount // 2 + 1))
			actual_revenue = 0 if status in ("CANCELLED", "REFUNDED") else net_amount - refund_amount
			transaction_row = {
				"source_transaction_id": transaction_id,
				"source_customer_ref": "" if rng.random() < 0.03 else crm_customer_id,
				"source_system": source_system,
				"branch_code": branch["branch_code"] if source_system == "POS" else "",
				"channel_code": channel_code,
				"transaction_datetime": iso_datetime(occurred),
				"gross_amount": gross_amount,
				"discount_amount": discount_amount,
				"net_amount": net_amount,
				"refund_amount": refund_amount,
				"actual_revenue": actual_revenue,
				"status": status,
			}
			transaction_output.write(transaction_row)
			duplicate_truth.write({
				"source_transaction_id": transaction_id,
				"golden_customer_id": stable_id(seed, "golden-customer", customer_index),
				"event_kind": "BUSINESS_TRANSACTION",
				"duplicate_group_id": transaction_id,
			})
			for line in lines:
				item_output.write(line)
			if rng.random() < 0.01:
				duplicate = dict(transaction_row)
				duplicate_id = stable_id(seed, "transaction-duplicate", sequence)
				duplicate["source_transaction_id"] = duplicate_id
				transaction_output.write(duplicate)
				duplicate_truth.write({
					"source_transaction_id": duplicate_id,
					"golden_customer_id": stable_id(seed, "golden-customer", customer_index),
					"event_kind": "DUPLICATE_BUSINESS_EVENT",
					"duplicate_group_id": transaction_id,
				})
				for line_number, line in enumerate(lines):
					duplicate_line = dict(line)
					duplicate_line["source_item_id"] = stable_id(seed, "transaction-item-duplicate", f"{sequence}:{line_number}")
					duplicate_line["source_transaction_id"] = duplicate_id
					item_output.write(duplicate_line)
	return trajectories


def make_app_events(seed: int, customers: list[dict[str, Any]], start: datetime, end: datetime, rng: RandomSource, output: CsvSink) -> None:
	sequence = 0
	for row in customers:
		source_id = str(row["crm_customer_id"])
		active_start = customer_start(row, start)
		if rng.random() > 0.34:
			continue
		for _ in range(rng.integer(1, 9)):
			occurred = random_moment(rng, active_start, end)
			event_type = rng.choice(APP_EVENT_TYPES)
			output.write({
				"event_id": stable_id(seed, "app-event", sequence),
				"source_customer_id": source_id,
				"event_type": event_type,
				"item_id": f"ITM-{rng.integer(1, 101):04d}" if event_type in ("PRODUCT_VIEW", "CART_ADD") else "",
				"occurred_at": iso_datetime(occurred),
				"channel": "APP",
			})
			sequence += 1


def make_service_cases(seed: int, customers: list[dict[str, Any]], start: datetime, end: datetime, rng: RandomSource, output: CsvSink) -> None:
	sequence = 0
	for row in customers:
		source_id = str(row["crm_customer_id"])
		active_start = customer_start(row, start)
		if rng.random() >= 0.035:
			continue
		for _ in range(1 + int(rng.random() < 0.12)):
			created = random_moment(rng, active_start, end)
			status = rng.choice(("OPEN", "IN_PROGRESS", "RESOLVED"), (0.08, 0.16, 0.76))
			closed = created + timedelta(days=rng.integer(1, 8))
			if status == "RESOLVED" and closed > end:
				status = "IN_PROGRESS"
			output.write({
				"source_case_id": stable_id(seed, "service-case", sequence),
				"source_customer_ref": source_id,
				"category": rng.choice(CASE_CATEGORIES),
				"severity": rng.choice(("LOW", "MEDIUM", "HIGH", "SEVERE"), (0.5, 0.3, 0.16, 0.04)),
				"status": status,
				"opened_at": iso_datetime(created),
				"closed_at": iso_datetime(closed) if status == "RESOLVED" else "",
				"resolution_code": rng.choice(("BOOKING_RESCHEDULED", "BILLING_ADJUSTED", "SERVICE_FOLLOWUP", "STOCK_UPDATED")) if status == "RESOLVED" else "",
			})
			sequence += 1


def make_consent_events(seed: int, customers: list[dict[str, Any]], start: datetime, end: datetime, rng: RandomSource, output: CsvSink) -> None:
	sequence = 0
	for row in customers:
		source_id = str(row["crm_customer_id"])
		active_start = customer_start(row, start)
		for purpose in ("MARKETING", "SERVICE"):
			for channel in ("EMAIL", "PUSH"):
				status = rng.choice(("OPT_IN", "OPT_OUT", "UNKNOWN"), (0.90, 0.06, 0.04))
				captured = random_moment(rng, active_start, end)
				output.write({
					"source_consent_id": stable_id(seed, "consent-event", sequence),
					"source_customer_ref": source_id,
					"purpose": purpose,
					"channel_code": channel,
					"state": status,
					"captured_at": iso_datetime(captured),
					"expires_at": iso_datetime(captured + timedelta(days=365)),
					"capture_source": rng.choice(("CRM", "POS", "APP")),
				})
				sequence += 1


def make_membership_events(seed: int, source_rows: list[dict[str, Any]], start: datetime, end: datetime, rng: RandomSource, output: CsvSink) -> None:
	try:
		from .business_events import make_membership_events as derive_memberships
	except ImportError:
		from business_events import make_membership_events as derive_memberships
	derive_memberships(seed, source_rows, start, end, rng, output)


def make_customer_visits(seed: int, transactions_path: Path, output: CsvSink) -> None:
	"""Derive observable visits without using evaluation truth."""
	try:
		from .business_events import make_customer_visits as derive_visits
	except ImportError:
		from business_events import make_customer_visits as derive_visits
	derive_visits(seed, transactions_path, output)


def checksum(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as stream:
		for block in iter(lambda: stream.read(1024 * 1024), b""):
			digest.update(block)
	return digest.hexdigest()


def create_sinks(directory: Path, schemas: dict[str, tuple[str, ...]]) -> dict[str, CsvSink]:
	return {name: CsvSink(directory / name, fields) for name, fields in schemas.items()}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Generate synthetic V-TEKI customer intelligence data.")
	parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
	parser.add_argument("--as-of-date", type=date.fromisoformat, default=date(2026, 9, 6), help="Inclusive simulation end YYYY-MM-DD (Asia/Jakarta).")
	parser.add_argument("--customers", type=int, default=50_000, help="Number of golden customers to generate.")
	parser.add_argument("--output-dir", default="./inbound/2026-09-06")
	parser.add_argument("--ground-truth-dir", default="./generator/ground_truth")
	args = parser.parse_args()
	if args.customers < 1:
		parser.error("--customers must be a positive integer")
	output_dir = Path(args.output_dir).resolve()
	truth_dir = Path(args.ground_truth_dir).resolve()
	if output_dir == truth_dir or output_dir in truth_dir.parents or truth_dir in output_dir.parents:
		parser.error("--output-dir and --ground-truth-dir must be separate, non-nested directories")
	args.output_dir = output_dir
	args.ground_truth_dir = truth_dir
	return args


def runtime_meta() -> dict[str, Any]:
	try:
		import importlib.metadata as meta
	except ImportError:
		meta = None  # type: ignore[assignment]
	packages: dict[str, Any] = {}
	for name in ("numpy", "pandas", "faker"):
		version = None
		if meta is not None:
			try:
				version = meta.version(name)  # type: ignore[attr-defined]
			except Exception:
				pass
		packages[name] = version
	return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": packages}


def run(args: argparse.Namespace) -> dict[str, Any]:
	rng = RandomSource(args.seed)
	names = NameFactory(args.seed)
	as_of: date = getattr(args, "as_of_date", None) or date(2026, 9, 6)
	start, end = as_of_bounds(as_of)
	args.output_dir.mkdir(parents=True, exist_ok=True)
	args.ground_truth_dir.mkdir(parents=True, exist_ok=True)

	inbound_schemas = {
		"crm_customers.csv": CRM_FIELDS,
		"branches.csv": ("branch_code", "branch_name", "city", "region", "active_flag"),
		"catalogue_items.csv": ("item_code", "item_type", "name", "category", "subcategory", "list_price", "duration_minutes", "availability_flag", "suitability_flags", "approved_facts", "status"),
		"transactions.csv": ("source_transaction_id", "source_customer_ref", "source_system", "branch_code", "channel_code", "transaction_datetime", "gross_amount", "discount_amount", "net_amount", "refund_amount", "actual_revenue", "status"),
		"transaction_items.csv": ("source_item_id", "source_transaction_id", "item_type", "item_code", "qty", "unit_price", "line_amount"),
		"app_events.csv": ("event_id", "source_customer_id", "event_type", "item_id", "occurred_at", "channel"),
		"service_cases.csv": ("source_case_id", "source_customer_ref", "category", "severity", "status", "opened_at", "closed_at", "resolution_code"),
		"consent_events.csv": ("source_consent_id", "source_customer_ref", "purpose", "channel_code", "state", "captured_at", "expires_at", "capture_source"),
		"membership_events.csv": MEMBERSHIP_EVENT_FIELDS,
		"customer_visits.csv": VISIT_FIELDS,
	}
	truth_schemas = {
		"identity_mapping.csv": ("source_customer_id", "golden_customer_id", "source_system", "identity_scenario"),
		"customer_latent_trajectories.csv": ("golden_customer_id", "trajectory", "observed_from", "observed_to"),
		"transaction_duplicates.csv": ("source_transaction_id", "golden_customer_id", "event_kind", "duplicate_group_id"),
	}
	inbound = create_sinks(args.output_dir, inbound_schemas)
	truth = create_sinks(args.ground_truth_dir, truth_schemas)
	duplicate_count = round(args.customers * 11_000 / 50_000)
	source_rows, _, _ = make_customers(
		args.seed, args.customers, duplicate_count, start, end, rng, names,
		inbound["crm_customers.csv"], truth["identity_mapping.csv"],
	)
	branches = make_branches(rng, args.seed, inbound["branches.csv"])
	catalogue = make_catalogue(args.seed, rng, inbound["catalogue_items.csv"])
	trajectories = make_transactions(
		args.seed, source_rows[:args.customers], branches, catalogue, start, end, rng,
		inbound["transactions.csv"], inbound["transaction_items.csv"], truth["customer_latent_trajectories.csv"],
		truth["transaction_duplicates.csv"],
	)
	make_app_events(args.seed, source_rows[:args.customers], start, end, rng, inbound["app_events.csv"])
	make_service_cases(args.seed, source_rows[:args.customers], start, end, rng, inbound["service_cases.csv"])
	make_consent_events(args.seed, source_rows, start, end, rng, inbound["consent_events.csv"])
	make_membership_events(args.seed, source_rows[:args.customers], start, end, rng, inbound["membership_events.csv"])
	inbound["transactions.csv"].flush()
	make_customer_visits(args.seed, args.output_dir / "transactions.csv", inbound["customer_visits.csv"])
	for sink in (*inbound.values(), *truth.values()):
		sink.close()
	checksums = {name: checksum(args.output_dir / name) for name in inbound_schemas}
	effect_data = injected_campaign_effects(start.date(), end.date())
	effect_path = args.ground_truth_dir / "injected_campaign_effects.json"
	effect_path.write_text(json.dumps(effect_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	truth_checksums = {
		name: checksum(args.ground_truth_dir / name)
		for name in sorted((*truth_schemas, "injected_campaign_effects.json"))
	}
	manifest = {
		"generator": "vteki-synthetic-data",
		"generator_version": GENERATOR_VERSION,
		"schema_version": SCHEMA_VERSION,
		"as_of_date": as_of.isoformat(),
		"timezone": "Asia/Jakarta (+07:00)",
		"observation_period": {"from": start.isoformat(), "to": end.isoformat(), "days": OBSERVATION_DAYS},
		"rng": {"implementation": rng.rng_name(), "optional_packages_affect_randomness": False},
		"runtime": runtime_meta(),
		"seed": args.seed,
		"golden_customers": args.customers,
		"duplicate_source_records": duplicate_count,
		"trajectory_distribution": dict(sorted(trajectories.items())),
		"tables": {
			name: {"row_count": inbound[name].count, "sha256": checksums[name], "schema_version": SCHEMA_VERSION}
			for name in sorted(inbound_schemas)
		},
		"ground_truth_tables": {
			name: {
				"row_count": truth[name].count if name in truth else None,
				"sha256": truth_checksums[name],
				"schema_version": SCHEMA_VERSION,
			}
			for name in sorted(truth_checksums)
		},
		"volumes": {name.removesuffix(".csv"): sink.count for name, sink in inbound.items()},
		"checksums_sha256": checksums,
		"ground_truth_checksums_sha256": truth_checksums,
	}
	manifest_path = args.output_dir / "generation_manifest.json"
	manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	return manifest


def main() -> None:
	args = parse_args()
	manifest = run(args)
	print(json.dumps({
		"output_dir": str(args.output_dir),
		"ground_truth_dir": str(args.ground_truth_dir),
		"volumes": manifest["volumes"],
	}, indent=2))


if __name__ == "__main__":
	main()
