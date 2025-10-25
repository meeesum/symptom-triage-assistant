"""Spanish translations of the safety engine's per-rule guidance text.

This is deliberately a translation OVERLAY, not a second rules file:
app/safety/rules.yaml stays the single, English-authored, clinically-
reviewable source of truth for the actual rule LOGIC (match conditions,
tiers, requires_human_review) — only the guidance TEXT shown to the
patient is translated here, keyed by `matched_rule_id`. This is the most
safety-critical text in the internationalization epic: it's what an
emergency-tier patient actually reads (e.g. "call emergency services
now"), so an untranslated fast path would defeat the entire point of
translating symptom recognition in the first place — see
docs/phase9b-internationalization.md.

If a rule's `id` has no entry here (e.g. a new rule added to rules.yaml
without updating this file), the caller falls back to the English
guidance rather than raising — see app/api/triage.py's
`_localized_guidance`. That fallback is a deliberate, documented gap, not
a silent one: a missing translation should degrade to English text, never
to a crash or blank guidance during a possible emergency.
"""

from __future__ import annotations

GUIDANCE_ES: dict[str, str] = {
    "cardiac_event_pattern": (
        "Esta combinación de síntomas puede indicar un infarto. Llama a los "
        "servicios de emergencia (911 o el equivalente local) ahora. No "
        "conduzcas tú mismo."
    ),
    "stroke_fast_pattern": (
        "Estos síntomas pueden indicar un derrame cerebral, donde cada minuto "
        "cuenta. Llama a los servicios de emergencia ahora y anota la hora en "
        "que comenzaron los síntomas."
    ),
    "anaphylaxis_pattern": (
        "Esto podría ser una reacción alérgica grave (anafilaxia). Usa un "
        "autoinyector de epinefrina si tienes uno disponible y llama a los "
        "servicios de emergencia de inmediato."
    ),
    "severe_breathing_difficulty": (
        "La dificultad grave para respirar necesita atención de emergencia "
        "ahora. Llama a los servicios de emergencia."
    ),
    "uncontrolled_bleeding": (
        "El sangrado incontrolable o abundante es una emergencia médica. "
        "Aplica presión directa y firme y llama a los servicios de emergencia "
        "ahora."
    ),
    "suicidal_ideation": (
        "Si estás pensando en hacerte daño, por favor busca ayuda ahora mismo: "
        "llama o envía un mensaje de texto al 988 (Línea de Crisis y "
        "Prevención del Suicidio, EE. UU.) o acude a la sala de emergencias "
        "más cercana. Mereces apoyo, y hay ayuda disponible de inmediato."
    ),
    "pregnancy_severe_bleeding_or_pain": (
        "Esta combinación durante el embarazo necesita evaluación inmediata. "
        "Llama a los servicios de emergencia o acude a la sala de emergencias "
        "más cercana ahora."
    ),
    "infant_high_fever": (
        "La fiebre en un bebé menor de 3 meses siempre necesita evaluación "
        "médica en la misma hora, incluso si el bebé por lo demás parece estar "
        "bien. Contacta a los servicios de emergencia o acude a la sala de "
        "emergencias ahora."
    ),
    "severe_head_injury": (
        "Esta combinación después de una lesión en la cabeza necesita "
        "evaluación de emergencia ahora. Llama a los servicios de emergencia."
    ),
    "unexplained_loss_of_consciousness": (
        "Desmayarse o perder el conocimiento — incluso brevemente — debe "
        "evaluarse como una emergencia, ya que puede ser una señal de un "
        "problema cardíaco, neurológico u otro problema grave. Llama a los "
        "servicios de emergencia ahora."
    ),
    "severe_headache_red_flag": (
        "Un dolor de cabeza severo — especialmente uno repentino, o el peor "
        "que hayas tenido — puede ser señal de una afección grave como un "
        "sangrado en el cerebro. Llama a los servicios de emergencia ahora, o "
        "busca atención inmediata incluso si se desarrolló gradualmente en "
        "lugar de comenzar de repente."
    ),
    "chest_pain_isolated": (
        "El dolor de pecho debe evaluarse rápidamente incluso sin otros "
        "síntomas. Busca atención médica urgente el mismo día. Si empeora o "
        "aparecen nuevos síntomas, llama a los servicios de emergencia."
    ),
    "high_fever_adult": (
        "Una fiebre alta debe evaluarse pronto. Busca atención urgente o el "
        "mismo día, especialmente si persiste más de 48 horas o sientes que "
        "no puedes funcionar."
    ),
    "moderate_breathing_difficulty": (
        "La falta de aire que es nueva o que empeora debe evaluarse con "
        "urgencia. Si se vuelve severa, llama a los servicios de emergencia."
    ),
    "severe_abdominal_pain_general": (
        "El dolor abdominal severo debe evaluarse el mismo día. Busca "
        "atención urgente, o atención de emergencia si el dolor empeora "
        "rápidamente o desarrollas fiebre, vómitos o rigidez."
    ),
    "immunocompromised_infection_signs": (
        "Debido a que tu sistema inmunológico está comprometido, las señales "
        "de infección pueden empeorar rápidamente. Busca evaluación urgente "
        "el mismo día."
    ),
    "persistent_mild_symptoms": (
        "Vale la pena que evalúen estos síntomas. Agenda una visita rutinaria "
        "con tu proveedor de atención primaria en los próximos días."
    ),
    "default_mild_acute": (
        "Estos síntomas generalmente se pueden manejar en casa con descanso, "
        "líquidos y cuidado de venta libre. Vigila si empeoran — si aparecen "
        "nuevos síntomas o estos persisten más de una semana, contacta a tu "
        "proveedor."
    ),
}

# app/safety/engine.py's RedFlagEngine.evaluate() fallback when no rule
# matches at all (see _DEFAULT_UNMATCHED_GUIDANCE there) — has no
# matched_rule_id to key off of, so it's translated separately.
UNMATCHED_GUIDANCE_ES = (
    "No pudimos identificar con confianza tus síntomas dentro de un patrón "
    "de orientación específico. Para estar seguro, comunícate con un "
    "proveedor de salud para hablar sobre tus síntomas, o busca atención "
    "urgente si algo se siente grave o está empeorando rápidamente."
)
