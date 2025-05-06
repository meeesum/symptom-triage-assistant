"""Clinical notes API — provider annotations on a triage audit record.

Gated the same way as GET /audit/recent (app/api/audit.py): a provider
can only read or add notes on a record they could actually see via that
endpoint (their panel, or an anonymous record) — a note is exactly as
sensitive as the record it's attached to, so it inherits the same
visibility rule rather than defining a separate one. `admin` is
unrestricted. See docs/phase7b-clinical-notes.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_role
from app.models.clinical_note import VALID_NOTE_TYPES, ClinicalNote
from app.services.admin_action_log import log_admin_action
from app.services.clinical_notes import (
    AuditRecordNotFound,
    add_note,
    get_audit_record_patient_id,
    list_notes,
)
from app.services.patient_panel import org_admin_can_view_record, provider_can_view_record

router = APIRouter(prefix="/audit", tags=["clinical-notes"])


class NoteRequest(BaseModel):
    body: str = Field(min_length=1)
    note_type: str = "general"


class NoteResponse(BaseModel):
    id: int
    audit_record_id: int
    author_id: int
    note_type: str
    body: str
    created_at: str | None

    @staticmethod
    def from_model(n: ClinicalNote) -> NoteResponse:
        return NoteResponse(
            id=n.id,
            audit_record_id=n.audit_record_id,
            author_id=n.author_id,
            note_type=n.note_type,
            body=n.body,
            created_at=n.created_at.isoformat() if n.created_at else None,
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
        # Same status as "doesn't exist" — a provider/org_admin outside
        # the panel/org shouldn't be able to distinguish "not visible to
        # me" from "no such record" by response shape, matching how
        # /admin's role checks avoid leaking existence info elsewhere in
        # this codebase.
        raise HTTPException(status_code=404, detail=f"no audit record with id {record_id}")


@router.post("/{record_id}/notes", response_model=NoteResponse, status_code=201)
async def create_note(
    record_id: int,
    request: NoteRequest,
    user: CurrentUser = Depends(require_role("provider", "org_admin", "admin")),
) -> NoteResponse:
    if request.note_type not in VALID_NOTE_TYPES:
        raise HTTPException(
            status_code=422, detail=f"note_type must be one of {VALID_NOTE_TYPES}"
        )
    _check_visible(record_id, user)
    note = add_note(record_id, author_id=user.id, body=request.body, note_type=request.note_type)
    return NoteResponse.from_model(note)


@router.get("/{record_id}/notes", response_model=list[NoteResponse])
async def get_notes(
    record_id: int, user: CurrentUser = Depends(require_role("provider", "org_admin", "admin"))
) -> list[NoteResponse]:
    _check_visible(record_id, user)
    # "Who viewed which patient record, when" — the roadmap's own named
    # example for this log (docs/phase8c-admin-action-audit-log.md).
    log_admin_action(
        actor_id=user.id,
        actor_role=user.role,
        actor_org_id=user.org_id,
        action="viewed_clinical_notes",
        target_type="audit_record",
        target_id=record_id,
    )
    return [NoteResponse.from_model(n) for n in list_notes(record_id)]
