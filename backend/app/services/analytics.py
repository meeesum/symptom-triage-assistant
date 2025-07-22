"""Provider analytics aggregation — triage volume, tier distribution, and
time-to-follow-up trends. Read-only: no new tables, aggregates over
TriageAuditRecord and ReferralStatusChange. Same panel-based visibility
as GET /audit/recent (app/services/audit_visibility.py) — a provider's
analytics reflect only their own panel (+ anonymous records), never the
whole system. See docs/phase7d-provider-analytics.md.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.models.referral import Referral, ReferralStatusChange
from app.safety.schemas import EscalationTier
from app.services.audit_visibility import audit_visibility_clause

DEFAULT_WINDOW_DAYS = 30


def triage_volume_by_day(
    role: str, user_id: int, days: int = DEFAULT_WINDOW_DAYS, org_id: int | None = None
) -> list[dict]:
    """One entry per calendar day in the window, oldest first — including
    days with zero triages, so a frontend chart doesn't need to fill
    gaps itself."""
    since = datetime.now(UTC) - timedelta(days=days)
    with get_session() as session:
        query = select(TriageAuditRecord.created_at).where(TriageAuditRecord.created_at >= since)
        visibility = audit_visibility_clause(role, user_id, org_id)
        if visibility is not None:
            query = query.where(visibility)

        created_ats = session.execute(query).scalars().all()

    counts: dict[str, int] = {}
    for created_at in created_ats:
        if created_at is None:
            continue
        day = created_at.date().isoformat()
        counts[day] = counts.get(day, 0) + 1

    today = datetime.now(UTC).date()
    return [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "count": counts.get((today - timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(days - 1, -1, -1)
    ]


def tier_distribution(
    role: str, user_id: int, days: int = DEFAULT_WINDOW_DAYS, org_id: int | None = None
) -> dict[str, int]:
    since = datetime.now(UTC) - timedelta(days=days)
    with get_session() as session:
        query = (
            select(TriageAuditRecord.tier, func.count())
            .where(TriageAuditRecord.created_at >= since)
            .group_by(TriageAuditRecord.tier)
        )
        visibility = audit_visibility_clause(role, user_id, org_id)
        if visibility is not None:
            query = query.where(visibility)

        rows = session.execute(query).all()

    counts = {tier.value: 0 for tier in EscalationTier}
    for tier, count in rows:
        counts[tier] = count
    return counts


def time_to_follow_up_stats(
    role: str, user_id: int, days: int = DEFAULT_WINDOW_DAYS, org_id: int | None = None
) -> dict:
    """Hours between an audit record's creation and the FIRST referral
    status change moving it past `referred` (i.e. to `scheduled` or
    `seen` — whichever came first, since a referral can skip straight to
    `seen`; see docs/phase7c-referral-tracking.md). Records with no
    referral, or a referral still stuck at `referred`, aren't counted —
    there's no follow-up to measure yet, not a zero."""
    since = datetime.now(UTC) - timedelta(days=days)
    with get_session() as session:
        query = (
            select(TriageAuditRecord.id, TriageAuditRecord.created_at)
            .where(TriageAuditRecord.created_at >= since)
        )
        visibility = audit_visibility_clause(role, user_id, org_id)
        if visibility is not None:
            query = query.where(visibility)
        visible_records = {rid: created_at for rid, created_at in session.execute(query).all()}

        if not visible_records:
            return {"average_hours": None, "median_hours": None, "count": 0}

        referrals = session.execute(
            select(Referral.id, Referral.audit_record_id).where(
                Referral.audit_record_id.in_(visible_records.keys())
            )
        ).all()
        referral_to_record = {referral_id: record_id for referral_id, record_id in referrals}
        if not referral_to_record:
            return {"average_hours": None, "median_hours": None, "count": 0}

        first_follow_up_at: dict[int, datetime] = {}
        changes = session.execute(
            select(
                ReferralStatusChange.referral_id,
                ReferralStatusChange.to_status,
                ReferralStatusChange.changed_at,
            )
            .where(ReferralStatusChange.referral_id.in_(referral_to_record.keys()))
            .order_by(ReferralStatusChange.id)
        ).all()
        for referral_id, to_status, changed_at in changes:
            if to_status == "referred":
                continue  # the initial creation event, not a follow-up
            if referral_id not in first_follow_up_at:
                first_follow_up_at[referral_id] = changed_at

    hours: list[float] = []
    for referral_id, followed_up_at in first_follow_up_at.items():
        record_id = referral_to_record[referral_id]
        created_at = visible_records[record_id]
        delta = followed_up_at - created_at
        hours.append(delta.total_seconds() / 3600)

    if not hours:
        return {"average_hours": None, "median_hours": None, "count": 0}

    return {
        "average_hours": round(statistics.mean(hours), 2),
        "median_hours": round(statistics.median(hours), 2),
        "count": len(hours),
    }
