"""Self-service notification preferences — the current user manages
their OWN preferences. Unlike patient panels or role assignment (admin-
controlled, because those are assignments/permissions), which channel a
person wants alerts on is a personal preference, not something that
needs an admin in the loop. See docs/phase7f-notifications.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user
from app.services.notifications import get_preferences, set_preferences

router = APIRouter(prefix="/notifications", tags=["notifications"])

_DEFAULT_EMAIL_ENABLED = True
_DEFAULT_SMS_ENABLED = False


class PreferencesRequest(BaseModel):
    email_enabled: bool = _DEFAULT_EMAIL_ENABLED
    sms_enabled: bool = _DEFAULT_SMS_ENABLED
    phone_number: str | None = None


class PreferencesResponse(BaseModel):
    email_enabled: bool
    sms_enabled: bool
    phone_number: str | None


@router.get("/preferences", response_model=PreferencesResponse)
async def get_my_preferences(
    user: CurrentUser = Depends(get_current_user),
) -> PreferencesResponse:
    pref = get_preferences(user.id)
    if pref is None:
        # No row yet — a user who never set preferences gets the same
        # defaults notify_user() itself falls back to, not a 404. There's
        # nothing "missing" about not having customized this yet.
        return PreferencesResponse(
            email_enabled=_DEFAULT_EMAIL_ENABLED,
            sms_enabled=_DEFAULT_SMS_ENABLED,
            phone_number=None,
        )
    return PreferencesResponse(
        email_enabled=pref.email_enabled,
        sms_enabled=pref.sms_enabled,
        phone_number=pref.phone_number,
    )


@router.put("/preferences", response_model=PreferencesResponse)
async def update_my_preferences(
    request: PreferencesRequest,
    user: CurrentUser = Depends(get_current_user),
) -> PreferencesResponse:
    pref = set_preferences(
        user_id=user.id,
        email_enabled=request.email_enabled,
        sms_enabled=request.sms_enabled,
        phone_number=request.phone_number,
    )
    return PreferencesResponse(
        email_enabled=pref.email_enabled,
        sms_enabled=pref.sms_enabled,
        phone_number=pref.phone_number,
    )
