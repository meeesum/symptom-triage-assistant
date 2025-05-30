"""Programmatic entry point for running Alembic migrations.

Separate from app/core/db.py on purpose: migrations/env.py imports
`Base` and every model module from db.py/models to build
`target_metadata` for autogenerate. If db.py itself imported and called
this module (or ran migrations as an import-time side effect the way the
old `init_db()` did), that would be a circular/self-referential mess —
db.py stays a plain "engine + session + Base" module with zero side
effects, and this module is the one explicit place schema changes
actually get applied.

Called from:
  - app/main.py's lifespan, for local/dev convenience (so `uvicorn
    app.main:app` just works without a separate manual step)
  - tests/conftest.py, once per test session, against the throwaway
    SQLite file — so the test suite runs against the SAME migration
    history production would, not a parallel `create_all()` schema that
    could silently drift from what the migrations actually produce
  - scripts/migrate.py, for running migrations as an explicit deploy
    step — the standard production pattern, since auto-migrating on
    every app-instance boot means N replicas can race to apply the same
    migration concurrently. Dev/test convenience above takes the
    tradeoff deliberately; a real deployment should call the script
    once, before starting any app instances, not rely on the lifespan
    hook.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migrations(revision: str = "head") -> None:
    cfg = Config(str(_ALEMBIC_INI))
    command.upgrade(cfg, revision)
