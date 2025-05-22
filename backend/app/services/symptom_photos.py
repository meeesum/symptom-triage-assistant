"""Symptom photo storage and validation.

Scope is deliberately narrow, matching the roadmap's own framing for this
epic: "Secure image upload (e.g. a rash) tied to a chat exchange, with
provider-only review — scoped narrowly so it stays a triage aid, not a
diagnostic claim." Nothing here analyzes, classifies, or draws any
conclusion from a photo's contents — it is stored, validated as a real
image, and made viewable to the patient who uploaded it and any
provider/org_admin/admin who could already see the audit record it's
attached to. No ML model runs on it, ever, in this codebase.

Two independent layers of validation, because a client-declared MIME type
is just a label the client chose and cannot be trusted:
  1. A hard byte-size cap enforced while READING the upload (not by
     trusting the `Content-Length` header, which a client can lie about)
     — see app/api/symptom_photos.py's `_read_capped()`.
  2. Pillow actually opens and verifies the bytes decode as one of the
     allowed image formats. A file renamed from `.php` to `.jpg`, or a
     zip bomb, or plain garbage, fails here regardless of what
     Content-Type header or filename extension the client sent.

Storage is local disk, not an object store (see app/core/config.py's
UPLOAD_DIR) — the on-disk filename is always server-generated (a random
UUID + the extension Pillow itself determined from the decoded image, not
whatever the client's filename claimed), so nothing about a stored path is
ever derived from client input — the path-traversal/overwrite class of
bug this would otherwise invite is closed by construction, not by
sanitization.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from app.core.config import UPLOAD_DIR
from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.models.symptom_photo import SymptomPhoto

# Pillow's own format name -> (canonical content_type, file extension).
# Deliberately a small allowlist, not "whatever Pillow can open" — Pillow
# also opens formats like TIFF, ICO, etc. that aren't sensible for a
# patient's phone-camera photo and would just expand the attack surface.
_ALLOWED_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class AuditRecordNotFound(Exception):
    pass


class InvalidImage(Exception):
    """Bytes that don't decode as one of _ALLOWED_FORMATS — a corrupt
    file, a disguised non-image, or an unsupported format."""


def get_audit_record_patient_id(audit_record_id: int) -> int | None:
    with get_session() as session:
        record = session.get(TriageAuditRecord, audit_record_id)
        if record is None:
            raise AuditRecordNotFound(f"no audit record with id {audit_record_id}")
        return record.patient_id


def _validate_image(data: bytes) -> tuple[str, str]:
    """Returns (content_type, extension) for real, decodable image bytes
    in an allowed format, or raises InvalidImage.

    Image.verify() confirms the file isn't truncated/corrupt but leaves
    the Image object unusable afterward (Pillow's own documented
    behavior) — so decoding happens twice, once to verify and once
    (on a fresh handle) to read `.format`, rather than trying to reuse
    the verified-but-now-inert object.
    """
    try:
        Image.open(io.BytesIO(data)).verify()
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
    except (UnidentifiedImageError, OSError, ValueError) as err:
        raise InvalidImage("file is not a valid image") from err

    if fmt not in _ALLOWED_FORMATS:
        raise InvalidImage(f"unsupported image format: {fmt!r} (allowed: jpeg, png, webp)")
    return _ALLOWED_FORMATS[fmt]


def save_photo(audit_record_id: int, patient_id: int, data: bytes) -> SymptomPhoto:
    """Validates `data` as a real image, writes it to disk under a
    server-generated filename, and records it in the DB. Raises
    InvalidImage if `data` doesn't decode as an allowed format — callers
    are expected to enforce the byte-size cap themselves before calling
    this (see app/api/symptom_photos.py), since that's a request-layer
    concern (reject early, don't even finish reading a too-large body).
    """
    content_type, extension = _validate_image(data)

    record_dir = UPLOAD_DIR / str(audit_record_id)
    record_dir.mkdir(parents=True, exist_ok=True)
    storage_filename = f"{uuid.uuid4().hex}{extension}"
    (record_dir / storage_filename).write_bytes(data)

    with get_session() as session:
        photo = SymptomPhoto(
            audit_record_id=audit_record_id,
            patient_id=patient_id,
            storage_filename=storage_filename,
            content_type=content_type,
            size_bytes=len(data),
        )
        session.add(photo)
        session.commit()
        session.refresh(photo)
        session.expunge(photo)
        return photo


def list_photos(audit_record_id: int) -> list[SymptomPhoto]:
    with get_session() as session:
        rows = (
            session.execute(
                select(SymptomPhoto)
                .where(SymptomPhoto.audit_record_id == audit_record_id)
                .order_by(SymptomPhoto.id)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def list_photos_for_patient(patient_id: int) -> list[SymptomPhoto]:
    """Used by app/services/data_rights.py's deletion flow — a patient's
    photos are keyed by who uploaded them (patient_id), independent of
    which audit record they're attached to, so a "delete my data"
    request needs this rather than list_photos()'s per-record lookup."""
    with get_session() as session:
        rows = (
            session.execute(
                select(SymptomPhoto)
                .where(SymptomPhoto.patient_id == patient_id)
                .order_by(SymptomPhoto.id)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def delete_photos_for_audit_record(audit_record_id: int) -> int:
    """Used by app/services/retention.py's purge job, called BEFORE a
    TriageAuditRecord is hard-deleted — without this, a purged record's
    photos become orphaned: DB rows and on-disk files pointing at an
    audit_record_id that no longer exists (audit_record_id is a plain
    Integer, not a SQLAlchemy ForeignKey, so nothing would even raise an
    error to catch this). Returns the count deleted, for the purge run's
    own reporting."""
    photos = list_photos(audit_record_id)
    for photo in photos:
        delete_photo(photo)
    return len(photos)


def get_photo(photo_id: int) -> SymptomPhoto | None:
    with get_session() as session:
        photo = session.get(SymptomPhoto, photo_id)
        if photo is not None:
            session.expunge(photo)
        return photo


def read_photo_bytes(photo: SymptomPhoto) -> bytes:
    path = _photo_path(photo)
    return path.read_bytes()


def delete_photo(photo: SymptomPhoto) -> None:
    path = _photo_path(photo)
    path.unlink(missing_ok=True)
    with get_session() as session:
        session.delete(session.get(SymptomPhoto, photo.id))
        session.commit()


def _photo_path(photo: SymptomPhoto) -> Path:
    return UPLOAD_DIR / str(photo.audit_record_id) / photo.storage_filename
