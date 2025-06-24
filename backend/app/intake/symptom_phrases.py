"""Phrase -> symptom_id mapping for the deterministic text extractor, now
per-language. See docs/phase9b-internationalization.md for why this
exists: the roadmap's own words for this epic are "a mistranslated
symptom description is a safety issue here, not a cosmetic one" — this
is the file that claim is actually about. A translated UI shell with an
English-only extractor would mean a Spanish-speaking patient's real
symptom description silently matches nothing and falls through to the
generic "couldn't confidently match" guidance, even for an emergency.

SUPPORTED_LANGUAGES = ("en", "es") — deliberately just the two the
roadmap named ("two fully translated languages"), not an open-ended set.
Every `symptom_id` referenced anywhere in `app/safety/rules.yaml` must
have an entry in EVERY supported language's SYMPTOM_PHRASES — enforced
for both by `tests/test_intake_extractor.py::test_every_rule_symptom_id_has_phrases`
(parametrized over language) and by `test_i18n_phrase_coverage.py`.

Phrases are plain substrings matched against lowercased, normalized
patient text (see extractor.py) — same deliberately-not-NLP tradeoff as
before, now applied twice. The Spanish phrase list is honestly narrower
than English's already-limited seed list (this is placeholder coverage
for a prototype, not clinically reviewed native-speaker copy — same
"PLACEHOLDER CONTENT" honesty already applied to the knowledge base
articles) — a real deployment supporting Spanish patients would need
native-speaker/clinical review here before handling real patients, same
as English's own KB content already documents needing.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("en", "es")
DEFAULT_LANGUAGE = "en"

_SYMPTOM_PHRASES_EN: dict[str, list[str]] = {
    "chest_pain": [
        "chest pain", "chest hurts", "chest hurt", "pain in my chest",
        "chest feels tight", "tightness in my chest", "chest tightness",
        "chest pressure", "pressure in my chest", "my chest feels heavy",
        "chest discomfort", "discomfort in my chest",
    ],
    "shortness_of_breath": [
        "shortness of breath", "short of breath", "hard to breathe",
        "trouble breathing", "can't catch my breath", "cant catch my breath",
        "out of breath", "breathless",
    ],
    "sweating": [
        "sweating", "sweaty", "breaking out in a sweat", "cold sweat",
    ],
    "pain_radiating_arm_jaw": [
        "pain in my arm", "pain radiating to my arm", "pain in my jaw",
        "arm and jaw pain", "pain going down my arm", "pain spreading to my arm",
        "spreading to my arm", "radiating to my arm", "spreading to my jaw",
    ],
    "nausea": [
        "nausea", "nauseous", "feel sick to my stomach", "feel like throwing up",
    ],
    "facial_drooping": [
        "face is drooping", "facial drooping", "one side of my face is drooping",
        "my face feels droopy", "face drooping", "drooping on one side",
        "drooping on one side of my face", "side of my face won't move",
        "side of my face wont move", "one side of my face won't move right",
    ],
    "arm_weakness_one_sided": [
        "arm weakness", "weak arm", "can't lift my arm", "cant lift my arm",
        "one arm feels weak", "arm went numb", "one side is weak",
    ],
    "slurred_speech": [
        "slurred speech", "slurring my words", "can't speak clearly",
        "words are coming out wrong", "speech is slurred",
    ],
    "sudden_confusion": [
        "sudden confusion", "suddenly confused", "can't think straight",
        "disoriented", "confused all of a sudden", "feel really confused",
        "feel so confused", "feeling confused",
    ],
    "sudden_vision_loss": [
        "lost vision", "can't see", "sudden vision loss", "vision went dark",
        "vision blacked out",
    ],
    "throat_swelling": [
        "throat is swelling", "throat swelling", "my throat feels like it's closing",
        "tongue is swelling", "throat closing up", "throat feels tight",
    ],
    "difficulty_breathing_severe": [
        "can't breathe", "cant breathe", "struggling to breathe",
        "gasping for air", "severe difficulty breathing",
    ],
    "widespread_hives_with_swelling": [
        "hives all over", "covered in hives", "hives and swelling",
        "widespread hives",
    ],
    "cant_speak_full_sentences": [
        "can't speak in full sentences", "can only say a few words",
        "too breathless to talk",
    ],
    "blue_lips_or_face": [
        "lips are blue", "turning blue", "blue lips", "face looks blue",
    ],
    "uncontrolled_bleeding": [
        "won't stop bleeding", "wont stop bleeding", "bleeding heavily",
        "can't stop the bleeding", "uncontrolled bleeding",
    ],
    "coughing_up_large_blood": [
        "coughing up blood", "coughing blood", "coughing up a lot of blood",
        "coughing up so much blood", "coughing up quite a bit of blood",
    ],
    "vomiting_large_blood": [
        "vomiting blood", "throwing up blood",
    ],
    "suicidal_thoughts": [
        "thinking about suicide", "want to kill myself", "suicidal",
        "don't want to be alive", "thoughts of ending my life", "want to die",
    ],
    "self_harm_intent": [
        "want to hurt myself", "thinking about hurting myself", "self harm",
        "self-harm",
    ],
    "heavy_vaginal_bleeding": [
        "heavy vaginal bleeding", "bleeding a lot", "heavy bleeding",
        "soaking through a pad an hour",
    ],
    "severe_abdominal_pain": [
        "severe stomach pain", "severe abdominal pain", "excruciating stomach pain",
        "my stomach hurts really badly", "sharp pain in my stomach", "belly pain is severe",
        "excruciating pain in my abdomen", "unbearable pain in my abdomen",
    ],
    "fever": [
        "fever", "temperature", "running a temperature", "feels hot", "feverish",
        "feels warm", "feels warm to the touch",
    ],
    "head_injury": [
        "hit my head", "head injury", "fell and hit my head", "banged my head",
    ],
    "loss_of_consciousness": [
        "passed out", "lost consciousness", "blacked out", "fainted",
    ],
    "repeated_vomiting": [
        "vomiting repeatedly", "keep throwing up", "vomiting over and over",
        "can't stop throwing up", "can't stop puking", "puking over and over",
    ],
    "localized_swelling_redness": [
        "red and swollen", "swelling and redness", "localized swelling",
    ],
    "cough": ["cough", "coughing"],
    "sore_throat": ["sore throat", "throat hurts", "scratchy throat"],
    "headache": ["mild headache", "slight headache", "headache"],
    "joint_pain": ["joint pain", "my joints hurt", "achy joints"],
    "rash": ["rash", "skin rash", "broke out in a rash"],
    "runny_nose": ["runny nose", "stuffy nose", "nose is running"],
    "mild_fatigue": ["tired", "fatigued", "fatigue", "low energy", "feeling run down"],
}

_SEVERITY_PHRASES_EN: dict[str, list[str]] = {
    "severe": [
        "severe", "excruciating", "unbearable", "really bad", "the worst", "extreme",
        "worst one i've ever had", "worst i've ever had", "worst headache of my life",
        "worst headache i've ever had", "worst pain of my life",
    ],
    "moderate": ["moderate", "noticeable", "uncomfortable"],
    "mild": ["mild", "slight", "a little", "minor"],
}

_ONSET_PHRASES_EN: dict[str, list[str]] = {
    "sudden": ["suddenly", "all of a sudden", "just started", "out of nowhere", "abruptly"],
    "recent": ["since yesterday", "started today", "past day", "last night", "couple of days"],
    "gradual": ["gradually", "slowly getting worse", "over the past week", "for a few days"],
    "chronic": ["for weeks", "for months", "chronic", "ongoing for a while"],
}

_CONTEXT_PHRASES_EN = {
    "is_pregnant": ["pregnant", "i'm pregnant", "im pregnant", "weeks pregnant"],
    "is_immunocompromised": [
        "immunocompromised", "on chemo", "on chemotherapy", "weakened immune system",
        "immune system is compromised", "on immunosuppressants",
    ],
    "has_cardiac_history": [
        "history of heart disease", "heart condition", "had a heart attack before",
        "history of heart attacks",
    ],
    "has_respiratory_history": [
        "history of asthma", "have asthma", "copd", "history of lung disease",
    ],
}

_NEGATION_CUES_EN = (
    r"\bno\b", r"\bnot\b", r"\bdenies\b", r"\bdenying\b",
    r"\bdon'?t have\b", r"\bdoesn'?t have\b", r"\bwithout\b",
    r"\bno longer\b", r"\bnever had\b",
)

# --- Spanish — placeholder coverage, not clinically reviewed. See this
# module's docstring. ---

_SYMPTOM_PHRASES_ES: dict[str, list[str]] = {
    "chest_pain": [
        "dolor en el pecho", "me duele el pecho", "dolor de pecho",
        "presión en el pecho", "pecho apretado", "siento el pecho apretado",
        "opresión en el pecho",
    ],
    "shortness_of_breath": [
        "falta de aire", "me falta el aire", "dificultad para respirar",
        "no puedo respirar bien", "sin aliento",
    ],
    "sweating": ["sudando", "sudoración", "sudor frío", "empapado en sudor"],
    "pain_radiating_arm_jaw": [
        "dolor en el brazo", "dolor que se extiende al brazo", "dolor en la mandíbula",
        "dolor en el brazo y la mandíbula", "dolor que baja por el brazo",
    ],
    "nausea": ["náuseas", "con náuseas", "ganas de vomitar", "el estómago revuelto"],
    "facial_drooping": [
        "se me cae la cara", "un lado de la cara caído",
        "la cara se me está cayendo de un lado", "cara caída",
    ],
    "arm_weakness_one_sided": [
        "debilidad en el brazo", "brazo débil", "no puedo levantar el brazo",
        "un brazo se siente débil", "un lado débil",
    ],
    "slurred_speech": [
        "hablo arrastrado", "se me traba la lengua", "no puedo hablar claro",
        "habla arrastrada",
    ],
    "sudden_confusion": [
        "confusión repentina", "de repente confundido", "no puedo pensar con claridad",
        "desorientado", "me siento muy confundido",
    ],
    "sudden_vision_loss": [
        "perdí la visión", "no puedo ver", "pérdida repentina de visión",
        "se me oscureció la vista",
    ],
    "throat_swelling": [
        "se me está hinchando la garganta", "hinchazón en la garganta",
        "siento que la garganta se cierra", "se me hincha la lengua",
    ],
    "difficulty_breathing_severe": [
        "no puedo respirar", "luchando por respirar", "jadeando por aire",
        "dificultad severa para respirar",
    ],
    "widespread_hives_with_swelling": [
        "ronchas por todo el cuerpo", "cubierto de ronchas", "ronchas e hinchazón",
    ],
    "cant_speak_full_sentences": [
        "no puedo hablar en oraciones completas", "solo puedo decir pocas palabras",
        "demasiado sin aliento para hablar",
    ],
    "blue_lips_or_face": [
        "labios morados", "me estoy poniendo morado", "labios azules", "cara morada",
    ],
    "uncontrolled_bleeding": [
        "no deja de sangrar", "sangrado abundante", "no puedo detener el sangrado",
        "sangrado incontrolable",
    ],
    "coughing_up_large_blood": ["toser sangre", "tosiendo sangre"],
    "vomiting_large_blood": ["vomitando sangre", "vómito con sangre"],
    "suicidal_thoughts": [
        "pensando en el suicidio", "quiero quitarme la vida", "suicida",
        "no quiero seguir viviendo", "quiero morir",
    ],
    "self_harm_intent": [
        "quiero hacerme daño", "pensando en lastimarme", "autolesión",
    ],
    "heavy_vaginal_bleeding": [
        "sangrado vaginal abundante", "sangrando mucho", "sangrado abundante",
    ],
    "severe_abdominal_pain": [
        "dolor de estómago severo", "dolor abdominal severo",
        "dolor de estómago insoportable", "me duele muchísimo el estómago",
        "dolor agudo en el estómago",
    ],
    "fever": ["fiebre", "temperatura", "tengo temperatura", "me siento afiebrado"],
    "head_injury": [
        "me golpeé la cabeza", "lesión en la cabeza", "me caí y me golpeé la cabeza",
    ],
    "loss_of_consciousness": [
        "perdí el conocimiento", "me desmayé", "quedé inconsciente",
    ],
    "repeated_vomiting": [
        "vomitando repetidamente", "no dejo de vomitar", "vomitando una y otra vez",
    ],
    "localized_swelling_redness": [
        "rojo e hinchado", "hinchazón y enrojecimiento", "hinchazón localizada",
    ],
    "cough": ["tos", "tosiendo"],
    "sore_throat": ["dolor de garganta", "me duele la garganta", "garganta irritada"],
    "headache": ["dolor de cabeza leve", "un poco de dolor de cabeza", "dolor de cabeza"],
    "joint_pain": ["dolor en las articulaciones", "me duelen las articulaciones"],
    "rash": ["sarpullido", "erupción en la piel", "me salió un sarpullido"],
    "runny_nose": ["nariz que moquea", "nariz congestionada", "me moquea la nariz"],
    "mild_fatigue": ["cansado", "fatigado", "poca energía", "me siento agotado"],
}

_SEVERITY_PHRASES_ES: dict[str, list[str]] = {
    "severe": ["severo", "insoportable", "muy fuerte", "extremo", "terrible"],
    "moderate": ["moderado", "notable", "incómodo"],
    "mild": ["leve", "un poco", "ligero"],
}

_ONSET_PHRASES_ES: dict[str, list[str]] = {
    "sudden": ["de repente", "de pronto", "sin previo aviso", "repentinamente"],
    "recent": ["desde ayer", "empezó hoy", "el día pasado", "anoche", "hace un par de días"],
    "gradual": [
        "gradualmente", "empeorando lentamente", "durante la última semana",
        "desde hace unos días",
    ],
    "chronic": ["desde hace semanas", "desde hace meses", "crónico", "continuo desde hace tiempo"],
}

_CONTEXT_PHRASES_ES = {
    "is_pregnant": ["embarazada", "estoy embarazada", "semanas de embarazo"],
    "is_immunocompromised": [
        "inmunocomprometido", "en quimioterapia", "sistema inmune debilitado",
        "tomando inmunosupresores",
    ],
    "has_cardiac_history": [
        "historial de enfermedad cardíaca", "problema del corazón",
        "tuve un infarto antes",
    ],
    "has_respiratory_history": [
        "historial de asma", "tengo asma", "epoc", "historial de enfermedad pulmonar",
    ],
}

# Spanish negation is simpler in structure than English's (mostly a bare
# "no" directly before the verb) but that same simplicity means "no" is
# an extremely common word — the existing window/clause-boundary heuristic
# (see extractor.py's _is_negated) is unchanged and applies identically
# per language; only the cue word LIST is language-specific.
_NEGATION_CUES_ES = (
    r"\bno\b", r"\bsin\b", r"\bnunca\b", r"\bniego\b", r"\bya no\b",
)

PHRASES_BY_LANGUAGE: dict[str, dict] = {
    "en": {
        "symptom": _SYMPTOM_PHRASES_EN,
        "severity": _SEVERITY_PHRASES_EN,
        "onset": _ONSET_PHRASES_EN,
        "context": _CONTEXT_PHRASES_EN,
        "negation_cues": _NEGATION_CUES_EN,
    },
    "es": {
        "symptom": _SYMPTOM_PHRASES_ES,
        "severity": _SEVERITY_PHRASES_ES,
        "onset": _ONSET_PHRASES_ES,
        "context": _CONTEXT_PHRASES_ES,
        "negation_cues": _NEGATION_CUES_ES,
    },
}

# Backward-compatible top-level names — every existing caller that
# imported these directly (matching English-only, pre-i18n behavior)
# keeps working unchanged; new language-aware code goes through
# PHRASES_BY_LANGUAGE / extractor.py's `language` parameter instead.
SYMPTOM_PHRASES = _SYMPTOM_PHRASES_EN
SEVERITY_PHRASES = _SEVERITY_PHRASES_EN
ONSET_PHRASES = _ONSET_PHRASES_EN
CONTEXT_PHRASES = _CONTEXT_PHRASES_EN
