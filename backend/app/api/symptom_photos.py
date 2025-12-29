"""Symptom photo upload/review API.

Upload is patient-initiated (the inverse of clinical notes, which are
provider-initiated) — a patient can only upload to an audit record that
is actually theirs (`record.patient_id == current_user.id`); an anonymous
record (`patient_id` is None) or another patient's record 404s, same
existence-hiding pattern used everywhere else in this codebase for
"not yours to see."

Viewing (list metadata + fetch raw bytes) is available to: the owning
patient, or any provider/org_admin/admin who could already see that audit
record via GET /audit/recent — reusing app/services/patient_panel.py's
existing visibility functions rather than defining a new rule, same
pattern ClinicalNote and Referral already established. A provider/
org_admin/admin viewing photos is logged via
app/services/admin_action_log.py, same as viewing clinical notes.

GET /photos/{photo_id} streams the image directly (as a real
`image/jpeg`-etc response, not JSON) so it can be used as an `<img>`
source once fetched — see docs/phase9c-symptom-photo-upload.md for how
the frontend does this despite requiring a bearer token (plain `<img
src="...">` can't send an Authorization header).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user, require_role
from app.core.config import MAX_PHOTO_BYTES
from app.models.symptom_photo import SymptomPhoto
from app.services.admin_action_log import log_admin_action
from app.services.patient_panel import org_admin_can_view_record, provider_can_view_record
from app.services.symptom_photos import (
    AuditRecordNotFound,
    InvalidImage,
    delete_photo,
    get_audit_record_patient_id,
    get_photo,
    list_photos,
    read_photo_bytes,
    save_photo,
)

router = APIRouter(prefix="/audit", tags=["symptom-photos"])


class PhotoResponse(BaseModel):
    id: int
    audit_record_id: int
    content_type: str
    size_bytes: int
    created_at: str | None

    @staticmethod
    def from_model(p: SymptomPhoto) -> PhotoResponse:
        return PhotoResponse(
            id=p.id,
            audit_record_id=p.audit_record_id,
            content_type=p.content_type,
            size_bytes=p.size_bytes,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )


def _record_not_found(record_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"no audit record with id {record_id}")


def _check_viewable(record_id: int, user: CurrentUser) -> None:
    try:
        patient_id = get_audit_record_patient_id(record_id)
    except AuditRecordNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

    if user.role == "patient":
        visible = patient_id == user.id
    elif user.role == "provider":
        visible = provider_can_view_record(user.id, patient_id)
    elif user.role == "org_admin":
        visible = org_admin_can_view_record(user.org_id, patient_id)
    else:  # admin
        visible = True

    if not visible:
        raise _record_not_found(record_id)


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Reads at most `max_bytes + 1` bytes and rejects if the upload is
    larger — never trusts the `Content-Length` header (a client can send
    any value there, or none at all with chunked transfer encoding), and
    never buffers an unbounded amount of a hostile upload into memory
    before deciding to reject it.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"photo exceeds the {max_bytes} byte upload limit",
            )
    return b"".join(chunks)


@router.post("/{record_id}/photos", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    record_id: int,
    file: UploadFile,
    user: CurrentUser = Depends(require_role("patient")),
) -> PhotoResponse:
    try:
        patient_id = get_audit_record_patient_id(record_id)
    except AuditRecordNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

    if patient_id != user.id:
        # Same existence-hiding shape as every other "not yours" case in
        # this codebase — an anonymous record (patient_id is None) hits
        # this branch too, since no patient owns it to upload to.
        raise _record_not_found(record_id)

    data = await _read_capped(file, MAX_PHOTO_BYTES)
    try:
        photo = save_photo(record_id, patient_id=user.id, data=data)
    except InvalidImage as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return PhotoResponse.from_model(photo)


@router.get("/{record_id}/photos", response_model=list[PhotoResponse])
async def list_record_photos(
    record_id: int, user: CurrentUser = Depends(get_current_user)
) -> list[PhotoResponse]:
    _check_viewable(record_id, user)
    if user.role in ("provider", "org_admin", "admin"):
        log_admin_action(
            actor_id=user.id,
            actor_role=user.role,
            actor_org_id=user.org_id,
            action="viewed_symptom_photos",
            target_type="audit_record",
            target_id=record_id,
        )
    return [PhotoResponse.from_model(p) for p in list_photos(record_id)]


@router.get("/{record_id}/photos/{photo_id}")
async def get_photo_bytes(
    record_id: int, photo_id: int, user: CurrentUser = Depends(get_current_user)
) -> Response:
    _check_viewable(record_id, user)
    photo = get_photo(photo_id)
    if photo is None or photo.audit_record_id != record_id:
        raise HTTPException(status_code=404, detail=f"no photo with id {photo_id}")
    return Response(content=read_photo_bytes(photo), media_type=photo.content_type)


@router.delete("/{record_id}/photos/{photo_id}", status_code=204)
async def delete_record_photo(
    record_id: int, photo_id: int, user: CurrentUser = Depends(require_role("patient"))
) -> Response:
    photo = get_photo(photo_id)
    if photo is None or photo.audit_record_id != record_id or photo.patient_id != user.id:
        raise HTTPException(status_code=404, detail=f"no photo with id {photo_id}")
    delete_photo(photo)
    return Response(status_code=204)
