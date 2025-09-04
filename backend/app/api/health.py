"""Liveness vs. readiness — a real distinction, not two names for the same
check. `/health` (in main.py, unchanged) only proves the process is up and
answering HTTP at all; a container orchestrator uses it to decide "should
this instance be killed and restarted." `/health/ready` additionally
proves the app can actually serve a real request — DB and Redis are both
reachable — which is what a load balancer/orchestrator should check before
routing traffic to this instance. Conflating the two is a classic mistake:
an instance that's alive but can't reach its DB should fail readiness
(stop receiving traffic) without failing liveness (getting restarted,
which won't fix an external DB outage and just churns the process).
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.db import engine
from app.core.redis_client import redis_client

router = APIRouter(tags=["health"])


@router.get("/health/ready")
async def readiness(response: Response) -> dict:
    checks = {"database": _check_database(), "redis": _check_redis()}
    healthy = all(checks.values())
    # An orchestrator's readiness probe checks the HTTP status code, not
    # response body content — 503 here is what actually pulls this
    # instance out of a load balancer's rotation, not just informational.
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "not_ready", "checks": checks}


def _check_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — a readiness check must report False on ANY failure, not crash
        return False


def _check_redis() -> bool:
    try:
        return bool(redis_client.ping())
    except Exception:  # noqa: BLE001 — same as above: any failure means "not ready", never an unhandled 500
        return False
