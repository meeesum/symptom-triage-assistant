"""SQLAlchemy engine/session setup. See config.py for the DB URL.

Schema management moved to Alembic (see app/core/migrate.py and
migrations/) as part of the Postgres migration — this module used to also
own `init_db()`, which called `Base.metadata.create_all()` eagerly at
import time. That's gone: with Alembic as the source of truth, letting
this module create tables as a side effect of being imported would let
the schema drift out of sync with the migration history (or race a real
migration run). Nothing in here should have import-time side effects
beyond defining the engine/session/Base — see app/core/migrate.py for
the (explicit, not automatic) call that actually creates/updates tables.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
