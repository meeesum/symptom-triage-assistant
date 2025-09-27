"""Referral & appointment tracking API. Same panel-based visibility as
clinical notes (app/api/clinical_notes.py) and GET /audit/recent
(app/api/audit.py) — a referral is exactly as sensitive as the audit
record it's attached to. See docs/phase7c-referral-tracking.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_role
from app.models.referral import STATUS_ORDER, Referral, ReferralStatusChange
from app.services.admin_action_log import log_admin_action
from app.services.clinical_notes import AuditRecordNotFound, get_audit_record_patient_id
from app.services.patient_panel import org_admin_can_view_record, provider_can_view_record
from app.services.referrals import (
    InvalidStatusTransition,
    ReferralAlreadyExists,
    ReferralNotFound,
    advance_status,
    create_referral,
    get_referral,
    get_status_history,
)

router = APIRouter(prefix="/audit", tags=["referrals"])


class StatusUpdateRequest(BaseModel):
    status: str


class StatusChangeResponse(BaseModel):
    from_status: str | None
    to_status: str
    changed_by: int
    changed_at: str | None

    @staticmethod
    def from_model(c: ReferralStatusChange) -> StatusChangeResponse:
        return StatusChangeResponse(
            from_status=c.from_status,
            to_status=c.to_status,
            changed_by=c.changed_by,
            changed_at=c.changed_at.isoformat() if c.changed_at else None,
        )


class ReferralResponse(BaseModel):
    id: int
    audit_record_id: int
    status: str
    created_by: int
    created_at: str | None
    updated_at: str | None
    history: list[StatusChangeResponse]

    @staticmethod
    def from_model(r: Referral, history: list[ReferralStatusChange]) -> ReferralResponse:
        return ReferralResponse(
            id=r.id,
            audit_record_id=r.audit_record_id,
            status=r.status,
            created_by=r.created_by,
            created_at=r.created_at.isoformat() if r.created_at else None,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
            history=[StatusChangeResponse.from_model(c) for c in history],
        )


def _check_visible(record_id: int, user: CurrentUser) -> None:
    try:
        patient_id = get_audit_record_patient_id(record_id)
    except AuditRecordNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

    visible = True
    if user.role == "provider":
        visible = provider_can_view_record(user.id, patient_id)
    elif user.role == "org_admin":
        visible = org_admin_can_view_record(user.org_id, patient_id)

    if not visible:
        raise HTTPException(status_code=404, detail=f"no audit record with id {record_id}")


@router.post("/{record_id}/referral", response_model=ReferralResponse, status_code=201)
async def create_referral_for_record(
    record_id: int,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> ReferralResponse:
    _check_visible(record_id, user)
    try:
        referral = create_referral(record_id, created_by=user.id)
    except ReferralAlreadyExists as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return ReferralResponse.from_model(referral, get_status_history(referral.id))


@router.get("/{record_id}/referral", response_model=ReferralResponse)
async def get_referral_for_record(
    record_id: int,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> ReferralResponse:
    _check_visible(record_id, user)
    referral = get_referral(record_id)
    if referral is None:
        raise HTTPException(status_code=404, detail=f"no referral for audit record {record_id}")

    log_admin_action(
        actor_id=user.id,
        actor_role=user.role,
        actor_org_id=user.org_id,
        action="viewed_referral",
        target_type="audit_record",
        target_id=record_id,
    )
    return ReferralResponse.from_model(referral, get_status_history(referral.id))


@router.patch("/{record_id}/referral", response_model=ReferralResponse)
async def update_referral_status(
    record_id: int,
    request: StatusUpdateRequest,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> ReferralResponse:
    _check_visible(record_id, user)
    if request.status not in STATUS_ORDER:
        raise HTTPException(status_code=422, detail=f"status must be one of {STATUS_ORDER}")
    try:
        referral = advance_status(record_id, request.status, changed_by=user.id)
    except ReferralNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except InvalidStatusTransition as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return ReferralResponse.from_model(referral, get_status_history(referral.id))
