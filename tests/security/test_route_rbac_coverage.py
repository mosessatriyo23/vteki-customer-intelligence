"""Fail closed if a new business endpoint is registered without server-side auth."""

from fastapi.routing import APIRoute

from api.main import app
from api.security import get_current_user

PUBLIC_ENDPOINTS = {
    ("GET", "/health"),
    ("POST", "/auth/login"),
}


def _depends_on_current_user(dependant) -> bool:
    if dependant.call is get_current_user:
        return True
    return any(_depends_on_current_user(item) for item in dependant.dependencies)


def test_every_business_route_requires_authenticated_user_or_role():
    unprotected = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            if (method, route.path) in PUBLIC_ENDPOINTS:
                continue
            if not _depends_on_current_user(route.dependant):
                unprotected.append(f"{method} {route.path}")

    assert (
        not unprotected
    ), "Business routes must depend on get_current_user through RBAC: " + ", ".join(
        sorted(unprotected)
    )
