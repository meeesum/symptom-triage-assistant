"""GDPR/HIPAA-style self-service data export and deletion. Same
"personal, exercised by the subject" self-service pattern as
app/api/consent.py and app/api/notifications.py's preferences — no admin
in the loop. See app/services/data_rights.py and
docs/phase8b-consent-and-data-rights.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user
from app.models.data_request import DataRequest
from app.services.data_rights import delete_user_data, export_user_data, list_data_requests
from app.services.token_revocation import revoke_token

router = APIRouter(prefix="/data-rights", tags=["data-rights"])


class DataRequestResponse(BaseModel):
    id: int
    request_type: str
    status: str
    summary: str | None
    created_at: str | None

    @staticmethod
    def from_model(r: DataRequest) -> DataRequestResponse:
        return DataRequestResponse(
            id=r.id,
            request_type=r.request_type,
            status=r.status,
            summary=r.summary,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )


@router.post("/export")
async def export_my_data(user: CurrentUser = Depends(get_current_user)) -> dict:
    return export_user_data(user.id)


@router.post("/deletion", response_model=DataRequestResponse)
async def delete_my_data(user: CurrentUser = Depends(get_current_user)) -> DataRequestResponse:
    request = delete_user_data(user.id)
    # The CURRENT access token is revoked here (the API layer has its
    # jti); every refresh token is revoked inside delete_user_data()
    # itself, which only has the user_id, not this specific request's
    # token — see that function's docstring.
    revoke_token(user.jti, user.exp)
    return DataRequestResponse.from_model(request)


@router.get("/requests", response_model=list[DataRequestResponse])
async def get_my_data_requests(
    user: CurrentUser = Depends(get_current_user),
) -> list[DataRequestResponse]:
    return [DataRequestResponse.from_model(r) for r in list_data_requests(user.id)]
