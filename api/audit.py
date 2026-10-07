import logging
import re
from uuid import uuid4

import jwt
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from api.config import JWT_ALGORITHM, JWT_SECRET
from api.database import SessionLocal
from api.models import AuditEvent

logger = logging.getLogger(__name__)


def record_audit_event(
    session: Session,
    *,
    correlation_id: str,
    event_type: str,
    actor_id: int | None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        request_id=correlation_id,
        correlation_id=correlation_id,
        actor_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
        method="SYSTEM",
        path="/internal/audit",
        status_code=200,
    )
    session.add(event)
    return event


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid4().hex
        incoming_correlation_id = request.headers.get("x-correlation-id", "")
        correlation_id = (
            incoming_correlation_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", incoming_correlation_id)
            else request_id
        )
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            authorization = request.headers.get("authorization", "")
            actor_id = self._actor_id(authorization)
            session_factory = getattr(
                request.app.state, "audit_session_factory", SessionLocal
            )
            try:
                with session_factory() as session:
                    session.add(
                        AuditEvent(
                            request_id=request_id,
                            correlation_id=correlation_id,
                            actor_id=actor_id,
                            method=request.method,
                            path=request.url.path[:512],
                            status_code=status_code,
                            client_ip=request.client.host if request.client else None,
                            user_agent=request.headers.get("user-agent", "")[:512]
                            or None,
                        )
                    )
                    session.commit()
            except Exception:
                logger.exception(
                    "Failed to persist audit event request_id=%s", request_id
                )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @staticmethod
    def _actor_id(authorization: str) -> int | None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not JWT_SECRET:
            return None
        try:
            return int(jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])["sub"])
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
            return None
