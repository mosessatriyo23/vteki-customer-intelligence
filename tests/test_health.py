import os

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-long-enough-for-hmac")

from api import main


def test_health_reports_database_readiness(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _statement):
            return 1

    class AvailableDatabase:
        def connect(self):
            return Connection()

    monkeypatch.setattr(main, "engine", AvailableDatabase())
    assert main.health() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_is_unavailable(monkeypatch):
    class UnavailableDatabase:
        def connect(self):
            raise OperationalError("SELECT 1", {}, RuntimeError("offline"))

    monkeypatch.setattr(main, "engine", UnavailableDatabase())
    with pytest.raises(HTTPException) as error:
        main.health()
    assert error.value.status_code == 503
