"""Provider analytics API — triage volume, tier distribution, and
time-to-follow-up trends. See docs/phase7d-provider-analytics.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_role
from app.services.analytics import (
    DEFAULT_WINDOW_DAYS,
    tier_distribution,
    time_to_follow_up_stats,
    triage_volume_by_day,
)

router = APIRouter(prefix="/audit", tags=["analytics"])


class VolumeDay(BaseModel):
    date: str
    count: int


class FollowUpStats(BaseModel):
    average_hours: float | None
    median_hours: float | None
    count: int


class AnalyticsResponse(BaseModel):
    window_days: int
    volume_by_day: list[VolumeDay]
    tier_distribution: dict[str, int]
    time_to_follow_up: FollowUpStats


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    days: int = DEFAULT_WINDOW_DAYS,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> AnalyticsResponse:
    days = min(max(days, 1), 365)  # same floor-and-ceiling pattern as /audit/recent's limit
    org_id = user.org_id
    return AnalyticsResponse(
        window_days=days,
        volume_by_day=[
            VolumeDay(**d) for d in triage_volume_by_day(user.role, user.id, days, org_id)
        ],
        tier_distribution=tier_distribution(user.role, user.id, days, org_id),
        time_to_follow_up=FollowUpStats(
            **time_to_follow_up_stats(user.role, user.id, days, org_id)
        ),
    )
