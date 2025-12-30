"""Organization (tenant) creation and lookup. See
app/models/organization.py and docs/phase8a-organizations.md.

DEFAULT_ORG_SLUG is the zero-setup landing spot for a registration that
doesn't specify org_slug — same "zero-setup default, real usage opt-in"
pattern as everything else in this codebase, applied to multi-tenancy:
every test and every pre-existing single-tenant workflow keeps working
unchanged, landing in one shared default organization, while a real
deployment onboarding a second tenant uses create_organization() (via
POST /organizations) to get its own isolated one. The default
organization itself is seeded once, in the Alembic migration that added
the organizations table (migrations/versions/*_add_organizations_table*),
not created lazily here — a migration is the right place for a one-time
data seed a fresh dev clone can rely on existing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.user import User

DEFAULT_ORG_SLUG = "default"


class SlugAlreadyExists(Exception):
    pass


class OrganizationNotFound(Exception):
    pass


class EmailAlreadyExists(Exception):
    pass


def get_org_by_slug(slug: str) -> Organization | None:
    with get_session() as session:
        org = session.execute(
            select(Organization).where(Organization.slug == slug)
        ).scalar_one_or_none()
        if org is not None:
            session.expunge(org)
        return org


def create_organization(
    name: str, slug: str, admin_email: str, admin_password: str
) -> Organization:
    """The self-service onboarding flow: one call creates a brand-new,
    isolated organization AND its first org_admin account — no existing
    platform admin needs to be in the loop, which is the actual point
    (this is what lets a SECOND organization onboard at all)."""
    with get_session() as session:
        existing_user = session.execute(
            select(User).where(User.email == admin_email)
        ).scalar_one_or_none()
        if existing_user is not None:
            raise EmailAlreadyExists(f"an account with email {admin_email!r} already exists")

        org = Organization(name=name, slug=slug)
        session.add(org)
        try:
            session.flush()
        except IntegrityError as err:
            session.rollback()
            raise SlugAlreadyExists(f"organization slug {slug!r} is already taken") from err

        admin = User(
            email=admin_email,
            hashed_password=hash_password(admin_password),
            role="org_admin",
            org_id=org.id,
        )
        session.add(admin)
        try:
            session.commit()
        except IntegrityError as err:
            # TOCTOU: the email-existence check above and this commit
            # aren't atomic — same race app/api/auth.py's register()
            # already documents and handles the same way.
            session.rollback()
            raise EmailAlreadyExists(
                f"an account with email {admin_email!r} already exists"
            ) from err
        session.refresh(org)
        session.expunge(org)
        return org
