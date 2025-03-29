"""Reporting exports API — on-demand CSV/PDF exports off the provider
analytics dashboard, plus self-service scheduled report subscriptions for
org admins. See docs/phase9d-reporting-exports.md.

Two distinct concerns, two routers in this one module:
  - `export_router` (prefix /audit, matching /audit/recent and
    /audit/analytics): on-demand CSV/PDF, gated the same as the
    analytics dashboard itself (provider/org_admin/admin).
  - `subscription_router` (prefix /reports): self-service — a user
    manages their OWN subscription, same "personal preference, not an
    admin-controlled assignment" reasoning as
    app/api/notifications.py's preferences endpoints. Gated to org_admin
    specifically (not provider/admin) — see
    app/models/report_subscription.py's docstring for why a recurring
    digest is meaningful for an org-wide view but not a panel-scoped one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_role
from app.models.report_subscription import VALID_FORMATS, VALID_FREQUENCIES
from app.services.analytics import DEFAULT_WINDOW_DAYS
from app.services.report_delivery import (
    delete_subscription,
    enqueue_report_send,
    get_subscription,
    set_subscription,
)
from app.services.reporting import build_analytics_pdf, build_audit_csv

export_router = APIRouter(prefix="/audit", tags=["reporting"])
subscription_router = APIRouter(prefix="/reports", tags=["reporting"])


def _clamp_days(days: int) -> int:
    return min(max(days, 1), 365)  # same floor-and-ceiling pattern as /audit/analytics


@export_router.get("/export.csv")
async def export_audit_csv(
    days: int = DEFAULT_WINDOW_DAYS,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> Response:
    csv_bytes = build_audit_csv(user.role, user.id, user.org_id, _clamp_days(days))
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=triage_audit_export.csv"},
    )


@export_router.get("/analytics/export.pdf")
async def export_analytics_pdf(
    days: int = DEFAULT_WINDOW_DAYS,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> Response:
    pdf_bytes = build_analytics_pdf(user.role, user.id, user.org_id, _clamp_days(days))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=triage_analytics_report.pdf"},
    )


class SubscriptionRequest(BaseModel):
    frequency: str = "weekly"
    report_format: str = "pdf"


class SubscriptionResponse(BaseModel):
    subscribed: bool
    frequency: str | None = None
    report_format: str | None = None
    last_sent_at: str | None = None


@subscription_router.get("/subscription", response_model=SubscriptionResponse)
async def get_my_subscription(
    user: CurrentUser = Depends(require_role("org_admin")),
) -> SubscriptionResponse:
    sub = get_subscription(user.id)
    if sub is None:
        return SubscriptionResponse(subscribed=False)
    return SubscriptionResponse(
        subscribed=True,
        frequency=sub.frequency,
        report_format=sub.report_format,
        last_sent_at=sub.last_sent_at.isoformat() if sub.last_sent_at else None,
    )


@subscription_router.put("/subscription", response_model=SubscriptionResponse)
async def update_my_subscription(
    request: SubscriptionRequest,
    user: CurrentUser = Depends(require_role("org_admin")),
) -> SubscriptionResponse:
    if request.frequency not in VALID_FREQUENCIES:
        raise HTTPException(
            status_code=422, detail=f"frequency must be one of {VALID_FREQUENCIES}"
        )
    if request.report_format not in VALID_FORMATS:
        raise HTTPException(status_code=422, detail=f"report_format must be one of {VALID_FORMATS}")

    sub = set_subscription(user.id, request.frequency, request.report_format)
    return SubscriptionResponse(
        subscribed=True,
        frequency=sub.frequency,
        report_format=sub.report_format,
        last_sent_at=sub.last_sent_at.isoformat() if sub.last_sent_at else None,
    )


@subscription_router.delete("/subscription", status_code=204)
async def cancel_my_subscription(
    user: CurrentUser = Depends(require_role("org_admin")),
) -> Response:
    delete_subscription(user.id)
    return Response(status_code=204)


@subscription_router.post("/subscription/send-now", status_code=202)
async def send_my_report_now(
    user: CurrentUser = Depends(require_role("org_admin")),
) -> dict:
    sub = get_subscription(user.id)
    if sub is None:
        raise HTTPException(
            status_code=404, detail="no active subscription — PUT /reports/subscription first"
        )
    # Decoupled via the job queue (see app/services/report_delivery.py) —
    # PDF generation + an SMTP round trip shouldn't block this response,
    # same reasoning as trigger_high_risk_alert().
    enqueue_report_send(sub.id)
    return {"status": "queued"}
