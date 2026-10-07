import os

from sqlalchemy import select

from api.database import SessionLocal
from api.models import Role, User
from api.security import hash_password


def main() -> None:
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or len(password) < 12:
        raise SystemExit(
            "Set BOOTSTRAP_ADMIN_EMAIL and a BOOTSTRAP_ADMIN_PASSWORD "
            "of at least 12 characters"
        )

    with SessionLocal.begin() as session:
        if session.scalar(select(User.id).limit(1)) is not None:
            raise SystemExit("Bootstrap refused: users already exist")
        admin_role = session.scalar(select(Role).where(Role.name == "admin"))
        if admin_role is None:
            raise SystemExit("Roles are missing; run database migrations first")
        session.add(
            User(email=email, password_hash=hash_password(password), roles=[admin_role])
        )

    print(f"Created initial administrator: {email}")


if __name__ == "__main__":
    main()
