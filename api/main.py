from fastapi import Depends, FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response
from starlette.routing import compile_path
from starlette.types import Receive, Scope, Send

from api.audit import AuditMiddleware
from api.audit_router import router as audit_router
from api.auth import router as auth_router
from api.campaigns import router as campaigns_router
from api.customers import router as customers_router
from api.database import engine
from api.decisions import router as decisions_router
from api.golden_customers import router as golden_customers_router
from api.governance import router as governance_router
from api.identity_reviews import router as identity_reviews_router
from api.jobs import router as jobs_router
from api.model_predictions import router as model_predictions_router
from api.models import User
from api.monitoring import router as monitoring_router
from api.security import require_roles


class GovernanceFastAPI(FastAPI):

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            path = scope.get("path", "")
            operations = self.openapi().get("paths", {}).get(path)
            if operations is not None:
                supported = {
                    method.upper()
                    for method in operations
                    if method.lower()
                    in {"get", "post", "put", "patch", "delete", "head", "trace"}
                }
            else:
                route_candidates = [
                    route
                    for included in self.routes
                    for route in getattr(
                        getattr(included, "original_router", None), "routes", [included]
                    )
                ]
                exact_routes = [
                    route
                    for route in route_candidates
                    if getattr(route, "path", None) == path
                ]
                matched_routes = exact_routes
                if not matched_routes:
                    matched_routes = []
                    for route in route_candidates:
                        template = getattr(route, "path", None)
                        if template is None:
                            continue
                        pattern, _, _ = compile_path(template)
                        if pattern.fullmatch(path):
                            matched_routes.append(route)

                supported = {
                    method.upper()
                    for route in matched_routes
                    for method in (getattr(route, "methods", None) or set())
                }
            if supported:
                allow = ", ".join(sorted(supported | {"OPTIONS"}))
                response = Response(
                    status_code=204,
                    headers={"Allow": allow},
                )
                await response(scope, receive, send)
                return

        await super().__call__(scope, receive, send)

    def openapi(self) -> dict:
        if self.openapi_schema:
            return self.openapi_schema
        schema = get_openapi(
            title=self.title,
            version=self.version,
            routes=self.routes,
        )
        error_response = {
            "description": "Request rejected by authentication, authorization, or resource validation.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                        "required": ["detail"],
                    }
                }
            },
        }
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict) or "responses" not in operation:
                    continue
                for status_code in ("400", "401", "403", "404", "409"):
                    operation["responses"].setdefault(status_code, error_response)
        self.openapi_schema = schema
        return schema


app = GovernanceFastAPI(title="VTEKI Customer Intelligence API", version="0.1.0")
app.add_middleware(AuditMiddleware)
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(golden_customers_router)
app.include_router(customers_router)
app.include_router(campaigns_router)
app.include_router(audit_router)
app.include_router(identity_reviews_router)
app.include_router(decisions_router)
app.include_router(monitoring_router)
app.include_router(model_predictions_router)
app.include_router(governance_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503, detail="Database is unavailable"
        ) from error
    return {"status": "ok", "database": "ok"}


@app.get("/admin/health", tags=["admin"])
def admin_health(_: User = Depends(require_roles("admin"))) -> dict[str, str]:
    return {"status": "ok"}
