"""API-level tests for the clinical review workflow —
POST/GET /kb-review/* — see app/api/kb_review.py.

write_article_file is monkeypatched throughout so these tests never
touch the real data/knowledge_base/articles/ directory.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import kb_review
from tests._auth_helpers import register_and_get_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def _redirect_article_writes(tmp_path, monkeypatch):
    def _fake_write(article, kb_dir=None):
        return tmp_path / f"{article['id']}.json"

    monkeypatch.setattr(kb_review, "write_article_file", _fake_write)


def _submit(token, article_id="api_test_topic"):
    return client.post(
        "/kb-review/submissions",
        json={
            "article_id": article_id,
            "title": "API Test Topic",
            "tags": ["api_test_topic"],
            "source_note": "PLACEHOLDER",
            "body": ["First paragraph."],
        },
        headers={"Authorization": f"Bearer {token}"},
    )


def test_patient_cannot_submit():
    token = register_and_get_token(client, role="patient")
    r = _submit(token)
    assert r.status_code == 403


def test_provider_can_submit():
    token = register_and_get_token(client, role="provider")
    r = _submit(token)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["version"] == 1


def test_anonymous_cannot_submit():
    r = client.post(
        "/kb-review/submissions",
        json={"article_id": "x", "title": "X", "tags": [], "source_note": "n", "body": ["p"]},
    )
    assert r.status_code == 401


def test_provider_can_approve_a_different_providers_submission():
    author_token = register_and_get_token(client, role="provider")
    reviewer_token = register_and_get_token(client, role="provider")

    submit_r = _submit(author_token, article_id="approve_test_topic")
    submission_id = submit_r.json()["id"]

    r = client.post(
        f"/kb-review/submissions/{submission_id}/approve",
        json={"review_note": "looks accurate"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["review_note"] == "looks accurate"


def test_self_approval_is_rejected():
    token = register_and_get_token(client, role="provider")
    submit_r = _submit(token, article_id="self_approve_test_topic")
    submission_id = submit_r.json()["id"]

    r = client.post(
        f"/kb-review/submissions/{submission_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_reject_requires_a_review_note():
    author_token = register_and_get_token(client, role="provider")
    reviewer_token = register_and_get_token(client, role="provider")
    submit_r = _submit(author_token, article_id="reject_test_topic")
    submission_id = submit_r.json()["id"]

    r = client.post(
        f"/kb-review/submissions/{submission_id}/reject",
        json={},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert r.status_code == 422


def test_reject_with_note_succeeds():
    author_token = register_and_get_token(client, role="provider")
    reviewer_token = register_and_get_token(client, role="provider")
    submit_r = _submit(author_token, article_id="reject_test_topic2")
    submission_id = submit_r.json()["id"]

    r = client.post(
        f"/kb-review/submissions/{submission_id}/reject",
        json={"review_note": "source_note isn't specific enough"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_approving_twice_returns_conflict():
    author_token = register_and_get_token(client, role="provider")
    reviewer_token = register_and_get_token(client, role="provider")
    submit_r = _submit(author_token, article_id="double_approve_test_topic")
    submission_id = submit_r.json()["id"]

    client.post(
        f"/kb-review/submissions/{submission_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    r = client.post(
        f"/kb-review/submissions/{submission_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert r.status_code == 409


def test_approving_unknown_submission_returns_404():
    token = register_and_get_token(client, role="provider")
    r = client.post(
        "/kb-review/submissions/99999999/approve",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_list_submissions_requires_reviewer_role():
    patient_token = register_and_get_token(client, role="patient")
    r = client.get(
        "/kb-review/submissions", headers={"Authorization": f"Bearer {patient_token}"}
    )
    assert r.status_code == 403


def test_list_submissions_filters_by_status():
    token = register_and_get_token(client, role="provider")
    _submit(token, article_id="filter_test_topic")

    r = client.get(
        "/kb-review/submissions?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert any(s["article_id"] == "filter_test_topic" for s in r.json())


def test_list_submissions_rejects_invalid_status():
    token = register_and_get_token(client, role="provider")
    r = client.get(
        "/kb-review/submissions?status=bogus",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_article_history_returns_all_versions():
    token = register_and_get_token(client, role="provider")
    _submit(token, article_id="history_test_topic")
    _submit(token, article_id="history_test_topic")

    r = client.get(
        "/kb-review/articles/history_test_topic/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    versions = [s["version"] for s in r.json()]
    assert versions == [1, 2]
