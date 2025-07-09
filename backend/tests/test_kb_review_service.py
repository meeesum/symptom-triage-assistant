"""Service-layer tests for the clinical review workflow — see
app/services/kb_review.py and docs/phase6e-clinical-review-workflow.md.

write_article_file is monkeypatched to a tmp_path throughout so these
tests never touch the real data/knowledge_base/articles/ directory.
"""

import pytest

from app.services import kb_review


@pytest.fixture(autouse=True)
def _redirect_article_writes(tmp_path, monkeypatch):
    written = {}

    def _fake_write(article, kb_dir=None):
        written["article"] = article
        return tmp_path / f"{article['id']}.json"

    monkeypatch.setattr(kb_review, "write_article_file", _fake_write)
    return written


def test_submit_article_starts_at_version_one():
    submission = kb_review.submit_article(
        article_id="test_topic",
        title="Test Topic",
        tags=["test_topic"],
        source_note="PLACEHOLDER",
        body=["First paragraph."],
        submitted_by=1,
    )
    assert submission.version == 1
    assert submission.status == "pending"


def test_second_submission_for_same_article_increments_version():
    kb_review.submit_article("test_topic2", "Title", [], "note", ["p1"], submitted_by=1)
    second = kb_review.submit_article("test_topic2", "Title v2", [], "note", ["p2"], submitted_by=1)
    assert second.version == 2


def test_approve_writes_article_file_and_marks_approved(_redirect_article_writes):
    submission = kb_review.submit_article(
        "test_topic3", "Title", ["tag1"], "note", ["p1"], submitted_by=1
    )
    approved = kb_review.approve_submission(submission.id, reviewed_by=2, review_note="looks good")

    assert approved.status == "approved"
    assert approved.reviewed_by == 2
    assert approved.review_note == "looks good"
    assert approved.reviewed_at is not None

    written = _redirect_article_writes["article"]
    assert written["id"] == "test_topic3"
    assert written["reviewed"] is True
    assert written["body"] == ["p1"]


def test_reject_does_not_write_article_file(_redirect_article_writes):
    submission = kb_review.submit_article(
        "test_topic4", "Title", [], "note", ["p1"], submitted_by=1
    )
    rejected = kb_review.reject_submission(submission.id, reviewed_by=2, review_note="not accurate")

    assert rejected.status == "rejected"
    assert rejected.review_note == "not accurate"
    assert "article" not in _redirect_article_writes


def test_approve_rejects_self_review():
    submission = kb_review.submit_article(
        "test_topic5", "Title", [], "note", ["p1"], submitted_by=1
    )
    with pytest.raises(kb_review.SelfReviewNotAllowed):
        kb_review.approve_submission(submission.id, reviewed_by=1)


def test_reject_rejects_self_review():
    submission = kb_review.submit_article(
        "test_topic6", "Title", [], "note", ["p1"], submitted_by=1
    )
    with pytest.raises(kb_review.SelfReviewNotAllowed):
        kb_review.reject_submission(submission.id, reviewed_by=1, review_note="n/a")


def test_approve_unknown_submission_raises_not_found():
    with pytest.raises(kb_review.SubmissionNotFound):
        kb_review.approve_submission(999999, reviewed_by=2)


def test_approve_already_reviewed_submission_raises_not_pending():
    submission = kb_review.submit_article(
        "test_topic7", "Title", [], "note", ["p1"], submitted_by=1
    )
    kb_review.approve_submission(submission.id, reviewed_by=2)

    with pytest.raises(kb_review.SubmissionNotPending):
        kb_review.approve_submission(submission.id, reviewed_by=3)


def test_list_submissions_filters_by_status():
    kb_review.submit_article("test_topic8", "T", [], "n", ["p"], submitted_by=1)
    pending = kb_review.list_submissions(status="pending")
    approved = kb_review.list_submissions(status="approved")
    assert any(s.article_id == "test_topic8" for s in pending)
    assert not any(s.article_id == "test_topic8" for s in approved)


def test_article_history_returns_versions_in_order():
    kb_review.submit_article("test_topic9", "V1", [], "n", ["p1"], submitted_by=1)
    kb_review.submit_article("test_topic9", "V2", [], "n", ["p2"], submitted_by=1)
    history = kb_review.get_article_history("test_topic9")
    assert [s.version for s in history] == [1, 2]
    assert [s.title for s in history] == ["V1", "V2"]
