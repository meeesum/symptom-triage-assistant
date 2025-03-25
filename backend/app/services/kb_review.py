"""Clinical review workflow: submit a KB article draft, a credentialed
reviewer approves or rejects it. See app/models/kb_review.py for the
schema and docs/phase6e-clinical-review-workflow.md for the design
rationale — most importantly, why approval is what actually flips an
article's `reviewed` field to `true` for the first time (see
app/rag/knowledge_base.py), closing a gap every prior KB epic left open.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.db import get_session
from app.models.kb_review import KbArticleSubmission
from app.rag.knowledge_base import write_article_file
from app.rag.retriever import get_default_retriever


class SubmissionNotFound(Exception):
    pass


class SubmissionNotPending(Exception):
    pass


class SelfReviewNotAllowed(Exception):
    pass


def submit_article(
    article_id: str,
    title: str,
    tags: list[str],
    source_note: str,
    body: list[str],
    submitted_by: int,
) -> KbArticleSubmission:
    with get_session() as session:
        latest_version = session.execute(
            select(func.max(KbArticleSubmission.version)).where(
                KbArticleSubmission.article_id == article_id
            )
        ).scalar()

        submission = KbArticleSubmission(
            article_id=article_id,
            version=(latest_version or 0) + 1,
            title=title,
            tags=tags,
            source_note=source_note,
            body=body,
            status="pending",
            submitted_by=submitted_by,
        )
        session.add(submission)
        session.commit()
        session.refresh(submission)
        session.expunge(submission)
        return submission


def list_submissions(status: str | None = None) -> list[KbArticleSubmission]:
    with get_session() as session:
        query = select(KbArticleSubmission).order_by(KbArticleSubmission.id.desc())
        if status is not None:
            query = query.where(KbArticleSubmission.status == status)
        rows = session.execute(query).scalars().all()
        for row in rows:
            session.expunge(row)
        return rows


def get_article_history(article_id: str) -> list[KbArticleSubmission]:
    with get_session() as session:
        rows = (
            session.execute(
                select(KbArticleSubmission)
                .where(KbArticleSubmission.article_id == article_id)
                .order_by(KbArticleSubmission.version.asc())
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _load_pending(session, submission_id: int) -> KbArticleSubmission:
    submission = session.get(KbArticleSubmission, submission_id)
    if submission is None:
        raise SubmissionNotFound(f"no submission with id {submission_id}")
    if submission.status != "pending":
        raise SubmissionNotPending(
            f"submission {submission_id} is already {submission.status}"
        )
    return submission


def approve_submission(
    submission_id: int, reviewed_by: int, review_note: str | None = None
) -> KbArticleSubmission:
    with get_session() as session:
        submission = _load_pending(session, submission_id)
        if submission.submitted_by == reviewed_by:
            raise SelfReviewNotAllowed(
                "a submission cannot be approved by the same user who submitted it"
            )

        article = {
            "id": submission.article_id,
            "title": submission.title,
            "tags": submission.tags,
            "source_note": submission.source_note,
            "body": submission.body,
            "reviewed": True,
            # Still placeholder content, even once reviewed — a real
            # deployment's source_type should only flip to something like
            # "verified_source" once the source_note itself cites a real
            # reference, which this review workflow doesn't verify on its
            # own. See docs/phase6e-clinical-review-workflow.md.
            "source_type": "placeholder",
            "added_date": datetime.now(UTC).date().isoformat(),
        }
        write_article_file(article)
        # The retriever singleton is built once from disk and cached (see
        # get_default_retriever()) — without this, an approval would be
        # silently invisible to every already-running server process
        # until its next restart, defeating the point of a live review
        # workflow.
        get_default_retriever.cache_clear()

        submission.status = "approved"
        submission.reviewed_by = reviewed_by
        submission.review_note = review_note
        submission.reviewed_at = datetime.now(UTC)
        session.commit()
        session.refresh(submission)
        session.expunge(submission)
        return submission


def reject_submission(
    submission_id: int, reviewed_by: int, review_note: str
) -> KbArticleSubmission:
    with get_session() as session:
        submission = _load_pending(session, submission_id)
        if submission.submitted_by == reviewed_by:
            raise SelfReviewNotAllowed(
                "a submission cannot be rejected by the same user who submitted it"
            )

        submission.status = "rejected"
        submission.reviewed_by = reviewed_by
        submission.review_note = review_note
        submission.reviewed_at = datetime.now(UTC)
        session.commit()
        session.refresh(submission)
        session.expunge(submission)
        return submission
