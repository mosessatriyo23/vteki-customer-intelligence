from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session, selectinload

from api.database import get_db
from api.models import Role, User
from api.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# EmailStr rejects special-use domains beyond JSON Schema's generic email format.
# Publish that restriction without relaxing runtime validation or hiding 422s.
_RESERVED_DOMAINS = ("arpa", "invalid", "local", "localhost", "onion", "test")
_RESERVED_PATTERN = "|".join(
    "".join(f"[{char.lower()}{char.upper()}]" for char in domain)
    for domain in _RESERVED_DOMAINS
)
EMAIL_SCHEMA_PATTERN = rf"^[^@]+@(?!(?:.*\.)?(?:{_RESERVED_PATTERN})\.?$)"


def email_field():
    return Field(
        json_schema_extra={"pattern": EMAIL_SCHEMA_PATTERN},
        description="Email address; special-use/reserved domains are not accepted.",
    )


class LoginRequest(BaseModel):
    email: EmailStr = email_field()
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserCreate(BaseModel, extra="ignore"):
    email: EmailStr = email_field()
    password: str = Field(min_length=12, max_length=128)
    roles: list[Literal["admin", "analyst", "operator", "campaign_manager"]] = Field(
        min_length=1
    )


class UserResponse(BaseModel):
    id: int
    email: EmailStr = email_field()
    roles: list[str]


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = (
        db.query(User)
        .options(selectinload(User.roles))
        .filter(User.email == payload.email.lower())
        .first()
    )
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from api.config import ACCESS_TOKEN_TTL

    return TokenResponse(
        access_token=create_access_token(user),
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, roles=sorted(role.name for role in user.roles)
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> UserResponse:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        )
    roles = db.query(Role).filter(Role.name.in_(set(payload.roles))).all()
    if {role.name for role in roles} != set(payload.roles):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown role"
        )
    user = User(email=email, password_hash=hash_password(payload.password), roles=roles)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id, email=user.email, roles=sorted(role.name for role in user.roles)
    )
