import hashlib
import os
from datetime import datetime, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, selectinload

from api.config import ACCESS_TOKEN_TTL, JWT_ALGORITHM, JWT_SECRET
from api.database import get_db
from api.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def _get_jwt_secret() -> str:
    return os.getenv("JWT_SECRET") or JWT_SECRET


def _bcrypt_input(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(password: str) -> str:
    digest = bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt(rounds=12))
    return digest.decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_input(password), encoded.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def create_access_token(user: User) -> str:
    secret = _get_jwt_secret()
    if not secret:
        raise RuntimeError(
            "JWT_SECRET must be configured before serving authentication requests"
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "roles": sorted(role.name for role in user.roles),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    secret = _get_jwt_secret()
    if credentials is None or not secret:
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials, secret, algorithms=[JWT_ALGORITHM]
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None
    user = (
        db.query(User)
        .options(selectinload(User.roles))
        .filter(User.id == user_id)
        .first()
    )
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*required_roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if not {role.name for role in user.roles}.intersection(required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return user

    return dependency
