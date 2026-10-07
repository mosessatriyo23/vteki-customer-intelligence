from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi

from api.audit import AuditMiddleware
from api.audit_router import router as audit_router
from api.auth import router as auth_router
from api.campaigns import router as campaigns_router
from api.customers import router as customers_router
from api.decisions import router as decisions_router
from api.governance import router as governance_router
from api.identity_reviews import router as identity_reviews_router
from api.jobs import router as jobs_router
from api.models import User
from api.monitoring import router as monitoring_router
from api.security import require_roles


class GovernanceFastAPI(FastAPI):
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
app.include_router(customers_router)
app.include_router(campaigns_router)
app.include_router(audit_router)
app.include_router(identity_reviews_router)
app.include_router(decisions_router)
app.include_router(monitoring_router)
app.include_router(governance_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin/health", tags=["admin"])
def admin_health(_: User = Depends(require_roles("admin"))) -> dict[str, str]:
    return {"status": "ok"}
