import pytest
from sqlalchemy import select

from app.core.db import get_session
from app.models.user import User
from app.services.organizations import (
    DEFAULT_ORG_SLUG,
    EmailAlreadyExists,
    SlugAlreadyExists,
    create_organization,
    get_org_by_slug,
)


def test_default_org_was_seeded_by_migration():
    org = get_org_by_slug(DEFAULT_ORG_SLUG)
    assert org is not None
    assert org.name == "Default Organization"


def test_get_org_by_slug_returns_none_for_unknown_slug():
    assert get_org_by_slug("no-such-org-slug") is None


def test_create_organization_creates_org_and_first_org_admin():
    org = create_organization(
        name="Acme Clinic",
        slug="acme-clinic-svc-test",
        admin_email="admin@acme-svc-test.example",
        admin_password="correct-horse-battery-staple",
    )
    assert org.slug == "acme-clinic-svc-test"

    with get_session() as session:
        admin = session.execute(
            select(User).where(User.org_id == org.id)
        ).scalar_one_or_none()
        assert admin is not None
        assert admin.role == "org_admin"
        assert admin.email == "admin@acme-svc-test.example"


def test_create_organization_rejects_duplicate_slug():
    create_organization(
        name="First",
        slug="dup-slug-svc-test",
        admin_email="first@dup-svc-test.example",
        admin_password="correct-horse-battery-staple",
    )
    with pytest.raises(SlugAlreadyExists):
        create_organization(
            name="Second",
            slug="dup-slug-svc-test",
            admin_email="second@dup-svc-test.example",
            admin_password="correct-horse-battery-staple",
        )


def test_create_organization_rejects_duplicate_admin_email():
    create_organization(
        name="Org A",
        slug="org-a-svc-test",
        admin_email="shared@dup-email-svc-test.example",
        admin_password="correct-horse-battery-staple",
    )
    with pytest.raises(EmailAlreadyExists):
        create_organization(
            name="Org B",
            slug="org-b-svc-test",
            admin_email="shared@dup-email-svc-test.example",
            admin_password="correct-horse-battery-staple",
        )


def test_new_orgs_are_isolated_from_each_other():
    org1 = create_organization(
        name="Isolated One",
        slug="isolated-one-svc-test",
        admin_email="admin@isolated-one-svc-test.example",
        admin_password="correct-horse-battery-staple",
    )
    org2 = create_organization(
        name="Isolated Two",
        slug="isolated-two-svc-test",
        admin_email="admin@isolated-two-svc-test.example",
        admin_password="correct-horse-battery-staple",
    )
    assert org1.id != org2.id
