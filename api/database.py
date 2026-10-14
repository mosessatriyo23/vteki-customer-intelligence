from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from api.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


SQLITE_SCHEMA_TRANSLATE_MAP = {
    "core": None,
    "gov": None,
    "stg": None,
    "feat": None,
    "ml": None,
    "dec": None,
    "act": None,
    "msr": None,
    "source": None,
    "identity": None,
    "customer360": None,
    "segmentation": None,
}


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
