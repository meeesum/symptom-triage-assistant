"""App-wide settings. Deliberately minimal — add fields only as something
actually reads them, not speculatively."""

from __future__ import annotations

import os
from pathlib import Path

# SQLite file next to the backend/ directory by default, so a fresh clone
# runs with zero setup (`pip install -r requirements.txt && uvicorn
# app.main:app`) — no DB server required. Point DATABASE_URL at Postgres
# for anything beyond local single-process dev; `docker-compose up` (see
# docker-compose.yml) brings up a local Postgres wired to match the
# example below. SQLite is NOT a production audit store (no concurrent-
# write story, no managed backups/retention policy) — see
# docs/phase5-postgres-migration.md for why Postgres is the real target
# and what changed to make both actually work off the same Alembic
# migration history (app/core/migrate.py) instead of drifting apart.
#
# Postgres example: postgresql+psycopg://triage:triage@localhost:5432/triage
# (the "+psycopg" driver segment matters — this project uses psycopg v3,
# not psycopg2, since psycopg2-binary has no prebuilt wheel for Python
# 3.13 and fails to compile from source against its C API changes.)
_DEFAULT_SQLITE_PATH = Path(__file__).resolve().parents[2] / "triage_audit.db"

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")

# Symptom photo uploads (app/services/symptom_photos.py) — plain local
# filesystem storage next to the repo, same zero-setup-by-default
# philosophy as the SQLite path above. NOT an object-store/CDN story;
# fine for a single-process prototype, not for a real multi-instance
# deployment — see docs/phase9c-symptom-photo-upload.md.
_DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads" / "symptom_photos"
UPLOAD_DIR = Path(os.environ.get("SYMPTOM_PHOTO_UPLOAD_DIR", str(_DEFAULT_UPLOAD_DIR)))
MAX_PHOTO_BYTES = int(os.environ.get("MAX_PHOTO_BYTES", 5 * 1024 * 1024))  # 5 MiB
