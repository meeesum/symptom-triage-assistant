"""Sentry error tracking — opt-in via SENTRY_DSN.

No-op when SENTRY_DSN isn't set (the default for local dev and this
sandbox, which has no real Sentry project to report to) — matches the
project's established "real backing service optional, documented default"
pattern (SQLite/Postgres, fakeredis/Redis). Nothing here should ever be a
reason the app fails to start.
"""

from __future__ import annotations

import os


def init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENVIRONMENT", "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        # This app handles real patient-adjacent text — opt in to sending
        # PII explicitly if that's ever wanted, don't default it on.
        send_default_pii=False,
    )
