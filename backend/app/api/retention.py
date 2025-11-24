"""Manually-triggerable retention purge, for testing/ops visibility —
the realistic trigger for a real deployment is an external cron entry
running scripts/run_retention_purge.py, not this endpoint (see
app/services/retention.py's module docstring for why). Platform
`admin` only, not `org_admin`: retention is a platform-wide data
lifecycle operation, not a per-tenant one — chat history and audit
records age out on the same global clock regardless of which org they
belong to. See docs/phase8d-retention-and-purge-jobs.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_role
from app.models.retention_purge_run import RetentionPurgeRun
from app.services.retention import enqueue_retention_purge, list_purge_runs

router = APIRouter(prefix="/admin/retention", tags=["retention"])


class PurgeRunResponse(BaseModel):
    id: int
    chat_exchanges_deleted: int
    audit_records_deleted: int
    symptom_photos_deleted: int
    admin_action_logs_deleted: int
    ran_at: str | None

    @staticmethod
    def from_model(r: RetentionPurgeRun) -> PurgeRunResponse:
        return PurgeRunResponse(
            id=r.id,
            chat_exchanges_deleted=r.chat_exchanges_deleted,
            audit_records_deleted=r.audit_records_deleted,
            symptom_photos_deleted=r.symptom_photos_deleted,
            admin_action_logs_deleted=r.admin_action_logs_deleted,
            ran_at=r.ran_at.isoformat() if r.ran_at else None,
        )


@router.post("/purge", status_code=202)
async def trigger_purge(_admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    enqueue_retention_purge()
    return {"status": "enqueued"}


@router.get("/runs", response_model=list[PurgeRunResponse])
async def get_purge_runs(
    limit: int = 50, _admin: CurrentUser = Depends(require_role("admin"))
) -> list[PurgeRunResponse]:
    return [PurgeRunResponse.from_model(r) for r in list_purge_runs(limit)]
