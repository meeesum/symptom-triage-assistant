#!/usr/bin/env python
"""One-time bootstrap for the very first admin account.

Since /auth/register only ever creates patients now (role assignment is
admin-controlled — see app/api/auth.py), there has to be some way to get
the *first* admin into the system, because no admin exists yet to promote
anyone via PATCH /admin/users/{id}/role. This script is that escape hatch:
run it directly against the DB, once, by whoever controls the deployment.

Usage (from backend/):
    python scripts/create_admin.py admin@example.com

Prompts for a password interactively (getpass, not argv, so the password
doesn't end up in shell history or process listings). If the email already
exists, promotes that user to admin instead of creating a duplicate.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import get_session  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.organizations import DEFAULT_ORG_SLUG, get_org_by_slug  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/create_admin.py <email>", file=sys.stderr)
        return 1

    email = sys.argv[1]

    with get_session() as session:
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

        if existing is not None:
            existing.role = "admin"
            session.commit()
            print(f"Existing user {email!r} promoted to admin.")
            return 0

        password = getpass.getpass(f"Password for new admin account {email!r}: ")
        if len(password) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            return 1

        # "admin" is platform-wide (see app/models/user.py) — org_id is a
        # required column but not meaningful for authorization on this
        # role, so it's set to the default org rather than left dangling.
        default_org = get_org_by_slug(DEFAULT_ORG_SLUG)
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="admin",
            org_id=default_org.id,
        )
        session.add(user)
        session.commit()
        print(f"Admin account {email!r} created.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
