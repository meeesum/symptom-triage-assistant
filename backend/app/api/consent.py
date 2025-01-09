"""Self-service consent tracking — same "personal, not an assignment"
self-service pattern as app/api/notifications.py's preferences: a user
records their own consent decisions, no admin in the loop. See
docs/phase8b-consent-and-data-rights.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user
from app.models.consent import CONSENT_TYPES, ConsentRecord
from app.services.consent import get_consent_history, record_consent

router = APIRouter(prefix="/consent", tags=["consent"])


class ConsentRequest(BaseModel):
    consent_type: str
    granted: bool


class ConsentResponse(BaseModel):
    id: int
    consent_type: str
    granted: bool
    created_at: str | None

    @staticmethod
    def from_model(c: ConsentRecord) -> ConsentResponse:
        return ConsentResponse(
            id=c.id,
            consent_type=c.consent_type,
            granted=c.granted,
            created_at=c.created_at.isoformat() if c.created_at else None,
        )


@router.post("", response_model=ConsentResponse, status_code=201)
async def submit_consent(
    request: ConsentRequest, user: CurrentUser = Depends(get_current_user)
) -> ConsentResponse:
    if request.consent_type not in CONSENT_TYPES:
        raise HTTPException(status_code=422, detail=f"consent_type must be one of {CONSENT_TYPES}")
    record = record_consent(user.id, request.consent_type, request.granted)
    return ConsentResponse.from_model(record)


@router.get("", response_model=list[ConsentResponse])
async def get_my_consent_history(
    user: CurrentUser = Depends(get_current_user),
) -> list[ConsentResponse]:
    return [ConsentResponse.from_model(c) for c in get_consent_history(user.id)]
