"""Observable source CSV contract for synthetic generator schema 2.0.0.

No evaluation ground truth may be admitted to this pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableContract:
    fields: tuple[str, ...]
    pk: str
    references: tuple[tuple[str, str, str], ...] = ()
    nullable: frozenset[str] = frozenset()
    timestamps: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    nonnegative: tuple[str, ...] = ()
    positive: tuple[str, ...] = ()
    enums: tuple[tuple[str, frozenset[str]], ...] = ()


TABLES: dict[str, TableContract] = {
    "branches.csv": TableContract(
        ("branch_code", "branch_name", "city", "region", "active_flag"), "branch_code",
        enums=(("active_flag", frozenset({"True", "False"})),),
    ),
    "catalogue_items.csv": TableContract(
        ("item_code", "item_type", "name", "category", "subcategory", "list_price",
         "duration_minutes", "availability_flag", "suitability_flags", "approved_facts", "status"),
        "item_code", nullable=frozenset({"duration_minutes"}), positive=("list_price",),
        enums=(("item_type", frozenset({"PRODUCT", "SERVICE"})),
               ("status", frozenset({"ACTIVE", "DISCONTINUED"})),
               ("availability_flag", frozenset({"True", "False"}))),
    ),
    "crm_customers.csv": TableContract(
        ("crm_customer_id", "full_name", "phone_raw", "email_raw", "birth_month", "gender",
         "city", "member_code", "membership_tier", "join_date", "preferred_branch_code",
         "status", "source_updated_at"), "crm_customer_id",
        references=(("preferred_branch_code", "branches.csv", "branch_code"),),
        nullable=frozenset({"phone_raw", "email_raw", "member_code", "membership_tier"}),
        timestamps=("source_updated_at",), dates=("join_date",), positive=("birth_month",),
        enums=(("gender", frozenset({"F", "M", "U"})),
               ("status", frozenset({"ACTIVE", "INACTIVE", "CLOSED"}))),
    ),
    "transactions.csv": TableContract(
        ("source_transaction_id", "source_customer_ref", "source_system", "branch_code",
         "channel_code", "transaction_datetime", "gross_amount", "discount_amount",
         "net_amount", "refund_amount", "actual_revenue", "status"), "source_transaction_id",
        references=(("source_customer_ref", "crm_customers.csv", "crm_customer_id"),
                    ("branch_code", "branches.csv", "branch_code")),
        nullable=frozenset({"source_customer_ref", "branch_code"}),
        timestamps=("transaction_datetime",), positive=("gross_amount",),
        nonnegative=("discount_amount", "net_amount", "refund_amount", "actual_revenue"),
        enums=(("status", frozenset({"COMPLETED", "CANCELLED", "REFUNDED", "PARTIAL_REFUND"})),
               ("source_system", frozenset({"POS", "ECOM"}))),
    ),
    "transaction_items.csv": TableContract(
        ("source_item_id", "source_transaction_id", "item_type", "item_code", "qty",
         "unit_price", "line_amount"), "source_item_id",
        references=(("source_transaction_id", "transactions.csv", "source_transaction_id"),
                    ("item_code", "catalogue_items.csv", "item_code")),
        positive=("qty", "unit_price", "line_amount"),
        enums=(("item_type", frozenset({"PRODUCT", "SERVICE"})),),
    ),
    "app_events.csv": TableContract(
        ("event_id", "source_customer_id", "event_type", "item_id", "occurred_at", "channel"),
        "event_id", references=(("source_customer_id", "crm_customers.csv", "crm_customer_id"),
                                ("item_id", "catalogue_items.csv", "item_code")),
        nullable=frozenset({"item_id"}), timestamps=("occurred_at",),
        enums=(("event_type", frozenset({"APP_OPEN", "PRODUCT_VIEW", "SEARCH", "CART_ADD"})),
               ("channel", frozenset({"APP"}))),
    ),
    "service_cases.csv": TableContract(
        ("source_case_id", "source_customer_ref", "category", "severity", "status",
         "opened_at", "closed_at", "resolution_code"), "source_case_id",
        references=(("source_customer_ref", "crm_customers.csv", "crm_customer_id"),),
        nullable=frozenset({"closed_at", "resolution_code"}), timestamps=("opened_at", "closed_at"),
        enums=(("status", frozenset({"OPEN", "IN_PROGRESS", "RESOLVED"})),),
    ),
    "consent_events.csv": TableContract(
        ("source_consent_id", "source_customer_ref", "purpose", "channel_code", "state",
         "captured_at", "expires_at", "capture_source"), "source_consent_id",
        references=(("source_customer_ref", "crm_customers.csv", "crm_customer_id"),),
        timestamps=("captured_at", "expires_at"),
        enums=(("state", frozenset({"OPT_IN", "OPT_OUT", "UNKNOWN"})),
               ("purpose", frozenset({"MARKETING", "SERVICE"})),
               ("channel_code", frozenset({"EMAIL", "PUSH"}))),
    ),
    "membership_events.csv": TableContract(
        ("event_id", "source_customer_ref", "member_code", "event_type", "occurred_at",
         "period_start", "expires_at", "membership_tier", "previous_event_id"), "event_id",
        references=(("source_customer_ref", "crm_customers.csv", "crm_customer_id"),
                    ("previous_event_id", "membership_events.csv", "event_id")),
        nullable=frozenset({"previous_event_id"}),
        timestamps=("occurred_at", "period_start", "expires_at"),
        enums=(("event_type", frozenset({"JOIN", "RENEWAL"})),
               ("membership_tier", frozenset({"BRONZE", "SILVER", "GOLD", "PLATINUM"}))),
    ),
    "customer_visits.csv": TableContract(
        ("visit_id", "source_customer_ref", "source_transaction_id", "branch_code",
         "visit_datetime", "status"), "visit_id",
        references=(("source_customer_ref", "crm_customers.csv", "crm_customer_id"),
                    ("source_transaction_id", "transactions.csv", "source_transaction_id"),
                    ("branch_code", "branches.csv", "branch_code")),
        timestamps=("visit_datetime",), enums=(("status", frozenset({"COMPLETED"})),),
    ),
}

SCHEMA_VERSION = "2.0.0"
# Dependency order is deliberately part of the source contract.
LOAD_ORDER = tuple(TABLES)
