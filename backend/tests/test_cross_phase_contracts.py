"""Cross-phase contract tests — integration tests specifically at the
SEAMS between features built independently in different epics, where
bugs hide when two things that were each individually correct start
interacting. See docs/phase10c-cross-phase-contract-tests.md.

Every other test file in this suite verifies one feature in isolation
(often with a real DB, but exercising just that feature's own service/
API). These tests deliberately combine features from DIFFERENT epics in
one scenario — org isolation (Phase 04) constraining every panel-scoped
feature built across Phase 03, retention purge (Phase 04) interacting
with symptom photos (Phase 05, built a full epic later), data-rights
deletion (Phase 04) interacting with the same later-built photo feature
— because that's exactly where two independently-correct pieces of code
can produce a wrong RESULT together, even though neither one has a bug
you'd find testing it alone.

Two of these tests (TestDataRightsDeletionAndSymptomPhotos,
TestRetentionPurgeAndSymptomPhotos) are regression tests for real gaps
this epic found and fixed: symptom photo upload (Phase 05) was built a
full epic after both data-rights deletion and retention purge (Phase 04)
and was never wired back into either — a "delete my data" request and a
routine retention purge both used to leave a patient's uploaded photos
(and their on-disk files) completely untouched, indefinitely.
"""

import itertools

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.models.consent import ConsentRecord
from app.models.data_request import DataRequest
from app.models.retention_purge_run import RetentionPurgeRun
from app.main import app
from app.services.data_rights import delete_user_data
from app.services.organizations import create_organization
from app.services.patient_panel import assign_patient
from app.services.retention import purge_old_data
from app.services.symptom_photos import get_photo, list_photos, read_photo_bytes, save_photo
from tests._auth_helpers import create_db_user

client = TestClient(app)


_org_counter = itertools.count()


def _create_org(prefix: str) -> int:
    n = next(_org_counter)
    org = create_organization(
        name=f"{prefix} Org",
        slug=f"{prefix.lower()}-{n}",
        admin_email=f"{prefix.lower()}-admin-{n}@example.com",
        admin_password="correct-horse-battery-staple",
    )
    return org.id


def _create_audit_record(patient_id: int | None, **overrides) -> int:
    kwargs = dict(
        patient_id=patient_id,
        symptom_ids=overrides.get("symptom_ids", ["chest_pain", "shortness_of_breath"]),
        severity=overrides.get("severity", "severe"),
        onset=overrides.get("onset", "sudden"),
        tier=overrides.get("tier", "emergency"),
        matched_rule_id=overrides.get("matched_rule_id", "cardiac_event_pattern"),
        decision_source="test",
    )
    # Only set created_at when explicitly overridden — passing None
    # explicitly (rather than leaving the attribute unset) would make
    # SQLAlchemy insert a literal NULL instead of letting the column's
    # server_default=func.now() apply, which would fail against the
    # NOT NULL column.
    if overrides.get("created_at") is not None:
        kwargs["created_at"] = overrides["created_at"]

    with get_session() as session:
        record = TriageAuditRecord(**kwargs)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def _jpeg_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 40, 40)).save(buf, format="JPEG")
    return buf.getvalue()


# ------------------------------------------------------- org isolation
# "org isolation under panels" — named directly in the roadmap's own
# scope for this epic.


