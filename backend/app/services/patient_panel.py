"""Provider-patient panel assignment. See app/models/patient_panel.py and
docs/phase7a-patient-panels.md for the design rationale.

Cross-org assignment is rejected in assign_patient() — this is THE single
enforcement point for tenant isolation across this whole codebase (see
app/models/user.py's docstring and docs/phase8a-organizations.md): every
panel-scoped view built in Phase 03 (audit trail, clinical notes,
referrals, analytics, alerts) inherits org isolation for free, because
none of them can ever end up looking at a patient outside the provider's
own organization if a cross-org pair could never be assigned here in the
first place. Enforcing it again at every read site would be duplicated,
driftable logic for the same guarantee.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.models.patient_panel import PatientPanelAssignment
from app.models.user import User


class AssignmentAlreadyExists(Exception):
    pass


class AssignmentNotFound(Exception):
    pass


class CrossOrgAssignmentNotAllowed(Exception):
    pass


class UserNotFound(Exception):
    pass


def assign_patient(provider_id: int, patient_id: int) -> PatientPanelAssignment:
    with get_session() as session:
        provider = session.get(User, provider_id)
        patient = session.get(User, patient_id)
        if provider is None:
            raise UserNotFound(f"no such provider: {provider_id}")
        if patient is None:
            raise UserNotFound(f"no such patient: {patient_id}")
        if provider.org_id != patient.org_id:
            raise CrossOrgAssignmentNotAllowed(
                f"provider {provider_id} (org {provider.org_id}) and patient {patient_id} "
                f"(org {patient.org_id}) belong to different organizations"
            )

        assignment = PatientPanelAssignment(provider_id=provider_id, patient_id=patient_id)
        session.add(assignment)
        try:
            session.commit()
        except IntegrityError as err:
            session.rollback()
            raise AssignmentAlreadyExists(
                f"provider {provider_id} is already assigned patient {patient_id}"
            ) from err
        session.refresh(assignment)
        session.expunge(assignment)
        return assignment


def unassign_patient(assignment_id: int) -> None:
    with get_session() as session:
        assignment = session.get(PatientPanelAssignment, assignment_id)
        if assignment is None:
            raise AssignmentNotFound(f"no panel assignment with id {assignment_id}")
        session.delete(assignment)
        session.commit()


def list_all_assignments(org_id: int | None = None) -> list[PatientPanelAssignment]:
    """org_id=None (platform admin) lists every assignment, every org.
    Otherwise (org_admin) scoped to assignments where the PROVIDER
    belongs to that org — sufficient given assign_patient() already
    guarantees the patient is in the same org too."""
    with get_session() as session:
        query = select(PatientPanelAssignment).order_by(PatientPanelAssignment.id)
        if org_id is not None:
            query = query.join(User, PatientPanelAssignment.provider_id == User.id).where(
                User.org_id == org_id
            )
        rows = session.execute(query).scalars().all()
        for row in rows:
            session.expunge(row)
        return rows


def get_assignment(assignment_id: int) -> PatientPanelAssignment | None:
    with get_session() as session:
        assignment = session.get(PatientPanelAssignment, assignment_id)
        if assignment is not None:
            session.expunge(assignment)
        return assignment


def list_panel_patient_ids(provider_id: int) -> list[int]:
    with get_session() as session:
        return list(
            session.execute(
                select(PatientPanelAssignment.patient_id).where(
                    PatientPanelAssignment.provider_id == provider_id
                )
            ).scalars()
        )


def is_on_panel(provider_id: int, patient_id: int) -> bool:
    with get_session() as session:
        return (
            session.execute(
                select(PatientPanelAssignment.id).where(
                    PatientPanelAssignment.provider_id == provider_id,
                    PatientPanelAssignment.patient_id == patient_id,
                )
            ).scalar_one_or_none()
            is not None
        )


def list_assigned_providers(patient_id: int) -> list[int]:
    """The inverse of list_panel_patient_ids: every provider this patient
    is assigned to. Used by app/services/alerting.py to pick an on-call
    recipient for a high-risk alert."""
    with get_session() as session:
        return list(
            session.execute(
                select(PatientPanelAssignment.provider_id).where(
                    PatientPanelAssignment.patient_id == patient_id
                )
            ).scalars()
        )


def provider_can_view_record(provider_id: int, record_patient_id: int | None) -> bool:
    """Same visibility rule GET /audit/recent applies (app/api/audit.py):
    a record with no patient_id can't be tied to anyone, so it's visible
    to every provider; otherwise the patient must be on this provider's
    panel. Callers gating on the `admin` role should skip this check
    entirely — admin is unrestricted, not "always on every panel"."""
    if record_patient_id is None:
        return True
    return is_on_panel(provider_id, record_patient_id)


def org_admin_can_view_record(org_id: int, record_patient_id: int | None) -> bool:
    """org_admin's equivalent of provider_can_view_record() — scoped to
    their whole ORG's patients, not a provider's own panel (org_admin is
    administrative, not clinical, so "their panel" isn't the right
    boundary — see app/services/audit_visibility.py, added for the same
    reason in docs/phase8c-admin-action-audit-log.md)."""
    if record_patient_id is None:
        return True
    with get_session() as session:
        patient = session.get(User, record_patient_id)
    return patient is not None and patient.org_id == org_id
