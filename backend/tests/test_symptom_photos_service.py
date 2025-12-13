"""Service-layer tests for app/services/symptom_photos.py — validation,
storage, and retrieval, independent of the API/auth layer (covered
separately in test_symptom_photos_api.py).
"""

import io

import pytest
from PIL import Image

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
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


def _create_audit_record(patient_id: int | None = None) -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            patient_id=patient_id,
            symptom_ids=["rash"],
            severity="mild",
            onset="gradual",
            tier="self_care",
            decision_source="test",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def _real_jpeg_bytes(size=(40, 40), color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _real_png_bytes(size=(40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, (0, 255, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


def test_get_audit_record_patient_id_raises_for_unknown_record():
    with pytest.raises(AuditRecordNotFound):
        get_audit_record_patient_id(999_999_999)


def test_save_photo_accepts_a_real_jpeg():
    record_id = _create_audit_record(patient_id=1)
    photo = save_photo(record_id, patient_id=1, data=_real_jpeg_bytes())
    assert photo.content_type == "image/jpeg"
    assert photo.audit_record_id == record_id
    assert photo.storage_filename.endswith(".jpg")


def test_save_photo_accepts_a_real_png():
    record_id = _create_audit_record(patient_id=1)
    photo = save_photo(record_id, patient_id=1, data=_real_png_bytes())
    assert photo.content_type == "image/png"
    assert photo.storage_filename.endswith(".png")


def test_save_photo_rejects_non_image_bytes():
    record_id = _create_audit_record(patient_id=1)
    with pytest.raises(InvalidImage):
        save_photo(record_id, patient_id=1, data=b"not an image, just plain bytes" * 20)


def test_save_photo_rejects_a_file_disguised_as_an_image():
    # A file renamed with a .jpg-looking client filename wouldn't matter
    # here anyway (save_photo never sees a client filename at all) — this
    # proves the rejection is content-based, not extension-based, by
    # feeding it plausible-looking-but-fake header bytes.
    record_id = _create_audit_record(patient_id=1)
    fake = b"\xff\xd8\xff" + b"\x00" * 100  # JPEG magic bytes, garbage after
    with pytest.raises(InvalidImage):
        save_photo(record_id, patient_id=1, data=fake)


def test_saved_photo_filename_is_never_derived_from_client_input():
    # save_photo() doesn't even accept a client filename parameter — this
    # test documents that as an invariant, not just an implementation
    # detail: the storage_filename is always uuid4().hex + an extension
    # Pillow itself determined.
    record_id = _create_audit_record(patient_id=1)
    photo = save_photo(record_id, patient_id=1, data=_real_jpeg_bytes())
    stem = photo.storage_filename.rsplit(".", 1)[0]
    assert len(stem) == 32  # uuid4().hex length
    int(stem, 16)  # raises ValueError if it isn't actually hex


def test_read_photo_bytes_roundtrips_the_original_image():
    record_id = _create_audit_record(patient_id=1)
    original = _real_jpeg_bytes(color=(10, 20, 30))
    photo = save_photo(record_id, patient_id=1, data=original)
    assert read_photo_bytes(photo) == original


def test_list_photos_scoped_to_one_audit_record():
    record_a = _create_audit_record(patient_id=1)
    record_b = _create_audit_record(patient_id=1)
    save_photo(record_a, patient_id=1, data=_real_jpeg_bytes())
    save_photo(record_a, patient_id=1, data=_real_png_bytes())
    save_photo(record_b, patient_id=1, data=_real_jpeg_bytes())

    assert len(list_photos(record_a)) == 2
    assert len(list_photos(record_b)) == 1


def test_delete_photo_removes_db_row_and_file():
    record_id = _create_audit_record(patient_id=1)
    photo = save_photo(record_id, patient_id=1, data=_real_jpeg_bytes())
    photo_id = photo.id

    delete_photo(photo)

    assert get_photo(photo_id) is None
    with pytest.raises(FileNotFoundError):
        read_photo_bytes(photo)
