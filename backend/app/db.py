from collections.abc import Iterator
from decimal import Decimal

from sqlalchemy import BigInteger, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import settings
from app.core.money import to_money


class Base(DeclarativeBase):
    pass


class Money(TypeDecorator):
    """Decimal THB stored as integer satang, so SQLite never rounds through float."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int(to_money(value) * 100)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(Decimal("0.01"))


class ExactDecimal(TypeDecorator):
    """Non-money decimals (rates, ratios) stored as text to keep exact precision."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from app import models  # noqa: F401  (register models)

    Base.metadata.create_all(engine)
