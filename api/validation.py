"""Reusable validation metadata for HTTP request models."""

from typing import Annotated

from fastapi import Path
from pydantic import Field

DBId = Annotated[int, Path(ge=1, le=2_147_483_647)]


_RESERVED_EMAIL_SUFFIXES = ("arpa", "invalid", "local", "localhost", "onion", "test")


def _case_insensitive_ascii(value: str) -> str:
    return "".join(f"[{letter.lower()}{letter.upper()}]" for letter in value)


EMAIL_SCHEMA_PATTERN = (
    r"^(?![^@\s]+@(?:[^.@\s]+\.)*(?:"
    + "|".join(_case_insensitive_ascii(suffix) for suffix in _RESERVED_EMAIL_SUFFIXES)
    + r")$)(?=[^@]{1,64}@)"
    + r"[A-Za-z0-9_%+\-]+(?:\.[A-Za-z0-9_%+\-]+)*@"
    + r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    + r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    + r"\.[A-Za-z]{2,63}$"
)


def email_field():
    return Field(
        max_length=254,
        json_schema_extra={"pattern": EMAIL_SCHEMA_PATTERN},
        description="Valid email with DNS TLD; reserved domains are not accepted.",
    )
