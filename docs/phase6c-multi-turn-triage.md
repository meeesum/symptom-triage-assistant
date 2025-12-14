# Phase 6c deep-dive: multi-turn triage

Third epic of the scale-up roadmap's Phase 02 (Clinical Depth), following
`docs/phase6a-dense-retrieval.md` and `docs/phase6b-knowledge-base-expansion.md`.

## What's built

- `app/intake/conversation.py` — turns a SEQUENCE of raw messages into one
  merged `SymptomInput`, and decides whether the merge is confident
  enough to triage or whether a targeted follow-up question would help
  first. Each turn is extracted independently via the existing
  `extract_symptom_input()` (from `app/intake/extractor.py`, unchanged)
  and merged afterward — not concatenated into one blob before
  extraction, which would let the negation heuristic's clause-boundary
  logic bleed across what were really separate messages.
  `next_follow_up_question()` asks, in order: what symptom (if none
  recognized), how severe (if unknown), when it started (if unknown) —
  and gives up after `MAX_FOLLOW_UPS` (2) rounds, finalizing on whatever
  is understood rather than asking indefinitely.
- `POST /triage/intake` gained two new, both-optional request fields:
  `prior_turns` (earlier raw messages, oldest first) and
  `allow_follow_up` (defaults `False`). Response gained a `status` field:
  `"complete"` (a real triage decision, same shape as before) or
  `"need_more_info"` (a `follow_up_question` instead).
- `TriageChat.tsx` (frontend) now holds a `conversationTurns` array of
  raw messages sent so far in the current, not-yet-finalized
  conversation. A `"need_more_info"` response renders the question as a
  distinct dashed-border bubble and keeps the conversation open (input
  placeholder changes to "Answer the question above…"); a `"complete"`
  response resets `conversationTurns` so the next message starts fresh.

## Safety-critical: opt-in, and emergency/urgent always wins

Two design decisions here are not incidental — they're the actual point:

1. **`allow_follow_up` defaults to `False`.** Every existing caller of
   `/triage/intake` — including whatever integrations exist beyond this
   repo's own frontend — keeps getting exactly the single-shot,
   immediate-decision behavior it always has. Multi-turn is additive, not
   a breaking change to the endpoint's default contract. Verified
   directly: the full pre-existing test suite (159 tests before this
   epic) passed unchanged after this was wired in, with zero test edits
   needed for the default path.
2. **A follow-up question is only ever offered AFTER the safety engine
   has evaluated the merged symptom and found it NOT emergency/urgent.**
   `app/api/triage.py` checks `escalation.tier not in _FAST_PATH_TIERS`
   before even calling `next_follow_up_question()`. A patient describing
   an emergency is never made to answer more questions before getting
   emergency guidance — verified live: `"sudden chest pain and
   sweating"` with `allow_follow_up: true` still finalizes immediately
   as `emergency`, and the same is verified through the actual browser
   UI, not just curl (see below).

## Live verification, not just tests

Ran the real dev server (backend + `npm run dev` frontend) and drove the
actual chat UI in a browser:

1. Typed "I have a cough" — the assistant asked "How severe would you
   say this is — mild, moderate, or severe?" in a distinct bubble, input
   placeholder switched to "Answer the question above…".
2. Typed "its mild and started gradually" — got a final `routine` tier
   decision with `understood: cough · severity: mild · onset: gradual`
   and correctly cited the cough article, input reset to
   "Describe your symptoms…" for a new conversation.
3. Typed "sudden chest pain and sweating" — got an immediate `emergency`
   decision with the 911 callout, no follow-up question, confirming the
   fast-path-always-wins guarantee end-to-end through the real UI, not
   just the API layer.

## A real bug this surfaced and fixed: retrieval noise from the KB expansion epic

Live-testing turn 2 above (`"its mild and started gradually"` merged with
`"I have a cough"`) initially returned an explanation mixing in text from
the **heavy vaginal bleeding during pregnancy** and **joint pain**
articles — added in the immediately-preceding knowledge-base-expansion
epic — purely because they share generic vocabulary ("mild",
"gradually") with the query. Confirmed with the retriever directly:
`common_cold_cough` scored 0.382, but `joint_pain` (0.158) and
`heavy_vaginal_bleeding_pregnancy` (0.127) both cleared the retriever's
existing absolute `min_score=0.05` floor despite being far weaker matches
— TF-IDF has no concept of "far weaker relative to the best match," only
"above an absolute floor."

Fixed in `app/rag/pipeline.py` with `_filter_to_relevant()`: a retrieved
chunk must score at least half (`_RELEVANCE_RATIO = 0.5`) of the top
chunk's score to be used for citation or generation — a relative cutoff
layered on top of the retriever's existing absolute one, not a
replacement for it. Applied once, upstream of both the extractive
fallback and the real-LLM path, so both the sources list and the
generated text benefit. Verified live (re-ran the same browser flow,
only the correct article was cited) and covered by a regression test
(`test_weakly_relevant_chunks_are_filtered_out_of_sources` in
`tests/test_rag_pipeline.py`) so it can't silently reappear as the
knowledge base keeps growing in later epics.

## What's still open

- `next_follow_up_question()`'s three checks (symptom → severity → onset)
  are a fixed, hand-picked order — not adapted to which gap would most
  change the triage outcome for a given symptom. A more targeted version
  could ask about the specific missing field a matching `rules.yaml`
  condition actually depends on (e.g. skip the onset question entirely
  for a symptom with no onset-gated rule).
- No conversation persistence beyond what the client resends each turn —
  `prior_turns` is stateless by design (matches the existing JWT-based,
  no-server-session architecture), but this means a page refresh mid-
  conversation loses the in-progress thread. Only a *completed* exchange
  is saved to chat history, by design (an incomplete symptom picture
  isn't a triage decision worth persisting) — but the in-progress
  question-and-answer exchange itself isn't recoverable after a refresh.
- The `_RELEVANCE_RATIO = 0.5` cutoff is a hand-picked constant, not
  tuned against a labeled retrieval-quality eval set — the same caveat
  `docs/phase6a-dense-retrieval.md` already notes for dense retrieval's
  model choice. The adversarial eval harness from Phase 3 is the natural
  place to add retrieval-quality cases once there's a reason to tune this
  further.
