# Phase 9b deep-dive: internationalization (English + Spanish)

Second epic of the scale-up roadmap's Phase 05 (Reach & Polish). The
roadmap's own framing for this epic is the reason it's structured the way
it is: "An i18n framework and two fully translated languages — including a
translated knowledge base, not just UI strings, since a mistranslated
symptom description is a safety issue here, not a cosmetic one."

That sentence is taken literally here. This is not a UI-strings-only
translation pass — the deterministic intake extractor, the safety
engine's guidance text, and a safety-prioritized slice of the knowledge
base are all language-aware, because those are the parts that actually
determine whether a Spanish-speaking patient gets correct triage.

## The safety-critical half: symptom recognition, not just display text

`app/intake/symptom_phrases.py` was restructured from flat English-only
dictionaries into `PHRASES_BY_LANGUAGE = {"en": {...}, "es": {...}}`,
covering symptom phrases, severity/onset phrases, context phrases, and
per-language negation cue words. The English content is unchanged
(byte-for-byte the same phrase lists, just moved under `"en"`) — the old
top-level `SYMPTOM_PHRASES`/`SEVERITY_PHRASES`/`ONSET_PHRASES`/
`CONTEXT_PHRASES` names are kept as aliases pointing at the English
dicts, so every pre-existing caller and test kept working with zero
changes.

`app/intake/extractor.py`'s `extract_symptom_input()` gained an optional
`language: str = "en"` parameter, threaded through every internal
`_match_*` helper. An unrecognized language code falls back to English
rather than raising — verified with `test_intake_understands... falls
back to english` — since a language field is caller-supplied input, not
something the safety-critical extraction path should ever crash on.

`test_every_rule_symptom_id_has_spanish_phrases` (the Spanish analogue of
the pre-existing English test with the same name) enforces that every
`symptom_id` referenced by `rules.yaml` has a Spanish phrase entry too —
same reasoning as the original: a missing entry means a Spanish patient
describing that exact symptom would silently never trigger the rule.