class TestOrgIsolationAcrossPanelScopedFeatures:
    """One shared scenario, checked against every panel-scoped feature
    built across Phase 03 (audit, clinical notes, referrals, analytics)
    — not one test per feature in isolation, since the point is that
    ALL of them consistently respect the SAME org boundary a provider in
    a different org from the patient should never cross."""

    def _setup(self):
        org_a = _create_org("ContractA")
        org_b = _create_org("ContractB")

        provider_a = create_db_user("provider", org_id=org_a)
        patient_a = create_db_user("patient", org_id=org_a)
        assign_patient(provider_a, patient_a)

        outsider_provider_b = create_db_user("provider", org_id=org_b)

        # Real emergency triage, attributed to patient_a, via the actual
        # audit-logging path (not a hand-built row) — this is what a
        # panel-scoped read is actually supposed to surface. Logging in
        # as patient_a for real and submitting a real triage proves the
        # WHOLE chain (extraction -> safety engine -> audit log ->
        # panel-scoped read) works together, not just the panel query.
        # create_db_user() already sets the standard test password.
        with get_session() as session:
            from app.models.user import User

            patient_email = session.get(User, patient_a).email

        login_r = client.post(
            "/auth/login", json={"email": patient_email, "password": "correct-horse-battery-staple"}
        )
        patient_token = login_r.json()["access_token"]

        triage_r = client.post(
            "/triage/intake",
            json={"text": "sudden severe chest pain and I'm sweating"},
            headers={"Authorization": f"Bearer {patient_token}"},
        )
        assert triage_r.status_code == 200
        record_id = triage_r.json()["audit_record_id"]
        assert record_id is not None

        provider_a_token = _login_as_provider(provider_a)
        outsider_token = _login_as_provider(outsider_provider_b)
        return record_id, provider_a_token, outsider_token

    def test_audit_trail_respects_org_boundary(self):
        record_id, provider_a_token, outsider_token = self._setup()

        own_r = client.get(
            "/audit/recent?limit=50", headers={"Authorization": f"Bearer {provider_a_token}"}
        )
        assert any(r["id"] == record_id for r in own_r.json())

        outsider_r = client.get(
            "/audit/recent?limit=50", headers={"Authorization": f"Bearer {outsider_token}"}
        )
        assert not any(r["id"] == record_id for r in outsider_r.json())

    def test_clinical_notes_respect_org_boundary(self):
        record_id, provider_a_token, outsider_token = self._setup()

        own_r = client.post(
            f"/audit/{record_id}/notes",
            json={"body": "Advised ER visit."},
            headers={"Authorization": f"Bearer {provider_a_token}"},
        )
        assert own_r.status_code == 201

        outsider_r = client.post(
            f"/audit/{record_id}/notes",
            json={"body": "should not be able to add this"},
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert outsider_r.status_code == 404  # existence-hidden, same as every other "not yours" case

    def test_referrals_respect_org_boundary(self):
        record_id, provider_a_token, outsider_token = self._setup()

        own_r = client.post(
            f"/audit/{record_id}/referral",
            headers={"Authorization": f"Bearer {provider_a_token}"},
        )
        assert own_r.status_code == 201

        outsider_r = client.get(
            f"/audit/{record_id}/referral",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert outsider_r.status_code == 404

    def test_analytics_respect_org_boundary(self):
        _record_id, provider_a_token, outsider_token = self._setup()

        own_r = client.get(
            "/audit/analytics?days=1", headers={"Authorization": f"Bearer {provider_a_token}"}
        )
        outsider_r = client.get(
            "/audit/analytics?days=1", headers={"Authorization": f"Bearer {outsider_token}"}
        )
        assert own_r.status_code == 200 and outsider_r.status_code == 200
        # The emergency triage just submitted must count toward the
        # owning provider's tier distribution — analytics.py delegates to
        # the exact same audit_visibility_clause the raw audit-trail read
        # uses (test_audit_trail_respects_org_boundary), so this locks in
        # that the two stay consistent with each other rather than
        # re-asserting the outsider's exact count here (other tests in
        # this suite may legitimately contribute their own anonymous or
        # same-org emergencies to the outsider's own view).
        assert own_r.json()["tier_distribution"]["emergency"] >= 1


def _login_as_provider(user_id: int) -> str:
    with get_session() as session:
        from app.models.user import User

        user = session.get(User, user_id)
        email = user.email
    r = client.post("/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ------------------------------------------------ reporting × org isolation


class TestReportingExportsRespectOrgIsolation:
    def test_csv_export_excludes_other_orgs_records(self):
        import csv
        import io

        org_a = _create_org("ExportA")
        org_b = _create_org("ExportB")
        org_admin_a = create_db_user("org_admin", org_id=org_a)
        patient_b = create_db_user("patient", org_id=org_b)

        record_id = _create_audit_record(patient_b, tier="emergency")

        from app.services.reporting import build_audit_csv

        csv_bytes = build_audit_csv("org_admin", org_admin_a, org_id=org_a, days=3650)
        # Parse the CSV and check the `id` COLUMN specifically, not a raw
        # substring search over the whole blob — a naive `str(record_id)
        # in csv_bytes` check is a real false-positive trap in a shared
        # test DB: record_id could coincidentally appear inside another
        # row's date, a different row's id, or any digit-containing field
        # from a completely unrelated test, without org isolation having
        # leaked anything at all.
        rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
        ids_present = {int(row["id"]) for row in rows}
        assert record_id not in ids_present


# ------------------------------------------- retention × consent/data-rights
# "retention jobs against real consent records" — named directly in the
# roadmap's own scope for this epic.


class TestRetentionNeverTouchesComplianceRecords:
    def test_purge_leaves_old_consent_records_untouched(self):
        from datetime import UTC, datetime, timedelta

        patient_id = create_db_user("patient")
        with get_session() as session:
            record = ConsentRecord(user_id=patient_id, consent_type="data_processing", granted=True)
            session.add(record)
            session.commit()
            session.refresh(record)
            record_id = record.id
            # Backdate well past every retention window this purge uses,
            # to prove age alone doesn't matter for this table — it's
            # never even queried, not just "not old enough yet."
            session.execute(
                ConsentRecord.__table__.update()
                .where(ConsentRecord.id == record_id)
                .values(created_at=datetime.now(UTC) - timedelta(days=3650))
            )
            session.commit()

        purge_old_data()

        with get_session() as session:
            assert session.get(ConsentRecord, record_id) is not None

    def test_purge_leaves_old_data_requests_untouched(self):
        from datetime import UTC, datetime, timedelta

        patient_id = create_db_user("patient")
        with get_session() as session:
            req = DataRequest(
                user_id=patient_id, request_type="export", status="completed", summary="test"
            )
            session.add(req)
            session.commit()
            session.refresh(req)
            req_id = req.id
            session.execute(
                DataRequest.__table__.update()
                .where(DataRequest.id == req_id)
                .values(created_at=datetime.now(UTC) - timedelta(days=3650))
            )
            session.commit()

        purge_old_data()

        with get_session() as session:
            assert session.get(DataRequest, req_id) is not None


# ------------------------------------------ data rights × symptom photos
# Regression test for a real gap this epic found: delete_user_data()
# never touched a patient's uploaded photos at all before this fix.


class TestDataRightsDeletionAndSymptomPhotos:
    def test_deleting_user_data_also_deletes_their_photos(self):
        patient_id = create_db_user("patient")
        record_id = _create_audit_record(patient_id, tier="routine")
        photo = save_photo(record_id, patient_id=patient_id, data=_jpeg_bytes())

        delete_user_data(patient_id)

        assert get_photo(photo.id) is None
        import pytest

        with pytest.raises(FileNotFoundError):
            read_photo_bytes(photo)

    def test_deletion_summary_reports_photo_count(self):
        patient_id = create_db_user("patient")
        record_id = _create_audit_record(patient_id, tier="routine")
        save_photo(record_id, patient_id=patient_id, data=_jpeg_bytes())
        save_photo(record_id, patient_id=patient_id, data=_jpeg_bytes())

        result = delete_user_data(patient_id)
        assert "2 symptom photo(s) deleted" in result.summary


# --------------------------------------------- retention × symptom photos
# Regression test for the second real gap this epic found: purge_old_data()
# never touched symptom_photos, orphaning both the DB rows and the files
# on disk when the audit record they were attached to got purged.


class TestRetentionPurgeAndSymptomPhotos:
    def test_purging_an_old_audit_record_also_deletes_its_photos(self):
        from datetime import UTC, datetime, timedelta

        patient_id = create_db_user("patient")
        old_timestamp = datetime.now(UTC) - timedelta(days=3650)
        record_id = _create_audit_record(patient_id, tier="routine", created_at=old_timestamp)
        photo = save_photo(record_id, patient_id=patient_id, data=_jpeg_bytes())

        run = purge_old_data()

        with get_session() as session:
            assert session.get(TriageAuditRecord, record_id) is None
        assert get_photo(photo.id) is None
        import pytest

        with pytest.raises(FileNotFoundError):
            read_photo_bytes(photo)
        assert run.symptom_photos_deleted >= 1

    def test_purge_run_is_recorded_with_photo_count(self):
        with get_session() as session:
            runs = session.execute(select(RetentionPurgeRun)).scalars().all()
        # Sanity: the model/column actually round-trips through a real
        # session (not just present on the dataclass) — every run created
        # by the tests above should have a real, non-negative count.
        assert all(r.symptom_photos_deleted >= 0 for r in runs)

    def test_recent_audit_records_keep_their_photos_after_purge(self):
        # The other, equally important half of this contract: purge must
        # NOT delete photos belonging to records that are still within
        # the retention window — only genuinely old ones.
        patient_id = create_db_user("patient")
        record_id = _create_audit_record(patient_id, tier="routine")  # created_at = now
        photo = save_photo(record_id, patient_id=patient_id, data=_jpeg_bytes())

        purge_old_data()

        assert get_photo(photo.id) is not None
        assert len(list_photos(record_id)) == 1


# ---------------------------------------- panel assignment × org changes
# A dormant risk found (not fixed — see docs/phase10c-cross-phase-
# contract-tests.md) while investigating this epic: org isolation is
# enforced ONCE, at panel-ASSIGNMENT write-time (assign_patient() rejects
# a cross-org pair) — but every downstream READER (audit_visibility's
# provider branch, analytics, alerting's recipient resolution) trusts the
# assignment table without re-checking org_id at read time. Currently
# UNREACHABLE via any real code path (no endpoint anywhere changes a
# user's org_id after creation — only role changes exist), so this test
# simulates the hypothetical directly at the DB layer specifically to
# document the assumption for whoever adds an org-transfer feature later:
# if that ever ships, this exact test starts failing, which is the point.


class TestStalePanelAssignmentAfterHypotheticalOrgChange:
    def test_provider_still_sees_patient_after_patients_org_id_changes(self):
        from app.models.user import User
        from app.services.patient_panel import provider_can_view_record

        org_a = _create_org("StaleA")
        org_b = _create_org("StaleB")
        provider = create_db_user("provider", org_id=org_a)
        patient = create_db_user("patient", org_id=org_a)
        assign_patient(provider, patient)
        assert provider_can_view_record(provider, patient) is True

        # No real endpoint does this today — simulating a hypothetical
        # future "transfer this patient to another org" feature.
        with get_session() as session:
            session.get(User, patient).org_id = org_b
            session.commit()

        # Documents current, dormant behavior: still trusts the now-stale
        # assignment. If this ever becomes reachable via a real feature,
        # provider_can_view_record (and analytics.py, and alerting's
        # recipient resolution, which all share this same trust) would
        # need to re-check org_id at read time, not just at assignment
        # time — see this class's own module-level comment.
        assert provider_can_view_record(provider, patient) is True
