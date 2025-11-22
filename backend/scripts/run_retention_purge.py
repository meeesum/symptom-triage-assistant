#!/usr/bin/env python
"""Run a retention purge synchronously, as an explicit deploy/ops step —
same "not something the app quietly does on its own" judgment as
scripts/migrate.py. This is the realistic way a real deployment triggers
retention: an external cron entry running this script on a schedule (e.g.
daily), not the POST /admin/retention/purge API endpoint, which exists
for manual/testing visibility rather than as the primary trigger.

Usage (from backend/), e.g. as a daily cron entry:
    0 3 * * * cd /path/to/backend && .venv/bin/python scripts/run_retention_purge.py

Retention windows are configurable via env vars (CHAT_HISTORY_RETENTION_DAYS,
AUDIT_RECORD_RETENTION_DAYS, ADMIN_ACTION_LOG_RETENTION_DAYS) — see
app/services/retention.py for the defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retention import purge_old_data  # noqa: E402


def main() -> int:
    run = purge_old_data()
    print(
        f"Purge run {run.id}: {run.chat_exchanges_deleted} chat exchange(s), "
        f"{run.audit_records_deleted} audit record(s), "
        f"{run.symptom_photos_deleted} symptom photo(s), "
        f"{run.admin_action_logs_deleted} admin action log(s) deleted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
