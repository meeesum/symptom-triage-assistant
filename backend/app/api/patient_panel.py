"""Provider-patient panel assignment API.

Admin-controlled, same pattern as role assignment (app/api/admin.py): a
provider doesn't add patients to their own panel — an "admin" (platform
or org_admin) assigns them. A provider can only read their OWN panel
(GET /panel/mine); org_admin sees/manages only assignments within their
own org (platform admin sees everything). This is where cross-org
assignment is actually rejected — see
app/services/patient_panel.py's assign_patient() and
docs/phase8a-organizations.md for why this one enforcement point is what
makes every downstream panel-scoped view tenant-isolated for free.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, require_role
from app.core.db import get_session
from app.models.patient_panel import PatientPanelAssignment
from app.models.user import User
from app.services.admin_action_log import log_admin_action
from app.services.patient_panel import (
    AssignmentAlreadyExists,
    AssignmentNotFound,
    CrossOrgAssignmentNotAllowed,
    UserNotFound,
    assign_patient,
    get_assignment,
    list_all_assignments,
    list_panel_patient_ids,
    unassign_patient,
)

router = APIRouter(prefix="/panel", tags=["panel"])


class AssignmentRequest(BaseModel):
    provider_id: int
    patient_id: int


class AssignmentResponse(BaseModel):
    id: int
    provider_id: int
    patient_id: int
    assigned_at: str | None

    @staticmethod
    def from_model(a: PatientPanelAssignment) -> AssignmentResponse:
        return AssignmentResponse(
            id=a.id,
            provider_id=a.provider_id,
            patient_id=a.patient_id,
            assigned_at=a.assigned_at.isoformat() if a.assigned_at else None,
        )


class PanelPatientSummary(BaseModel):
    id: int
    email: str


def _require_role(user_id: int, expected_role: str, label: str) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"no such {label}: {user_id}")
        if user.role != expected_role:
            raise HTTPException(
                status_code=422,
                detail=f"{label} {user_id} has role {user.role!r}, not {expected_role!r}",
            )


@router.post("/assignments", response_model=AssignmentResponse, status_code=201)
async def create_assignment(
    request: AssignmentRequest,
    admin: CurrentUser = Depends(require_role("admin", "org_admin")),
) -> AssignmentResponse:
    _require_role(request.provider_id, "provider", "provider_id")
    _require_role(request.patient_id, "patient", "patient_id")
    if admin.role == "org_admin":
        # A cross-org attempt would also be rejected by assign_patient()
        # itself, but that 403-vs-422 distinction matters: an org_admin
        # naming a user outside their own org shouldn't even get a
        # "different orgs" error revealing that user's org membership —
        # same existence-hiding judgment as elsewhere in this codebase.
        targets = ((request.provider_id, "provider_id"), (request.patient_id, "patient_id"))
        for uid, label in targets:
            with get_session() as session:
                target = session.get(User, uid)
            if target is None or target.org_id != admin.org_id:
                raise HTTPException(status_code=404, detail=f"no such {label}: {uid}")
    try:
        assignment = assign_patient(request.provider_id, request.patient_id)
    except AssignmentAlreadyExists as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except CrossOrgAssignmentNotAllowed as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except UserNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

    log_admin_action(
        actor_id=admin.id,
        actor_role=admin.role,
        actor_org_id=admin.org_id,
        action="panel_assign",
        target_type="patient_panel_assignment",
        target_id=assignment.id,
        detail={"provider_id": assignment.provider_id, "patient_id": assignment.patient_id},
    )
    return AssignmentResponse.from_model(assignment)


@router.delete("/assignments/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: int,
    admin: CurrentUser = Depends(require_role("admin", "org_admin")),
) -> None:
    if admin.role == "org_admin":
        assignment = get_assignment(assignment_id)
        if assignment is not None:
            with get_session() as session:
                provider = session.get(User, assignment.provider_id)
            if provider is None or provider.org_id != admin.org_id:
                raise HTTPException(status_code=404, detail="no such assignment")
    try:
        unassign_patient(assignment_id)
    except AssignmentNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

    log_admin_action(
        actor_id=admin.id,
        actor_role=admin.role,
        actor_org_id=admin.org_id,
        action="panel_unassign",
        target_type="patient_panel_assignment",
        target_id=assignment_id,
    )


@router.get("/assignments", response_model=list[AssignmentResponse])
async def get_all_assignments(
    admin: CurrentUser = Depends(require_role("admin", "org_admin")),
) -> list[AssignmentResponse]:
    org_id = admin.org_id if admin.role == "org_admin" else None
    return [AssignmentResponse.from_model(a) for a in list_all_assignments(org_id)]


@router.get("/mine", response_model=list[PanelPatientSummary])
async def get_my_panel(
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> list[PanelPatientSummary]:
    patient_ids = list_panel_patient_ids(user.id)
    if not patient_ids:
        return []
    with get_session() as session:
        patients = session.execute(select(User).where(User.id.in_(patient_ids))).scalars().all()
        return [PanelPatientSummary(id=p.id, email=p.email) for p in patients]
