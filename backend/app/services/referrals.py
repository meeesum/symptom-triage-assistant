"""Referral & appointment tracking service. See
app/models/referral.py and docs/phase7c-referral-tracking.md.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.models.referral import STATUS_ORDER, Referral, ReferralStatusChange


class ReferralAlreadyExists(Exception):
    pass


class ReferralNotFound(Exception):
    pass


class InvalidStatusTransition(Exception):
    pass


def create_referral(audit_record_id: int, created_by: int) -> Referral:
    with get_session() as session:
        referral = Referral(audit_record_id=audit_record_id, created_by=created_by)
        session.add(referral)
        try:
            session.flush()
        except IntegrityError as err:
            session.rollback()
            raise ReferralAlreadyExists(
                f"audit record {audit_record_id} already has a referral"
            ) from err

        session.add(
            ReferralStatusChange(
                referral_id=referral.id,
                from_status=None,
                to_status="referred",
                changed_by=created_by,
            )
        )
        session.commit()
        session.refresh(referral)
        session.expunge(referral)
        return referral


def get_referral(audit_record_id: int) -> Referral | None:
    with get_session() as session:
        referral = session.execute(
            select(Referral).where(Referral.audit_record_id == audit_record_id)
        ).scalar_one_or_none()
        if referral is not None:
            session.expunge(referral)
        return referral


def get_status_history(referral_id: int) -> list[ReferralStatusChange]:
    with get_session() as session:
        rows = (
            session.execute(
                select(ReferralStatusChange)
                .where(ReferralStatusChange.referral_id == referral_id)
                .order_by(ReferralStatusChange.id)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def advance_status(audit_record_id: int, new_status: str, changed_by: int) -> Referral:
    """Forward-only: a referral can only move to a status LATER in
    STATUS_ORDER than its current one (skipping stages is allowed — e.g.
    referred straight to seen for a same-day walk-in — but going
    backward, or re-setting the same status, is not. See
    docs/phase7c-referral-tracking.md for why."""
    if new_status not in STATUS_ORDER:
        raise InvalidStatusTransition(
            f"unknown status {new_status!r}, must be one of {STATUS_ORDER}"
        )

    with get_session() as session:
        referral = session.execute(
            select(Referral).where(Referral.audit_record_id == audit_record_id)
        ).scalar_one_or_none()
        if referral is None:
            raise ReferralNotFound(f"audit record {audit_record_id} has no referral")

        current_index = STATUS_ORDER.index(referral.status)
        new_index = STATUS_ORDER.index(new_status)
        if new_index <= current_index:
            raise InvalidStatusTransition(
                f"cannot move referral from {referral.status!r} to {new_status!r} "
                "— status can only move forward"
            )

        old_status = referral.status
        referral.status = new_status
        session.add(
            ReferralStatusChange(
                referral_id=referral.id,
                from_status=old_status,
                to_status=new_status,
                changed_by=changed_by,
            )
        )
        session.commit()
        session.refresh(referral)
        session.expunge(referral)
        return referral
