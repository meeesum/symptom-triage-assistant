"""Service-layer tests for app/services/reporting.py — CSV/PDF export
generation. API-layer visibility/access tests live in
test_reports_api.py.
"""

import csv
import io

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.services.patient_panel import assign_patient
from app.services.reporting import build_analytics_pdf, build_audit_csv
from tests._auth_helpers import create_db_user


def _create_audit_record(patient_id: int | None, tier: str = "self_care") -> int:
    with get_session() as session:
        record = TriageAuditRecord(
            patient_id=patient_id,
            symptom_ids=["cough"],
            severity="mild",
            onset="gradual",
            tier=tier,
            matched_rule_id="default_mild_acute",
            decision_source="test",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def test_csv_export_has_header_and_is_parseable():
    csv_bytes = build_audit_csv("admin", user_id=1, days=30)
    reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8")))
    header = next(reader)
    assert header == [
        "id",
        "created_at",
        "tier",
        "symptom_ids",
        "severity",
        "onset",
        "matched_rule_id",
        "requires_human_review",
        "decision_source",
    ]


def test_csv_export_includes_a_real_record():
    marker_patient = create_db_user("patient")
    record_id = _create_audit_record(marker_patient, tier="emergency")

    csv_bytes = build_audit_csv("admin", user_id=1, days=30)
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    matching = [r for r in rows if r and r[0] == str(record_id)]
    assert len(matching) == 1
    assert matching[0][2] == "emergency"
    assert matching[0][3] == "cough"


def test_csv_export_respects_provider_panel_scoping():
    provider_id = create_db_user("provider")
    in_panel_patient = create_db_user("patient")
    outside_patient = create_db_user("patient")
    assign_patient(provider_id, in_panel_patient)

    in_panel_record_id = _create_audit_record(in_panel_patient)
    outside_record_id = _create_audit_record(outside_patient)

    csv_bytes = build_audit_csv("provider", provider_id, days=30)
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    ids_present = {r[0] for r in rows[1:] if r}

    assert str(in_panel_record_id) in ids_present
    assert str(outside_record_id) not in ids_present


def test_pdf_export_produces_real_pdf_bytes():
    _create_audit_record(patient_id=None)
    pdf_bytes = build_analytics_pdf("admin", user_id=1, days=30)
    assert pdf_bytes.startswith(b"%PDF-")
    assert pdf_bytes.endswith(b"%%EOF\n") or b"%%EOF" in pdf_bytes[-16:]


def test_pdf_export_handles_zero_records_without_crashing():
    # An org/provider with no visible records at all — the follow-up
    # stats service returns None averages in this case; the PDF builder
    # must not crash formatting None into a table cell.
    fresh_provider = create_db_user("provider")
    pdf_bytes = build_analytics_pdf("provider", fresh_provider, days=1)
    assert pdf_bytes.startswith(b"%PDF-")
