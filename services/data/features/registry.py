"""K-03: versioned feature definitions, in-memory, dev-only.

A (feature_name, feature_version) definition cannot be edited once ACTIVE;
a changed definition must be registered under a new version. Restricted
attributes are rejected by name at registration time, never silently
dropped. This has no database backing and no serving authority; it is a
rule-checking skeleton for the feature-governance contract.
"""

from __future__ import annotations

Entries = list[dict]


def _normalize(value: str) -> str:
    return value.strip().casefold()


class FeatureRegistry:
    def __init__(self, restricted_attributes: set[str] | None) -> None:
        if restricted_attributes is None or isinstance(
            restricted_attributes, (str, bytes)
        ):
            raise ValueError(
                "restricted_attributes must be an explicit set/list/tuple of "
                "strings (an empty collection is allowed; None or a bare "
                "string is not, so callers cannot forget it or pass one by "
                "mistake)"
            )
        if not all(isinstance(name, str) for name in restricted_attributes):
            raise ValueError("restricted_attributes must contain only strings")
        self._restricted = {_normalize(name) for name in restricted_attributes}
        self._definitions: dict[tuple[str, str], dict] = {}
        self._history: dict[tuple[str, str], list[dict]] = {}

    def _key(self, feature_name: str, feature_version: str) -> tuple[str, str]:
        return (feature_name, feature_version)

    def register(
        self,
        *,
        feature_name: str,
        feature_version: str,
        description: str,
        source_fields: tuple[str, ...],
        owner: str,
    ) -> dict:
        for label, value in (
            ("feature_name", feature_name),
            ("feature_version", feature_version),
            ("description", description),
            ("owner", owner),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a nonempty string")
        if (
            not isinstance(source_fields, (tuple, list))
            or not source_fields
            or not all(
                isinstance(field, str) and field.strip() for field in source_fields
            )
        ):
            raise ValueError("source_fields must be a nonempty tuple of strings")
        hit = {
            field for field in source_fields if _normalize(field) in self._restricted
        }
        if hit:
            raise ValueError(f"Restricted attribute(s) rejected: {sorted(hit)}")
        key = self._key(feature_name, feature_version)
        existing = self._definitions.get(key)
        if existing is not None and existing["state"] != "DRAFT":
            raise ValueError(
                f"{feature_name}@{feature_version} is {existing['state']} and "
                "immutable; register a new feature_version instead"
            )
        entry = {
            "feature_name": feature_name,
            "feature_version": feature_version,
            "description": description,
            "source_fields": tuple(source_fields),
            "owner": owner,
            "state": "DRAFT",
        }
        self._definitions[key] = entry
        self._history.setdefault(key, []).append({"to": "DRAFT"})
        return dict(entry)

    def get(self, feature_name: str, feature_version: str) -> dict:
        key = self._key(feature_name, feature_version)
        if key not in self._definitions:
            raise KeyError(f"No definition for {feature_name}@{feature_version}")
        return dict(self._definitions[key])

    def list(self) -> Entries:
        return [dict(entry) for entry in self._definitions.values()]

    def _transition(
        self, feature_name: str, feature_version: str, frm: str, to: str
    ) -> None:
        key = self._key(feature_name, feature_version)
        entry = self.get(feature_name, feature_version)
        if entry["state"] != frm:
            raise ValueError(
                f"{feature_name}@{feature_version} must be {frm} to become {to}, "
                f"is {entry['state']}"
            )
        self._definitions[key]["state"] = to
        self._history[key].append({"to": to})

    def activate(self, feature_name: str, feature_version: str) -> None:
        self._transition(feature_name, feature_version, "DRAFT", "ACTIVE")

    def deprecate(self, feature_name: str, feature_version: str) -> None:
        self._transition(feature_name, feature_version, "ACTIVE", "DEPRECATED")

    def history(self, feature_name: str, feature_version: str) -> Entries:
        key = self._key(feature_name, feature_version)
        if key not in self._history:
            raise KeyError(f"No definition for {feature_name}@{feature_version}")
        return [dict(event) for event in self._history[key]]
