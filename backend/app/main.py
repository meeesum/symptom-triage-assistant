from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.logging_config import configure_logging

# Configured before anything else imports/logs — including at import time
# of the modules below, not just once the app starts serving requests.
# The imports below are deliberately NOT at the top of the file for that
# reason (noqa: E402 on each — this ordering is intentional, not an
# oversight ruff's default import-position check doesn't know about).
configure_logging()

from app.api.admin import router as admin_router  # noqa: E402
from app.api.alerts import router as alerts_router  # noqa: E402
from app.api.analytics import router as analytics_router  # noqa: E402
from app.api.audit import router as audit_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.clinical_notes import router as clinical_notes_router  # noqa: E402
from app.api.consent import router as consent_router  # noqa: E402
from app.api.data_rights import router as data_rights_router  # noqa: E402
from app.api.kb_review import router as kb_review_router  # noqa: E402
from app.api.notifications import router as notifications_router  # noqa: E402
from app.api.organizations import router as organizations_router  # noqa: E402
from app.api.patient_panel import router as patient_panel_router  # noqa: E402
from app.api.retention import router as retention_router  # noqa: E402
from app.api.referrals import router as referrals_router  # noqa: E402
from app.api.reports import export_router as reports_export_router  # noqa: E402
from app.api.reports import subscription_router as reports_subscription_router  # noqa: E402
from app.api.symptom_photos import router as symptom_photos_router  # noqa: E402
from app.api.triage import router as triage_router  # noqa: E402
from app.core.migrate import run_migrations  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.request_limits import MaxBodySizeMiddleware  # noqa: E402
from app.core.sentry import init_sentry  # noqa: E402

init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev/local convenience only — see app/core/migrate.py's docstring for
    # why a real deployment should run migrations as an explicit step
    # before starting any app instance, not automatically here.
    run_migrations()
    yield


# Tags metadata: every router above is grouped under one of these in the
# generated OpenAPI docs (/docs) — without this, FastAPI still groups by
# tag name, just with no description for what the group actually covers.
_TAGS_METADATA = [
    {
        "name": "triage",
        "description": (
            "Patient-facing symptom triage. Emergency/urgent tiers bypass "
            "the RAG pipeline entirely — see docs/phase2-safety-engine.md."
        ),
    },
    {
        "name": "audit",
        "description": "Provider/admin-only read access to the triage decision audit trail.",
    },
    {
        "name": "auth",
        "description": (
            "Registration, login, logout, and token refresh. Registration "
            "always creates a patient account — see docs/phase4b-auth-rbac.md."
        ),
    },
    {
        "name": "admin",
        "description": "Admin-only user management (list users, change roles).",
    },
    {
        "name": "health",
        "description": (
            "Liveness (`/health`) vs. readiness (`/health/ready`) — see "
            "app/api/health.py for why they're different checks."
        ),
    },
    {
        "name": "kb-review",
        "description": (
            "Provider/admin-only clinical review queue for knowledge-base "
            "articles — submit a draft, approve or reject it. See "
            "docs/phase6e-clinical-review-workflow.md."
        ),
    },
    {
        "name": "panel",
        "description": (
            "Admin-controlled provider-patient panel assignment. Scopes "
            "GET /audit/recent for the provider role — see "
            "docs/phase7a-patient-panels.md."
        ),
    },
    {
        "name": "clinical-notes",
        "description": (
            "Provider/admin annotations on a triage audit record. Same "
            "panel-based visibility as GET /audit/recent — see "
            "docs/phase7b-clinical-notes.md."
        ),
    },
    {
        "name": "referrals",
        "description": (
            "Referral & appointment status tracking (referred -> "
            "scheduled -> seen) for a triage audit record. Same "
            "panel-based visibility as clinical notes — see "
            "docs/phase7c-referral-tracking.md."
        ),
    },
    {
        "name": "analytics",
        "description": (
            "Provider analytics: triage volume, tier distribution, and "
            "time-to-follow-up trends, scoped to the same panel-based "
            "visibility as GET /audit/recent — see "
            "docs/phase7d-provider-analytics.md."
        ),
    },
    {
        "name": "alerts",
        "description": (
            "Read-only oversight of high-risk (emergency-tier) alerts, "
            "paged asynchronously via a job queue — see "
            "docs/phase7e-high-risk-alerting.md."
        ),
    },
    {
        "name": "notifications",
        "description": (
            "Self-service email/SMS notification preferences — the "
            "current user manages their own. See "
            "docs/phase7f-notifications.md."
        ),
    },
    {
        "name": "organizations",
        "description": (
            "Self-service organization (tenant) signup — creates a new "
            "isolated org and its first org_admin account. See "
            "docs/phase8a-organizations.md."
        ),
    },
    {
        "name": "consent",
        "description": (
            "Self-service consent tracking. See "
            "docs/phase8b-consent-and-data-rights.md."
        ),
    },
    {
        "name": "data-rights",
        "description": (
            "Self-service GDPR/HIPAA-style data export and deletion "
            "(anonymization) requests. See "
            "docs/phase8b-consent-and-data-rights.md."
        ),
    },
    {
        "name": "retention",
        "description": (
            "Configurable retention windows + purge jobs for chat "
            "history and audit records. See "
            "docs/phase8d-retention-and-purge-jobs.md."
        ),
    },
]

app = FastAPI(
    title="Symptom Triage Assistant API",
    description=(
        "Informational symptom-triage service. NOT a diagnostic tool — "
        "always directs users to appropriate professional care.\n\n"
        "No API version prefix (`/v1/...`) yet — see "
        "docs/phase5d-api-hardening.md for why, and the trigger conditions "
        "for adding one."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=_TAGS_METADATA,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(MaxBodySizeMiddleware)

# Dev-only: local Next.js dev server origin. Tighten to a real allowlist
# (and drop wildcard methods/headers) before any non-local deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["POST", "GET", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(triage_router)
app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(health_router)
app.include_router(kb_review_router)
app.include_router(patient_panel_router)
app.include_router(clinical_notes_router)
app.include_router(referrals_router)
app.include_router(analytics_router)
app.include_router(alerts_router)
app.include_router(notifications_router)
app.include_router(organizations_router)
app.include_router(consent_router)
app.include_router(data_rights_router)
app.include_router(retention_router)
app.include_router(symptom_photos_router)
app.include_router(reports_export_router)
app.include_router(reports_subscription_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
