"""Clinical review workflow API — submit a KB article draft, a
credentialed reviewer (provider/admin — see app/api/deps.py::require_role)
approves or rejects it. See docs/phase6e-clinical-review-workflow.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_role
from app.models.kb_review import VALID_STATUSES, KbArticleSubmission
from app.services.admin_action_log import log_admin_action
from app.services.kb_review import (
    SelfReviewNotAllowed,
    SubmissionNotFound,
    SubmissionNotPending,
    approve_submission,
    get_article_history,
    list_submissions,
    reject_submission,
    submit_article,
)

router = APIRouter(prefix="/kb-review", tags=["kb-review"])

_REVIEWER_ROLES = ("provider", "admin")


class SubmissionRequest(BaseModel):
    article_id: str = Field(examples=["chest_pain"])
    title: str = Field(examples=["Chest Pain: General Information"])
    tags: list[str] = Field(default_factory=list)
    source_note: str
    body: list[str]


class ReviewDecisionRequest(BaseModel):
    review_note: str | None = None


class RejectionRequest(BaseModel):
    review_note: str = Field(description="Required — reviewers must say why a draft was rejected")


class SubmissionResponse(BaseModel):
    id: int
    article_id: str
    version: int
    title: str
    tags: list[str]
    source_note: str
    body: list[str]
    status: str
    submitted_by: int
    submitted_at: str | None
    reviewed_by: int | None
    reviewed_at: str | None
    review_note: str | None

    @staticmethod
    def from_model(s: KbArticleSubmission) -> SubmissionResponse:
        return SubmissionResponse(
            id=s.id,
            article_id=s.article_id,
            version=s.version,
            title=s.title,
            tags=s.tags,
            source_note=s.source_note,
            body=s.body,
            status=s.status,
            submitted_by=s.submitted_by,
            submitted_at=s.submitted_at.isoformat() if s.submitted_at else None,
            reviewed_by=s.reviewed_by,
            reviewed_at=s.reviewed_at.isoformat() if s.reviewed_at else None,
            review_note=s.review_note,
        )


@router.post("/submissions", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    request: SubmissionRequest,
    user: CurrentUser = Depends(require_role(*_REVIEWER_ROLES)),
) -> SubmissionResponse:
    submission = submit_article(
        article_id=request.article_id,
        title=request.title,
        tags=request.tags,
        source_note=request.source_note,
        body=request.body,
        submitted_by=user.id,
    )
    return SubmissionResponse.from_model(submission)


@router.get("/submissions", response_model=list[SubmissionResponse])
async def get_submissions(
    status: str | None = None,
    _user: CurrentUser = Depends(require_role(*_REVIEWER_ROLES)),
) -> list[SubmissionResponse]:
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {VALID_STATUSES}")
    return [SubmissionResponse.from_model(s) for s in list_submissions(status)]


@router.get("/articles/{article_id}/history", response_model=list[SubmissionResponse])
async def article_history(
    article_id: str,
    _user: CurrentUser = Depends(require_role(*_REVIEWER_ROLES)),
) -> list[SubmissionResponse]:
    return [SubmissionResponse.from_model(s) for s in get_article_history(article_id)]


@router.post("/submissions/{submission_id}/approve", response_model=SubmissionResponse)
async def approve(
    submission_id: int,
    request: ReviewDecisionRequest,
    user: CurrentUser = Depends(require_role(*_REVIEWER_ROLES)),
) -> SubmissionResponse:
    try:
        submission = approve_submission(submission_id, user.id, request.review_note)
    except SubmissionNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SubmissionNotPending as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except SelfReviewNotAllowed as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    log_admin_action(
        actor_id=user.id,
        actor_role=user.role,
        actor_org_id=user.org_id,
        action="kb_submission_approved",
        target_type="kb_article_submission",
        target_id=submission.id,
        detail={"article_id": submission.article_id, "version": submission.version},
    )
    return SubmissionResponse.from_model(submission)


@router.post("/submissions/{submission_id}/reject", response_model=SubmissionResponse)
async def reject(
    submission_id: int,
    request: RejectionRequest,
    user: CurrentUser = Depends(require_role(*_REVIEWER_ROLES)),
) -> SubmissionResponse:
    try:
        submission = reject_submission(submission_id, user.id, request.review_note)
    except SubmissionNotFound as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SubmissionNotPending as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except SelfReviewNotAllowed as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    log_admin_action(
        actor_id=user.id,
        actor_role=user.role,
        actor_org_id=user.org_id,
        action="kb_submission_rejected",
        target_type="kb_article_submission",
        target_id=submission.id,
        detail={"article_id": submission.article_id, "version": submission.version},
    )
    return SubmissionResponse.from_model(submission)
