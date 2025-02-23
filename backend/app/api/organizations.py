"""Organization self-service signup — the actual "onboarding flow" that
lets a second tenant join without an existing platform admin in the
loop. See app/services/organizations.py and docs/phase8a-organizations.md.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.core.db import get_session
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.admin_action_log import log_admin_action
from app.services.organizations import (
    EmailAlreadyExists,
    SlugAlreadyExists,
    create_organization,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


class OrganizationSignupRequest(BaseModel):
    name: str = Field(examples=["Acme Family Clinic"])
    slug: str = Field(examples=["acme-clinic"], pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    admin_email: EmailStr = Field(examples=["admin@acmeclinic.example"])
    admin_password: str = Field(min_length=8)


class OrganizationResponse(BaseModel):
    id: int
    name: str
    slug: str


@router.post("", response_model=OrganizationResponse, status_code=201)
@limiter.limit("5/minute")
async def signup(request: Request, body: OrganizationSignupRequest) -> OrganizationResponse:
    try:
        org = create_organization(
            name=body.name,
            slug=body.slug,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
        )
    except SlugAlreadyExists as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except EmailAlreadyExists as err:
        raise HTTPException(status_code=409, detail=str(err)) from err

    with get_session() as session:
        new_admin = session.execute(
            select(User).where(User.email == body.admin_email)
        ).scalar_one()
        admin_id = new_admin.id
    log_admin_action(
        actor_id=admin_id,
        actor_role="org_admin",
        actor_org_id=org.id,
        action="org_created",
        target_type="organization",
        target_id=org.id,
        detail={"name": org.name, "slug": org.slug},
    )
    return OrganizationResponse(id=org.id, name=org.name, slug=org.slug)