**Negation is language-specific, not just the cue words.** Spanish
negation structure differs from English ("no tengo dolor" vs "I don't
have pain") but the underlying heuristic — a negation cue word within ~30
characters before the matched phrase, not crossing a clause boundary —
generalizes fine across both, so only the cue-word list itself
(`no`, `sin`, `nunca`, `niego`, `ya no`) needed to be Spanish-specific,
not the algorithm. Verified with a real negated-symptom test case in
Spanish (`test_negated_symptom_is_not_matched`).

## The other half of "not cosmetic": the emergency guidance text itself

Live-verifying the first working version of this epic surfaced a real
gap, not a hypothetical one: a Spanish patient describing textbook
emergency chest-pain symptoms got correctly recognized (`chest_pain`,
`sweating`, `severe`, `sudden`) and correctly routed to the `emergency`
tier — but the **guidance text itself** ("Call emergency services now")
was still in English, because it comes verbatim from `rules.yaml`, which
the deterministic safety engine (`app/safety/engine.py`) has always
returned as-is, with no language awareness at all.

That is precisely the "not cosmetic" gap the roadmap warned about, just
one layer deeper than symptom recognition — a Spanish-speaking patient
in an actual emergency reading English "call 911 now" text is not
meaningfully better off than one whose symptoms weren't recognized at
all. Fixed by adding `app/safety/guidance_translations.py`: a Spanish
translation for all 18 `rules.yaml` guidance strings (all tiers,
emergency through self-care), keyed by `matched_rule_id`, applied as an
overlay in `app/api/triage.py`'s new `_localize_guidance()` — called for
both `/triage/intake` and `/triage/evaluate`.

This is deliberately an overlay, not a second rules file:
`rules.yaml` stays the single, English-authored, clinically-reviewable
source of truth for rule *logic* (match conditions, tiers,
`requires_human_review`); only the *guidance text* has a translation
layer on top. `test_every_rule_has_a_spanish_guidance_translation`
enforces the same "no silent gap" discipline as the phrase-coverage
test — a rule with no Spanish entry falls back to English rather than
erroring (a documented degradation, not a crash, since the alternative
during a possible emergency is worse), but the test makes sure that
fallback is never accidental for an existing rule.

## Knowledge base: a safety-prioritized subset, not all 17 articles

Translating the full knowledge base with real clinical review quality
was out of scope for this epic's time budget. Instead, 11 of the 17
articles were translated into Spanish — chosen for tier severity, not
convenience: **all 9 emergency-tier articles** (chest_pain,
stroke_warning_signs, allergic_reaction, cardiac_warning_signs,
severe_breathing_signs, severe_bleeding, suicidal_thoughts_self_harm,
head_injury, loss_of_consciousness_fainting) plus 2 of the most common
self-care articles (common_cold_cough, fever_general).

Each translated article is a **separate file** (`chest_pain_es.json`,
not a `language` key inside `chest_pain.json`) with its own `id`
(`chest_pain_es`) and a `"language": "es"` field. `app/rag/
knowledge_base.py`'s `load_chunks()` gained an optional `language` filter
(`None` = load everything, unfiltered — the pre-i18n default, used by
existing callers/tests unchanged); `Chunk` gained a `language` field
defaulting to `"en"` so the six original pre-provenance articles (which
predate the `language` key entirely) still load correctly.

`app/rag/retriever.py`'s `get_default_retriever()` gained a `language`
parameter and switched its cache from `@lru_cache(maxsize=1)` to a plain
`@cache` (unbounded) — `functools.cache` already keys on all arguments,
so this gives each language its own singleton index for free, with no
new caching logic.

**A real retrieval-quality bug found and fixed along the way:**
`TfidfVectorizer(stop_words="english")` does nothing for Spanish text —
scikit-learn only ships an "english" stopword list. Without a fix, short
high-frequency Spanish function words (de, la, el, en, que...) inflated
the score of any article that happened to repeat them, and a query for
"dolor en el pecho" ranked `cardiac_warning_signs_es` above
`chest_pain_es` — the wrong top citation for a query about chest pain
specifically. Fixed with a compact hand-rolled Spanish stopword list
(`_SPANISH_STOP_WORDS` in `retriever.py`) applied only when
`language="es"`. Verified live: the corrected retriever now ranks
`chest_pain_es` first for a chest-pain-specific query.

The RAG pipeline (`app/rag/pipeline.py`) also gained a `language`
parameter: the `_NO_CONTEXT_FALLBACK` message is now a per-language dict,
and `app/rag/llm_client.py`'s `build_grounded_prompt()` appends an
explicit "Write your entire response in Spanish" instruction to the LLM
prompt when `language != "en"` — unverified in this sandbox like every
other real-`ANTHROPIC_API_KEY` code path here, since no real key is
configured.

## Conversation flow: follow-up questions ask in the patient's language

`app/intake/conversation.py`'s `build_symptom_from_turns()` and
`next_follow_up_question()` both gained a `language` parameter.
Follow-up question text (the three prompts: "I wasn't able to identify a
specific symptom...", "How severe...", "When did this start...") has a
Spanish translation in `_FOLLOW_UP_TEXT`, so a Spanish-speaking patient
who gives an ambiguous first message is asked the clarifying question in
Spanish too — verified live in the browser (see below).

`app/api/triage.py`'s `IntakeRequest` gained a `language: str = "en"`
field; an unsupported value falls back to English (same pattern as the
extractor). `/triage/evaluate` (which takes pre-structured `SymptomInput`
with no free text) gained `language` as a **query parameter** instead —
there's no patient text for a language to describe there, so it only
affects which guidance/explanation language is returned, not extraction.

## Frontend: patient-facing surface only, honestly scoped

`frontend/lib/i18n.ts` is a flat `en`/`es` translation dictionary plus
`getLanguage()`/`setLanguage()` backed by `localStorage` (same pattern as
`lib/auth.ts`), broadcasting a `"languagechange"` window event so every
mounted component reacts together. `frontend/lib/useLanguage.ts` is the
small hook components use to read the current language and translate
strings.

**Translated**: the triage chat (empty-state hint, input placeholder,
send button, tier badges, "Understood/severity/onset" labels, sources
label, human-review note, emergency callout, network-error message), the
navbar (nav links, "signed in as"/"Log out"/"Log in", plus the new
language `<select>` itself), and the core login-form field labels
(Email/Password/Log in/Register).

**Not translated** (deliberately, and out of this epic's stated scope —
see the roadmap's own framing of *why* this epic exists): the provider
audit page, the analytics dashboard, and the admin user-management page.
Those are internal tools for clinical/operations staff, not the
patient-facing safety path the "mistranslated symptom description is a
safety issue" framing is actually about. The login page's
registration-flow admin-bootstrap disclaimer text is also still
English-only.

`frontend/lib/api.ts`'s `submitIntakeText()` gained a `language` option,
threaded from `TriageChat.tsx`'s `useLanguage()` hook into every
`/triage/intake` call.

## Live verification

Ran the full stack for real (not just unit tests) and drove it through
the actual browser:

1. Switched the navbar language selector to Español — every translated
   string on the page changed immediately (nav links, empty-state hint,
   input placeholder, send button), confirmed via `read_page` and a
   screenshot.
2. Submitted `"de repente tengo dolor en el pecho, es severo, y estoy
   sudando"` (Spanish for the same emergency chest-pain phrasing used in
   the English test suite) through the real chat UI. Got back, correctly:
   `chest_pain` + `sweating` recognized, `severity: severe`,
   `onset: sudden`, tier badge "Emergencia — llama al 911 ahora", the red
   emergency callout in Spanish, and — after the guidance-translation fix
   above — the actual guidance text in Spanish ("Esta combinación de
   síntomas puede indicar un infarto. Llama a los servicios de emergencia
   (911 o el equivalente local) ahora. No conduzcas tú mismo.").
3. Submitted `"tengo un poco de tos y dolor de garganta"` (mild cough +
   sore throat) — got a Spanish follow-up question ("¿Cuándo comenzó
   esto...") for missing onset, answered it, and got a `routine`-tier
   Spanish explanation citing `"Resfriado Común, Tos y Dolor de
   Garganta"` — the Spanish KB article, retrieved and quoted correctly,
   not a fallback to the English one.
4. Switched back to English and confirmed the navbar and page text
   reverted correctly with no lingering Spanish state.
5. Console showed the same benign Next.js dev-mode `ReactDevOverlay`/
   `scheduler.development.js` artifact already investigated and
   confirmed harmless in docs/phase9a-responsive-and-pwa.md (a dev-only
   Fast Refresh glitch, not a functional regression) — the actual page
   content and interactions worked correctly throughout, confirmed via
   `read_page`/`get_page_text` alongside the console check rather than
   trusting the console alone.

## What's still open

- **Age-phrase extraction is not localized.** `extractor.py`'s
  `_extract_age_years()` still only recognizes English "N year(s) old" /
  "N month(s) old" phrasing via regex — a Spanish patient stating their
  age as "tengo 5 años" or a baby's age as "3 meses" will not have that
  age extracted, which matters specifically for the `infant_high_fever`
  rule's age-gated condition. This is a real, known gap, not a silent
  one.
- **Knowledge base translation is partial by design**: 11 of 17 articles
  (all emergency-tier articles plus 2 common self-care ones). The
  remaining 6 (abdominal_pain, headache_general,
  heavy_vaginal_bleeding_pregnancy, joint_pain, localized_swelling_redness,
  rash) have no Spanish version; a Spanish-language RAG query about those
  topics gets the generic no-context fallback message rather than a
  grounded explanation, same behavior as any query with no relevant
  chunks.
- **Only two languages** (English, Spanish), matching the roadmap's own
  scope ("two fully translated languages"), not an open-ended
  `SUPPORTED_LANGUAGES` list.
- **Provider/admin pages are English-only** (audit, analytics, admin) —
  a deliberate scope decision, not an oversight; see above.
- **Spanish KB translations and Spanish phrase lists are unreviewed
  placeholder content**, same honesty standard already applied to the
  English KB articles' own `source_note` fields — before any real
  deployment serving actual Spanish-speaking patients, both would need
  native-speaker and clinical review, not just a second author's
  translation pass.
- **The LLM prompt's Spanish-response instruction is unverified** in
  this sandbox (no real `ANTHROPIC_API_KEY` configured) — same caveat as
  every other real-LLM-call path in this project.
- **No French/other-language groundwork** beyond the `PHRASES_BY_LANGUAGE`
  / `GUIDANCE_ES`-style structure itself, which would generalize to a
  third language without a redesign, but that's future work, not built
  here.

## Test coverage added

- `tests/test_i18n_intake_service.py` (13 tests) — Spanish phrase
  coverage for every rule symptom_id, Spanish symptom/severity/onset/
  negation/context extraction, unsupported-language fallback, Spanish
  conversation-flow follow-up questions.
- `tests/test_i18n_rag_service.py` (7 tests) — per-language chunk
  loading and filtering, per-language retriever caching, the Spanish
  stopword ranking fix, the per-language no-context fallback and LLM
  prompt instruction.
- `tests/test_i18n_triage_api.py` (8 tests) — end-to-end `/triage/intake`
  and `/triage/evaluate` behavior in Spanish (symptom recognition,
  emergency escalation, RAG-grounded self-care explanation, follow-up
  question language, guidance-text translation coverage across all 18
  rules, unsupported-language and omitted-language fallback to English).

All 404 backend tests pass (376 pre-existing + 28 new), zero regressions;
`ruff check` clean; frontend `tsc --noEmit` and `next build` both clean.
