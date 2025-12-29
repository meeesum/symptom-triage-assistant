#!/usr/bin/env python
"""Send every due scheduled analytics report, as an explicit deploy/ops
step — same "not something the app quietly does on its own" judgment as
scripts/migrate.py and scripts/run_retention_purge.py. This is the
realistic way a real deployment triggers scheduled reports: an external
cron entry running this script on a schedule (e.g. daily, so daily/
weekly/monthly subscriptions are all checked and caught whenever they
come due), not a standing in-process scheduler.

Usage (from backend/), e.g. as a daily cron entry:
    0 6 * * * cd /path/to/backend && .venv/bin/python scripts/run_scheduled_reports.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_delivery import run_due_reports  # noqa: E402


def main() -> int:
    sent_ids = run_due_reports()
    print(f"Sent {len(sent_ids)} scheduled report(s): subscription ids {sent_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
