"""Save/read a logged-in patient's triage chat history."""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import get_session
from app.models.chat_exchange import ChatExchange
from app.safety.schemas import SymptomInput

_HISTORY_LIMIT = 200  # hard cap regardless of what's requested — same pattern as /audit/recent


def save_exchange(
    user_id: int,
    symptom: SymptomInput,
    tier: str,
    guidance: str,
    matched_rule_id: str | None,
    requires_human_review: bool,
    sources: list[str],
) -> None:
    with get_session() as session:
        session.add(
            ChatExchange(
                user_id=user_id,
                user_text=symptom.free_text,
                tier=tier,
                guidance=guidance,
                matched_rule_id=matched_rule_id,
                requires_human_review=requires_human_review,
                sources=sources,
                understood_symptom_ids=symptom.symptom_ids,
                understood_severity=symptom.severity.value,
                understood_onset=symptom.onset.value,
            )
        )
        session.commit()


def get_history(user_id: int, limit: int = 50) -> list[ChatExchange]:
    # Floor AND ceiling — see the code-review finding on /audit/recent's missing floor
    limit = min(max(limit, 1), _HISTORY_LIMIT)
    with get_session() as session:
        rows = session.execute(
            select(ChatExchange)
            .where(ChatExchange.user_id == user_id)
            .order_by(ChatExchange.id.asc())  # ascending: oldest first, matches chat reading order
            .limit(limit)
        ).scalars().all()
        # detach from the session before returning — callers read these
        # after the `with` block closes the session
        for row in rows:
            session.expunge(row)
        return rows
