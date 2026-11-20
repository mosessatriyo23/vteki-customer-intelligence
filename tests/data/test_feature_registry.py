"""K-03: immutable versioned feature definitions; restricted attributes rejected."""

import pytest

from services.data.features.registry import FeatureRegistry


def definition(**overrides):
    value = dict(
        feature_name="recency_days",
        feature_version="event-time-dev-1.0",
        description="Days since last purchase at the cutoff",
        source_fields=("transaction_date",),
        owner="moses",
    )
    value.update(overrides)
    return value


def test_new_definition_starts_draft_and_is_retrievable():
    registry = FeatureRegistry(restricted_attributes={"religion"})
    registry.register(**definition())
    entry = registry.get("recency_days", "event-time-dev-1.0")
    assert entry["state"] == "DRAFT"
    assert entry["source_fields"] == ("transaction_date",)


def test_draft_may_be_replaced_but_active_is_immutable():
    registry = FeatureRegistry(restricted_attributes=set())
    registry.register(**definition())
    registry.register(**definition(description="Clarified"))
    registry.activate("recency_days", "event-time-dev-1.0")
    with pytest.raises(ValueError, match="immutable"):
        registry.register(**definition(description="Edited in place"))
    registry.register(**definition(feature_version="event-time-dev-1.1"))
    assert registry.get("recency_days", "event-time-dev-1.0")["state"] == "ACTIVE"
    assert registry.get("recency_days", "event-time-dev-1.1")["state"] == "DRAFT"


def test_restricted_attribute_is_rejected_and_named():
    registry = FeatureRegistry(restricted_attributes={"religion"})
    with pytest.raises(ValueError, match="religion"):
        registry.register(**definition(source_fields=("religion", "transaction_date")))
    assert registry.list() == []


def test_restricted_matching_is_case_and_space_insensitive():
    registry = FeatureRegistry(restricted_attributes={"Religion"})
    with pytest.raises(ValueError, match="RELIGION"):
        registry.register(**definition(source_fields=(" RELIGION ",)))


def test_source_fields_string_cannot_bypass_restricted_check():
    registry = FeatureRegistry(restricted_attributes={"religion"})
    with pytest.raises(ValueError, match="source_fields"):
        registry.register(**definition(source_fields="religion"))
    assert registry.list() == []


def test_restricted_attributes_string_cannot_disable_refusal():
    with pytest.raises(ValueError, match="restricted_attributes"):
        FeatureRegistry(restricted_attributes="religion")


def test_iterator_cannot_consume_and_disable_restricted_list():
    with pytest.raises(ValueError, match="restricted_attributes"):
        FeatureRegistry(restricted_attributes=iter(["religion"]))


def test_empty_restricted_list_is_refused_when_not_explicit():
    with pytest.raises(ValueError, match="explicit"):
        FeatureRegistry(restricted_attributes=None)


def test_deprecation_is_one_way_and_keeps_history():
    registry = FeatureRegistry(restricted_attributes=set())
    registry.register(**definition())
    with pytest.raises(ValueError, match="DRAFT"):
        registry.deprecate("recency_days", "event-time-dev-1.0")
    registry.activate("recency_days", "event-time-dev-1.0")
    registry.deprecate("recency_days", "event-time-dev-1.0")
    assert registry.get("recency_days", "event-time-dev-1.0")["state"] == "DEPRECATED"
    with pytest.raises(ValueError, match="DEPRECATED"):
        registry.activate("recency_days", "event-time-dev-1.0")
    assert [
        event["to"] for event in registry.history("recency_days", "event-time-dev-1.0")
    ] == [
        "DRAFT",
        "ACTIVE",
        "DEPRECATED",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("feature_name", ""),
        ("feature_version", " "),
        ("source_fields", ()),
        ("owner", ""),
    ],
)
def test_incomplete_definition_is_refused(field, value):
    registry = FeatureRegistry(restricted_attributes=set())
    with pytest.raises(ValueError):
        registry.register(**definition(**{field: value}))


def test_unknown_feature_lookup_is_refused():
    registry = FeatureRegistry(restricted_attributes=set())
    with pytest.raises(KeyError):
        registry.get("missing", "v1")
