#!/usr/bin/env python
"""Run Alembic migrations as an explicit deploy step.

Usage (from backend/):
    DATABASE_URL=postgresql+psycopg://... python scripts/migrate.py

This is the production path: run once, before starting any app instance.
`app/main.py`'s lifespan also calls run_migrations() for local/dev
convenience, but relying on that in production means every replica races
to apply the same migration on boot — see app/core/migrate.py's docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DATABASE_URL  # noqa: E402
from app.core.migrate import run_migrations  # noqa: E402


def main() -> int:
    print(f"Running migrations against: {DATABASE_URL}")
    run_migrations()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
