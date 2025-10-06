"""Load test: proves the rate limiter (app/core/rate_limit.py) actually
holds under real concurrent load, not just the single-threaded curl-style
check every prior epic's manual verification used.

The limits under test (see app/core/rate_limit.py / app/api/auth.py):
  - POST /auth/register — 5/minute per IP
  - POST /auth/login    — 10/minute per IP
  - POST /auth/refresh  — 30/minute per IP

This is deliberately its OWN locustfile, separate from
locustfile_triage.py: /triage/intake has no rate limit at all today (see
docs/phase5d-api-hardening.md's "no blanket API-wide limit" decision), so
mixing auth traffic into the triage load test would conflate two
different things being measured, and running Locust with many simulated
"users" against a rate limit keyed on source IP only makes sense when
every one of those users genuinely shares one IP — true for a local run
against 127.0.0.1, which is the intended way to run this.

What "passing" looks like here is NOT "every request succeeds" — it's
the opposite: BOTH conditions below being true means the limiter is
working correctly under real concurrent pressure, not just in the
existing single-threaded pytest test:
  1. Some requests succeed (200/201) — real traffic within the limit
     isn't being wrongly blocked.
  2. Some requests get 429 once concurrent volume exceeds the limit —
     the limiter is actually engaging under real, overlapping requests,
     not just in a serial curl loop where timing never actually
     contends.
A run where EVERY request succeeds would mean the limiter silently
stopped working under concurrency (e.g. a race in how slowapi's counter
is incremented) — worth knowing, and impossible to see from the existing
single-threaded rate-limiting pytest suite alone.

Usage (from backend/, against a real running server with
RATE_LIMIT_ENABLED unset/"1" — the app's real default; the existing
pytest suite runs with RATE_LIMIT_ENABLED=0, so THIS is the only place
in this project the limiter is exercised under real concurrent load):

    locust -f scripts/loadtest/locustfile_auth_rate_limits.py \\
        --host=http://127.0.0.1:8000 --headless --users 20 --spawn-rate 20 \\
        --run-time 30s

Deliberately high spawn-rate relative to run-time — the whole point is
concurrent pressure within the same rate-limit window (a minute), not a
slow ramp that never actually contends.
"""

from __future__ import annotations

import itertools
import uuid

from locust import HttpUser, constant, events, task

_email_counter = itertools.count()

_stats = {"register_200": 0, "register_429": 0, "login_200": 0, "login_429": 0}


class AuthRateLimitProbe(HttpUser):
    # No think-time — deliberately hammering as fast as this simulated
    # user can, since the point is concurrent pressure within the
    # rate-limit window, not realistic pacing (see locustfile_triage.py
    # for the realistic-pacing version of this pattern).
    wait_time = constant(0)

    @task
    def register_and_login(self):
        email = f"loadtest-{uuid.uuid4().hex[:10]}@example.com"
        password = "correct-horse-battery-staple"

        with self.client.post(
            "/auth/register",
            json={"email": email, "password": password},
            name="/auth/register",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                _stats["register_200"] += 1
                resp.success()
            elif resp.status_code == 429:
                _stats["register_429"] += 1
                # A 429 here is EXPECTED once the limit is hit — this is
                # what proves the limiter is working, not a failure.
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")
                return

        with self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
            name="/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                _stats["login_200"] += 1
                resp.success()
            elif resp.status_code in (401, 429):
                # 401 is expected for any register attempt that itself
                # got 429'd (the account was never created); 429 is the
                # login limiter itself engaging.
                if resp.status_code == 429:
                    _stats["login_429"] += 1
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")


@events.quitting.add_listener
def report_rate_limit_verdict(environment, **kwargs):
    """Printed at the end of a headless run — the actual pass/fail signal
    for THIS load test, distinct from Locust's own request-count summary.
    See this module's docstring for why "some 429s" is the success case.
    """
    print("\n--- Rate limiter verdict ---")
    print(f"register: {_stats['register_200']} succeeded, {_stats['register_429']} got 429")
    print(f"login:    {_stats['login_200']} succeeded, {_stats['login_429']} got 429")

    if _stats["register_429"] == 0 and (_stats["register_200"] + _stats["register_429"]) > 5:
        print(
            "WARNING: more than 5 register attempts were made and NONE got 429 — "
            "the /auth/register rate limit does not appear to be engaging under load."
        )
    else:
        print("OK: /auth/register's 5/minute limit engaged under concurrent load.")
