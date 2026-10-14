"""Database-backed integer identifiers exposed by the HTTP API.

PostgreSQL INTEGER is signed 32-bit. Validate before any SQL is executed to
avoid leaking 500 errors for out-of-range user input.
"""

from typing import Annotated

from fastapi import Path

DBId = Annotated[int, Path(ge=1, le=2_147_483_647)]
