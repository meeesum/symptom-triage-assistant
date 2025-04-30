"""Triage API endpoints.

Request flow (this ordering is the whole point of the architecture):

  raw text (optional, possibly multiple turns)
      -> build_symptom_from_turns()        [deterministic keyword extraction + merge]
  SymptomInput
      -> RedFlagEngine.evaluate()          [deterministic, no LLM]
      -> if tier in {emergency, urgent}: finalize immediately, skip RAG,
         and skip any follow-up question — see app/intake/conversation.py
      -> emergency tier additionally triggers a high-risk alert, decoupled
         onto a job queue — see app/services/alerting.py
      -> else, if the caller opted into allow_follow_up and confidence is
         low: return a follow-up question instead of a decision
      -> else: generate_explanation() adds grounded context on top
      -> log the full decision (audit trail) regardless of path taken

Two entry points share the same finalization logic (`_finalize_triage`):
  - POST /triage/evaluate  — caller already has structured SymptomInput,
    single-shot, no conversation/follow-up concept
  - POST /triage/intake    — caller has raw patient text (chat UI path),
    optionally multi-turn via prior_turns + allow_follow_up (see
    app/intake/conversation.py for the merge/confidence logic)

`/triage/intake` works for anyone — no login required, matching the
product's actual shape (anyone can describe symptoms without an account).
But if the caller happens to be a logged-in patient (an optional bearer
token, via get_optional_current_user), the exchange is also saved to their
own chat history (see app/services/chat_history.py) so `/triage/history`
can show it back to them later. Anonymous requests are never persisted
this way — same privacy stance as the audit trail's free-text handling.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_current_user, get_optional_current_user
from app.intake.conversation import build_symptom_from_turns, next_follow_up_question
from app.intake.symptom_phrases import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from app.rag.pipeline import generate_explanation
from app.safety.engine import RedFlagEngine
from app.safety.guidance_translations import GUIDANCE_ES, UNMATCHED_GUIDANCE_ES
from app.safety.schemas import EscalationResult, EscalationTier, SymptomInput
from app.services.alerting import trigger_high_risk_alert
from app.services.audit_log import log_triage_decision
from app.services.chat_history import get_history, save_exchange

router = APIRouter(prefix="/triage", tags=["triage"])

_engine = RedFlagEngine()

_FAST_PATH_TIERS = {EscalationTier.EMERGENCY, EscalationTier.URGENT}


class IntakeRequest(BaseModel):
    text: str = Field(examples=["I have a mild cough and sore throat"])
    prior_turns: list[str] = Field(
        default_factory=list,
        description=(
            "Earlier raw messages in this conversation, oldest first. Omit "
            "or leave empty to start a new conversation."
        ),
    )
    allow_follow_up: bool = Field(
        default=False,
        description=(
            "Opt in to multi-turn triage: when confidence is low (missing "
            "severity/onset, or no symptom recognized) and the tier isn't "
            "emergency/urgent, the response is a follow-up question instead "
            "of a final decision — see app/intake/conversation.py."
        ),
    )
    language: str = Field(
        default=DEFAULT_LANGUAGE,
        description=(
            f"Language the patient's text is in and the response should be "
            f"in. One of {sorted(SUPPORTED_LANGUAGES)}; unsupported values "
            "fall back to English rather than erroring."
        ),
    )


def _localize_guidance(escalation: EscalationResult, language: str) -> EscalationResult:
    """Overlay a Spanish guidance translation on top of the rule engine's
    (always-English) output, keyed by matched_rule_id — see
    app/safety/guidance_translations.py for why this is a translation
    overlay rather than a second rules file. A rule with no translation
    entry (or an unmatched-rule fallback) keeps the English text rather
    than erroring — a missing translation degrading to English is a safe,
    documented gap; anything else risks showing no guidance at all during
    a possible emergency.
    """
    if language != "es":
        return escalation
    if escalation.matched_rule_id is None:
        return escalation.model_copy(update={"guidance": UNMATCHED_GUIDANCE_ES})
    translated = GUIDANCE_ES.get(escalation.matched_rule_id)
    if translated is None:
        return escalation
    return escalation.model_copy(update={"guidance": translated})


async def _finalize_triage(
    symptom: SymptomInput,
    escalation: EscalationResult,
    patient_id: int | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    escalation = _localize_guidance(escalation, language)
    if escalation.tier in _FAST_PATH_TIERS:
        # Safety fast path: do not involve the LLM at all for the
        # highest-risk tiers. What you see is exactly the reviewed,
        # version-controlled guidance text from rules.yaml.
        record_id = log_triage_decision(
            symptom, escalation, source="rule_engine_fast_path", patient_id=patient_id
        )
        if escalation.tier == EscalationTier.EMERGENCY and record_id is not None:
            # Decoupled from this response via a job queue (see
            # app/services/alerting.py) — never allowed to delay or break
            # an emergency-tier reply, same principle as audit logging.
            trigger_high_risk_alert(record_id, message=escalation.guidance)
        return {
            "tier": escalation.tier.value,
            "guidance": escalation.guidance,
            "matched_rule_id": escalation.matched_rule_id,
            "requires_human_review": escalation.requires_human_review,
            "sources": [],
            "audit_record_id": record_id,
        }

    explanation = await generate_explanation(symptom, escalation, language=language)
    record_id = log_triage_decision(
        symptom,
        escalation,
        source=f"rag_pipeline:{explanation.generation_source}",
        patient_id=patient_id,
    )
    return {
        "tier": escalation.tier.value,
        "guidance": explanation.explanation,
        "matched_rule_id": escalation.matched_rule_id,
        "requires_human_review": escalation.requires_human_review,
        "sources": explanation.sources,
        "audit_record_id": record_id,
    }


@router.post("/evaluate")
async def evaluate_symptoms(symptom: SymptomInput, language: str = DEFAULT_LANGUAGE) -> dict:
    # `language` is a query param here (not a SymptomInput field) since
    # this endpoint takes already-extracted structured input — there's no
    # patient free text for a language to describe. It only affects
    # guidance/explanation translation, not evaluation itself.
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    escalation = _engine.evaluate(symptom)
    result = await _finalize_triage(symptom, escalation, language=language)
    result["status"] = "complete"
    return result


@router.post("/intake")
async def intake_from_text(
    request: IntakeRequest,
    current_user: CurrentUser | None = Depends(get_optional_current_user),
) -> dict:
    language = request.language if request.language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    all_turns = [*request.prior_turns, request.text]
    symptom = build_symptom_from_turns(all_turns, language=language)
    escalation = _engine.evaluate(symptom)

    if request.allow_follow_up and escalation.tier not in _FAST_PATH_TIERS:
        follow_up = next_follow_up_question(
            symptom, turns_so_far=len(all_turns), language=language
        )
        if follow_up is not None:
            # Not yet confident enough to triage, and this isn't an
            # emergency/urgent tier — ask instead of guessing. Nothing is
            # logged to the audit trail or chat history for this turn: an
            # incomplete symptom picture is not a triage decision.
            return {
                "status": "need_more_info",
                "follow_up_question": follow_up,
                "understood_symptom_ids": symptom.symptom_ids,
                "understood_severity": symptom.severity.value,
                "understood_onset": symptom.onset.value,
            }

    patient_id = current_user.id if current_user is not None else None
    result = await _finalize_triage(symptom, escalation, patient_id=patient_id, language=language)
    result["status"] = "complete"
    # Surface what was actually understood from the text — critical for a
    # keyword-based extractor: the patient/UI needs to be able to see and
    # correct a missed or wrong match, not just trust it silently.
    result["understood_symptom_ids"] = symptom.symptom_ids
    result["understood_severity"] = symptom.severity.value
    result["understood_onset"] = symptom.onset.value

    if current_user is not None:
        save_exchange(
            user_id=current_user.id,
            symptom=symptom,
            tier=result["tier"],
            guidance=result["guidance"],
            matched_rule_id=result["matched_rule_id"],
            requires_human_review=result["requires_human_review"],
            sources=result["sources"],
        )

    return result


@router.get("/history")
async def triage_history(
    limit: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    exchanges = get_history(current_user.id, limit)
    return [
        {
            "id": e.id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "user_text": e.user_text,
            "tier": e.tier,
            "guidance": e.guidance,
            "matched_rule_id": e.matched_rule_id,
            "requires_human_review": e.requires_human_review,
            "sources": e.sources,
            "understood_symptom_ids": e.understood_symptom_ids,
            "understood_severity": e.understood_severity,
            "understood_onset": e.understood_onset,
        }
        for e in exchanges
    ]
