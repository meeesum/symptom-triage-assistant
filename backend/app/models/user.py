"""User accounts for auth/RBAC.

Four roles: "patient" (default, no special access), "provider" (can view
the audit trail — see app/api/deps.py's require_role), "org_admin" (a
strict superset within their OWN organization only: everything a
provider can do, plus user management and patient-panel assignment
scoped to their org — see app/api/admin.py), "admin" (a platform-wide
superuser, unrestricted by org — the pre-multi-tenancy role, now reserved
for cross-org bootstrap/support use via scripts/create_admin.py rather
than everyday operation). "admin" is not "org_admin with a different
label" and vice versa; routes should default to the narrowest
require_role(...) that fits.

Every user belongs to exactly one Organization (org_id, non-nullable) —
see app/models/organization.py. This is the actual foundation Phase 04's
multi-tenancy epic is built on: tenant isolation is enforced ONCE, where
a provider is assigned a patient (app/services/patient_panel.py rejects
a cross-org assignment outright), rather than re-derived independently at
every read. Every existing panel-scoped view (audit trail, clinical
notes, referrals, analytics, alerts) inherits this for free, since none
of them can ever end up looking at a patient outside the provider's org
in the first place — see docs/phase8a-organizations.md for why this was
chosen over adding an org_id column to every downstream table.
"""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

VALID_ROLES = ("patient", "provider", "org_admin", "admin")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="patient")
    org_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
