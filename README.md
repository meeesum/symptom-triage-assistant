# Symptom Triage Assistant

An informational (not diagnostic) symptom-triage product: patient intake →
deterministic red-flag safety check → RAG-grounded explanation for
lower-risk cases → provider dashboard for oversight.

See the full 12-month roadmap context in `docs/`, and the six-phase
scale-up plan (prototype → ~30k-line multi-tenant platform) in the
published roadmap artifact. This repo covers **Phase 2 (Core Triage
Engine + intake layer)**, working slices of **Phase 1 (knowledge base +
RAG)** and **Phase 4 (persistent audit log, auth/RBAC, chat history)**, a
first pass of **Phase 3 (adversarial safety evaluation)**, and the
scale-up plan's **Phase 01 (Production Foundations) — complete, all four
epics**: Postgres + Alembic migrations, Redis-backed token tracking,
observability & CI, and API hardening, the scale-up plan's
**Phase 02 (Clinical Depth) — complete, all five epics**: dense-embedding
retrieval, knowledge-base expansion, multi-turn triage, semantic
groundedness, and a clinical review workflow, plus the scale-up plan's
**Phase 03 (Provider & Care-Team Platform) — complete, all six epics**:
patient panels, clinical notes, referral & appointment tracking, a
provider analytics dashboard, high-risk alerting + a real job queue, and
notifications, plus the scale-up plan's **Phase 04 (Multi-Tenancy &
Compliance) — complete, all four epics**: organizations, consent & data
rights, an admin action audit log, and retention & purge jobs, plus the
scale-up plan's **Phase 05 (Reach & Polish) — complete, all four
epics**: a responsive redesign + PWA, internationalization (English +
Spanish), symptom photo upload, and reporting exports, plus the
scale-up plan's **Phase 06 (Quality at Scale) — complete, all three
epics, completing the entire six-phase scale-up plan**: an end-to-end
Playwright test suite, an expanded adversarial eval set (16 → 72 cases)
+ Locust load testing, and cross-phase contract tests.
See `docs/phase1-knowledge-base-and-rag.md`, `docs/phase2-safety-engine.md`,
`docs/phase2-intake-layer.md`, `docs/phase3-adversarial-eval.md`,
`docs/phase4a-audit-persistence.md`, `docs/phase4b-auth-rbac.md`,
`docs/phase4c-chat-history.md`, `docs/phase5-postgres-migration.md`,
`docs/phase5b-redis-token-tracking.md`, `docs/phase5c-observability-ci.md`,
`docs/phase5d-api-hardening.md`, `docs/phase6a-dense-retrieval.md`,
`docs/phase6b-knowledge-base-expansion.md`,
`docs/phase6c-multi-turn-triage.md`,
`docs/phase6d-semantic-groundedness.md`,
`docs/phase6e-clinical-review-workflow.md`,
`docs/phase7a-patient-panels.md`, `docs/phase7b-clinical-notes.md`,
`docs/phase7c-referral-tracking.md`,
`docs/phase7d-provider-analytics.md`,
`docs/phase7e-high-risk-alerting.md`,
`docs/phase7f-notifications.md`,
`docs/phase8a-organizations.md`,
`docs/phase8b-consent-and-data-rights.md`,
`docs/phase8c-admin-action-audit-log.md`,
`docs/phase8d-retention-and-purge-jobs.md`,
`docs/phase9a-responsive-and-pwa.md`,
`docs/phase9b-internationalization.md`,
`docs/phase9c-symptom-photo-upload.md`,
`docs/phase9d-reporting-exports.md`,
`docs/phase10a-e2e-test-suite.md`,
`docs/phase10b-expanded-eval-and-load-testing.md`, and
`docs/phase10c-cross-phase-contract-tests.md` for
the design rationale behind each.

## What's implemented right now

- `backend/app/safety/` — the rule-based escalation engine. Data-driven
  (`rules.yaml`), pure-function evaluator (`engine.py`), fully typed
  schemas (`schemas.py`). 20 passing unit tests.
- `backend/app/intake/` — deterministic free-text → `SymptomInput`
  extractor (`extractor.py` + `symptom_phrases.py`). Keyword/regex-based
  on purpose, not LLM-based — see `docs/phase2-intake-layer.md` for why.
  Enforces (via test) that every symptom referenced in `rules.yaml` has
  extractable phrases.
- `data/knowledge_base/articles/` — 6 seed knowledge-base articles
  (placeholder content, flagged for clinical review before real use),
  chunked and tagged to the rule set.
- `backend/app/rag/` — real TF-IDF retrieval (`retriever.py`) over the
  knowledge base, a pluggable LLM client (`llm_client.py`: real Anthropic
  call if `ANTHROPIC_API_KEY` is set, deterministic extractive fallback
  otherwise), a groundedness check (`groundedness.py`, run only on real
  LLM output — a lexical-overlap heuristic against the retrieved context;
  ungrounded output is discarded in favor of the extractive fallback, not
  shown to the patient), and the wired-up pipeline (`pipeline.py`) — no
  longer a stub. See `docs/phase1-knowledge-base-and-rag.md` for what the
  groundedness check does and doesn't catch.
- `backend/app/api/triage.py` — two endpoints sharing one decision path:
  `POST /triage/evaluate` (structured input) and `POST /triage/intake`
  (raw text). Emergency/urgent tiers bypass RAG entirely and return rule
  guidance directly; routine/self_care tiers get a grounded, cited
  explanation from the knowledge base.
- `backend/app/core/db.py` + `app/models/audit.py` + `app/services/audit_log.py`
  — persistent audit trail (SQLite bootstrap, see `docs/phase4a-audit-persistence.md`).
  Every triage decision writes to both stdout and a DB table; a DB outage
  degrades to stdout-only rather than ever blocking a triage response.
- `backend/app/api/auth.py` + `app/api/deps.py` + `app/models/user.py` +
  `app/core/security.py` — email/password accounts, JWT sessions, three
  roles (patient/provider/admin). `GET /audit/recent` now requires a
  provider or admin token — verified live against a real server: no
  token → 401, patient token → 403, provider token → 200.
- `backend/app/models/revoked_token.py` + `app/services/token_revocation.py`
  + `POST /auth/logout` — real token revocation via a DB-backed blocklist
  keyed on each JWT's `jti`. Verified live: the exact same token that
  returns 200 before logout returns `401 {"detail": "token has been
  revoked"}` immediately after — not just a client-side `localStorage`
  clear. The frontend's logout button calls this endpoint for real.
- `backend/app/api/admin.py` + `scripts/create_admin.py` — role assignment
  is now admin-controlled, not self-service: `/auth/register` always
  creates a `patient` (a `"role":"admin"` field in the request body is
  silently ignored — verified live), and `GET/PATCH /admin/users*`
  (admin-only) is how a patient becomes a provider or admin. The bootstrap
  script creates the very first admin account directly via the DB, since
  no admin exists yet to promote anyone on a fresh deployment.
- `backend/app/models/refresh_token.py` + `app/services/refresh_tokens.py`
  + `POST /auth/refresh` — access tokens shrank from 24h to 1h, backed by
  a real refresh-token flow: 7-day refresh tokens with rotation (each use
  invalidates itself and issues a new one) and reuse detection (replaying
  an already-used refresh token revokes *every* session for that user, not
  just the replay). Verified live: rotate once, replay the old token
  (401), then try the token from the legitimate rotation (also 401) —
  proving reuse detection nukes the whole session. Access and refresh
  tokens are also mutually rejected as the wrong type (a refresh token
  can't be used as an API credential and vice versa). See
  `docs/phase4b-auth-rbac.md` for what's still open (PBKDF2 not a
  maintained hashing lib, DB-backed tracking that doesn't scale past a
  prototype).
- `frontend/` — Next.js (App Router, TypeScript) app with four pages: the
  triage chat UI (`/`), login/register (`/login`), a provider audit
  dashboard (`/audit`), and admin-only user management (`/admin`, list +
  promote via dropdown). Auth state is a thin `localStorage` wrapper
  (`lib/auth.ts`) storing both access and refresh tokens — explicitly not
  production session handling. `authFetch()` in `lib/api.ts` now retries
  once on a 401 via a silent token refresh, single-flighted so concurrent
  401s share one refresh call instead of racing separate ones — verified
  live with a corrupted-access-token test, which also caught a real bug:
  the first (non-single-flight) version let two concurrent refreshes
  race, and the loser's reuse-detected failure wiped out the winner's
  freshly-saved tokens seconds after they were written. Also verified
  end-to-end in a real browser: emergency and self-care triage cases
  render correctly; logged-out/patient/provider each hit the right state
  on `/audit`; a patient's live triage submission shows up in the
  provider's audit table without a page reload; promoting a user to
  provider through `/admin`'s dropdown persists; and the logout button's
  revoke request actually invalidates the refresh token server-side
  (confirmed by trying to use it via curl immediately after clicking "Log
  out" in the browser — 401). Caught and fixed a real bug in the process
  — the nav bar's logged-in state didn't refresh after a client-side
  redirect (e.g.
  register → `/audit`) because its `useEffect` had no dependency on the
  route; fixed by keying it off `usePathname()`.
- `backend/app/models/chat_exchange.py` + `app/services/chat_history.py`
  + `GET /triage/history` — triage chat history now persists for
  logged-in patients (anonymous use is unaffected — `/triage/intake`
  takes an optional bearer token via a new `get_optional_current_user`).
  Verified live: sent a message while logged in, did a full page reload
  (not a client nav — the JS runtime restarted), and the message was
  still there via a real `GET /triage/history` call; confirmed the
  endpoint 401s with no token, so one user's history isn't reachable by
  another. See `docs/phase4c-chat-history.md`.
- `data/eval/adversarial_cases.json` + `backend/app/eval/` — adversarial
  eval harness (`scripts/run_eval.py` CLI report + wired into pytest).
  First run surfaced 3 real under-triage bugs (fixed same session,
  including a new safety rule) and a negation-handling gap (closed in a
  follow-up pass — see `docs/phase3-adversarial-eval.md`). Expanded from
  16 to 72 cases across 15 categories in the scale-up plan's Phase 06 —
  see below and `docs/phase10b-expanded-eval-and-load-testing.md` for
  the six real safety bugs that expansion found and fixed (infant age in
  weeks not parsed, "feels warm" not a fever phrase, patient context
  flags having zero negation handling, and four phrase-list gaps), plus
  what it found and deliberately left as documented `known_gap`s (a
  Spanish-specific negation asymmetry, a severity-matching substring
  collision, and an unused `has_cardiac_history` context flag). 16 known
  gaps remain total, `xfail(strict=True)`'d so a silently-fixed gap fails
  the build until docs are updated; several need a clinical reviewer, not
  more engineering.
- `backend/tests/` — 534 tests total (517 passing + 16 intentional xfail +
  1 opt-in skipped by default):
  23 safety engine + 9 API integration + 6 retriever + 7 RAG pipeline +
  28 intake extractor + 73 adversarial eval (56 must_pass + 16 known_gap
  xfail + 1 case-set sanity check) + 3 audit persistence +
  21 auth/RBAC/admin + 7 groundedness + 10 refresh tokens (incl. a real
  concurrency test hammering the same token from 8 threads, reverified
  against real Redis) + 6 chat history + 5 token revocation + 4 rate
  limiting + 2 health/readiness + 3 request-size limits + 6 dense
  retriever + 5 embeddings + 7 KB ingestion CLI + 13 conversation state +
  6 multi-turn API + 7 LLM entailment + 10 KB review service +
  13 KB review API + 11 patient panel service + 7 patient panel API +
  3 audit panel scoping + 6 clinical notes service + 7 clinical notes
  API + 11 referral service + 7 referral API + 7 analytics service +
  4 analytics API + 5 alerting service + 6 alerting API + 13 notification
  service + 6 notification API + 6 organizations service + 9
  organizations API + 6 consent service + 11 data rights service + 9
  consent/data-rights API + 6 admin action log service + 8 admin action
  log API + 9 org_admin access-gap regression + 5 retention service + 4
  retention API + 13 i18n intake service (Spanish extraction/negation/
  conversation flow) + 7 i18n RAG service (per-language retrieval,
  Spanish stopwords, per-language fallback text) + 8 i18n triage API
  (end-to-end Spanish triage, guidance-translation coverage) + 9 symptom
  photo service (image validation, storage, retrieval) + 12 symptom
  photo API (upload ownership, provider-panel visibility, oversized/
  invalid-image rejection, delete) + 5 reporting service (CSV/PDF export
  content and panel scoping) + 12 report delivery service (subscription
  CRUD, due-date logic incl. the SQLite timezone regression, send
  success/failure) + 14 reports API (export role gating, subscription
  lifecycle) + 13 cross-phase contracts (org isolation across audit/
  notes/referrals/analytics/exports, retention-never-touches-consent,
  data-rights-deletion-removes-photos, retention-purge-removes-photos,
  a documented dormant stale-panel-assignment risk). The LLM-path tests use a
  fake `AnthropicLLMClient` subclass (no `anthropic` package or API key
  needed — see `docs/phase1-knowledge-base-and-rag.md`); the LLM
  entailment checker's tests fake the `anthropic` module itself the same
  way (see `docs/phase6d-semantic-groundedness.md`); the dense
  retriever's tests use a fake deterministic embedder the same way (no
  network/model
  download needed — see `docs/phase6a-dense-retrieval.md`).
  One further test (real `fastembed`, network-gated) is opt-in and
  skipped by default — see `tests/test_dense_retriever_live.py`.
- `backend/alembic.ini` + `migrations/` + `app/core/migrate.py` — real
  Alembic migrations replace the old `Base.metadata.create_all()`
  bootstrap. Both SQLite (still the zero-setup default) and Postgres now
  run off the exact same migration history. Verified against a real,
  throwaway Postgres 16 instance (not just SQLite): ran the full 128-test
  suite against it directly, confirmed real rows landed
  (39 users / 15 audit records / 66 refresh tokens), and caught a real bug
  in the process — `tests/conftest.py` was unconditionally overwriting
  `DATABASE_URL`, silently making every earlier "test against Postgres"
  attempt a no-op. Switched from `psycopg2-binary` to `psycopg` v3, since
  psycopg2 has no Python 3.13 wheel and fails to compile against 3.13's
  C API changes. See `docs/phase5-postgres-migration.md`.
- `backend/app/core/redis_client.py` + rewritten
  `app/services/token_revocation.py` / `app/services/refresh_tokens.py` —
  the access-token blocklist and refresh-token tracking moved off SQL
  tables (`refresh_tokens`/`revoked_tokens` — dropped by a real Alembic
  migration) onto Redis, closing the "costs a DB lookup per request" and
  "no purge job" gaps flagged since Phase 4. Revoked tokens self-expire
  via Redis TTL instead of needing a purge job at all. The SQL version's
  atomic-claim race fix (`UPDATE ... WHERE used_at IS NULL`) became
  Redis's `SET key value XX GET` — same "claim exactly once under
  concurrency" guarantee, different primitive, re-verified with the same
  8-thread concurrency test (reran 3x to be sure). `fakeredis` keeps the
  test suite zero-setup, same pattern as SQLite for Postgres. Verified
  against a real, throwaway Redis instance: ran the full suite against
  it, independently confirmed 101 real keys existed afterward via
  `redis-cli`, then drove the complete register → refresh → replay
  (401) → logout → revoked-token-rejected (401) flow live with curl
  against a real running server. See `docs/phase5b-redis-token-tracking.md`.
- `app/core/logging_config.py` + `app/core/sentry.py` + `app/api/health.py`
  — structured JSON/console logging (wraps stdlib `logging`, so the one
  existing `logging.getLogger` call site gets it for free), opt-in Sentry
  (`SENTRY_DSN`, a genuine no-op unset), and a real liveness/readiness
  split: `GET /health/ready` checks DB + Redis and returns actual `503`
  (not just a JSON field) when either is down — verified live by killing
  a real Redis instance mid-run and confirming `{"database": true,
  "redis": false}` with a 503 status. `backend/Dockerfile` +
  `frontend/Dockerfile` (the frontend's using Next's `output: "standalone"`,
  verified via a real `npm run build`) + two GitHub Actions workflows
  (backend lint+test — run twice, once on the SQLite/fakeredis zero-setup
  default and once against real Postgres+Redis service containers — and
  frontend typecheck+build). Expanding `ruff`'s rule set to actually catch
  real issues (bugbear, pyupgrade, simplify, logging) surfaced 33
  pre-existing findings across the whole codebase, all fixed before wiring
  lint into CI. See `docs/phase5c-observability-ci.md`.
- `app/core/rate_limit.py` + `app/core/request_limits.py` — per-IP rate
  limiting (`slowapi`, Redis-backed) on `/auth/register` (5/min),
  `/auth/login` (10/min), `/auth/refresh` (30/min) — narrow, not a
  blanket API-wide limit — plus a 1 MiB request body cap. Verified live:
  hammered `/auth/register` 6 times with curl, first 5 succeeded, 6th got
  429. Wiring the limiter into the test suite immediately broke 30
  unrelated tests (`TestClient` always presents the same synthetic IP) —
  fixed with the same "disabled by default for tests, explicitly
  re-enabled by its own dedicated test file" pattern, documented as a
  genuine necessity rather than glossed over. Also documents a deliberate
  **no-`/v1/`-prefix-yet** API versioning decision with explicit trigger
  conditions for when to add one. See `docs/phase5d-api-hardening.md`.
  **This completes Phase 01 (Production Foundations) of the scale-up plan.**
- `app/rag/embeddings.py` + `app/rag/dense_retriever.py` — pluggable dense
  retrieval: `fastembed` (ONNX, no torch — `torch` has no distribution for
  this project's Python 3.13 here) generates embeddings, `qdrant-client`
  indexes them (in-memory by default, real server via `QDRANT_URL`, same
  zero-setup pattern as Postgres/Redis). Same `retrieve(query, k) ->
  list[ScoredChunk]` interface as the existing TF-IDF retriever, selected
  via `RETRIEVAL_BACKEND=dense` (TF-IDF stays the default until it's had
  real pilot validation). Verified live with the real model: the
  paraphrased query "my chest feels tight and I can't catch my breath"
  (zero lexical overlap with the article's own wording) still ranks the
  `chest_pain` article first — the exact paraphrase gap TF-IDF's own
  docstring named as its limitation. First epic of the scale-up plan's
  Phase 02 (Clinical Depth). See `docs/phase6a-dense-retrieval.md`.
- `scripts/kb_ingest.py` — a KB ingestion CLI (`check-coverage` cross-
  references `rules.yaml`'s symptom_ids against every article's tags;
  `add` validates and ingests a draft article, stamping provenance
  metadata) plus **eleven new KB articles** closing all nineteen
  symptom_ids that previously fell back to bare rule guidance with no
  citation — verified live: `check-coverage` now reports zero gaps,
  enforced going forward by `tests/test_kb_ingest.py`. Deliberately
  eleven articles, not the roadmap's rough "40+" loc-budget estimate —
  clinically-clustered symptoms (e.g. a heart attack's four associated
  symptoms) share one coherent article rather than being split into thin,
  overlapping ones purely to hit a round number; see
  `docs/phase6b-knowledge-base-expansion.md` for the reasoning. All
  content, old and new, stays explicitly `"source_type": "placeholder"` —
  a new `reviewed` field on every article stays `false` until the
  Clinical Review Workflow epic (still open, see below) actually builds a
  reviewer queue. Second epic of Phase 02.
- `app/intake/conversation.py` — multi-turn triage: merges a sequence of
  raw messages into one `SymptomInput` and, when confidence is low
  (unknown severity/onset, or no symptom recognized), returns a targeted
  follow-up question instead of a decision. Opt-in via
  `allow_follow_up` on `POST /triage/intake` (default `false` — every
  existing caller's behavior is unchanged); the safety fast path always
  wins regardless — an emergency/urgent tier finalizes immediately, no
  follow-up question, ever. `TriageChat.tsx` implements the multi-turn
  UI. Verified live through the real browser UI (not just curl/tests):
  a "cough" message triggers a severity question, the answer completes
  the decision, and "sudden chest pain and sweating" still finalizes
  immediately as emergency with `allow_follow_up` on. This also surfaced
  and fixed a real bug from the knowledge-base-expansion epic: the RAG
  pipeline's chunk retrieval let weakly-relevant, generic-vocabulary
  matches ride along with a strong match (e.g. a mild-cough query pulling
  in the pregnancy-bleeding article) — fixed with a relative relevance
  filter in `app/rag/pipeline.py`, covered by a regression test. Third
  epic of Phase 02. See `docs/phase6c-multi-turn-triage.md`.
- `app/rag/groundedness.py` — a real semantic entailment check for the
  LLM path, opt-in via `GROUNDEDNESS_METHOD=llm`: a second Anthropic call
  asking directly "does this claim follow from this context?" instead of
  the default lexical-overlap heuristic. Deliberately NOT built as dense-
  embedding cosine similarity — generic sentence embeddings are good at
  topic similarity, not at telling a supported claim from a topically-
  similar contradiction of it (e.g. "chest pain resolves on its own" vs.
  "chest pain can indicate a heart attack" would likely still score
  close on embedding similarity). Opt-in rather than the new default: it
  doubles the LLM path's per-request cost/latency, a tradeoff a
  deployment should choose deliberately. No real `ANTHROPIC_API_KEY` is
  available in this sandbox, so the real network call is unverified here
  (same caveat as `AnthropicLLMClient` generally) — but the wiring is:
  fakes prove `GROUNDEDNESS_METHOD=llm` actually resolves to the new
  checker, and an end-to-end pipeline test proves a lexically-plausible-
  but-contradictory claim that the default checker would accept is
  correctly rejected once the real-entailment mode is enabled. Fourth
  epic of Phase 02. See `docs/phase6d-semantic-groundedness.md`.
- `app/api/kb_review.py` + `app/services/kb_review.py` — a clinical
  review queue: a provider/admin submits a KB article draft, a
  *different* provider/admin approves or rejects it (self-review is
  blocked — enforced, not just a UI convention). Approval is what
  actually flips an article's `reviewed` field to `true` for the first
  time — closing the gap `docs/phase6b-knowledge-base-expansion.md` left
  open — and writes it via the same `write_article_file()` now shared
  with `scripts/kb_ingest.py`'s CLI. Version history: one DB row per
  submission (not per article), queryable per `article_id`, nothing ever
  overwritten. Verified live end-to-end with two real, separately
  logged-in provider accounts: submitted a draft with a unique marker
  sentence, confirmed the file didn't exist yet, approved it as the
  other account, confirmed the file appeared with `reviewed: true`, and
  — without restarting the server — confirmed the SAME running process
  immediately retrieved and cited it, proving the retriever cache
  invalidation on approval actually works, not just in a mocked test.
  No frontend UI for this yet (backend-only pass, see the doc). Fifth
  and final epic of Phase 02 — **Phase 02 (Clinical Depth) is now
  complete.** See `docs/phase6e-clinical-review-workflow.md`.
- `app/api/patient_panel.py` + `app/services/patient_panel.py` — provider-
  patient panel assignment, admin-controlled (same pattern as role
  assignment). `GET /audit/recent` now scopes for the `provider` role: a
  provider sees only audit rows for patients on their own panel, plus
  every anonymous row (no `patient_id` — can't be tied to any patient,
  so panel-scoping it further would only hide data, not protect anyone).
  `admin` stays unrestricted. Verified live with real, distinct accounts
  (not mocked): an admin assigned patient A (not patient B) to a
  provider; both patients submitted an emergency triage; the provider's
  `/audit/recent` correctly showed ONLY patient A's record, while the
  admin's view showed both. First epic of the scale-up plan's Phase 03
  (Provider & Care-Team Platform). See `docs/phase7a-patient-panels.md`.
- `app/api/clinical_notes.py` + `app/services/clinical_notes.py` —
  provider annotations (`POST`/`GET /audit/{id}/notes`) on a triage audit
  record: free-text `body` plus a structured `note_type`
  (`clinical_impression`/`follow_up`/`general`). Reuses patient panels'
  exact visibility rule rather than defining a new one — a note is
  exactly as sensitive as the record it's attached to. An outsider
  provider (not on the patient's panel) gets a 404, not a 403 —
  deliberately indistinguishable from "no such record," the same
  existence-hiding judgment already used for login errors. Verified
  live: a provider added a note on their panel patient's emergency
  triage record and read it back; a second, separate provider account
  NOT on that panel got a real 404 from the running server. Second epic
  of Phase 03. See `docs/phase7b-clinical-notes.md`.
- `app/api/referrals.py` + `app/services/referrals.py` — referral &
  appointment status tracking: `POST`/`GET`/`PATCH /audit/{id}/referral`,
  one `Referral` per audit record moving forward through `referred` ->
  `scheduled` -> `seen` (skipping a stage is allowed — e.g. a same-day
  walk-in going straight to `seen` — but moving backward is rejected
  with a 409). Every transition is recorded append-only in
  `ReferralStatusChange`, so "who moved this and when" is always
  answerable. Same panel-based visibility as clinical notes. Verified
  live against a real running server: created a referral, advanced it
  through all three statuses with the history growing correctly at each
  step, then confirmed attempting to move backward from `seen` to
  `referred` got a real 409 with the exact rejection message. Third
  epic of Phase 03. See `docs/phase7c-referral-tracking.md`.
- `app/api/analytics.py` + `app/services/analytics.py` +
  `frontend/app/analytics/page.tsx` — `GET /audit/analytics`: triage
  volume by day, tier distribution, and time-to-follow-up (mean/median
  hours from an audit record's creation to the first referral status
  change past `referred`). Same panel-based visibility as the audit
  trail, now shared via a new `app/services/audit_visibility.py`
  extracted from `GET /audit/recent` itself (refactored, no behavior
  change) so both endpoints apply the identical rule rather than two
  copies that could drift apart. The first Phase 03 epic with a real
  frontend page — an inline-SVG bar chart plus CSS tier-distribution
  bars, no charting library. Verified live: seeded 5 real triage
  decisions via the API, confirmed the aggregation via curl, then logged
  in through the actual login form and confirmed the browser-rendered
  dashboard showed the exact same numbers. Caught and fixed a stale
  disclaimer on the audit page while at it — it still claimed "no
  per-provider record scoping yet," true when written, false since the
  patient-panels epic. Fourth epic of Phase 03. See
  `docs/phase7d-provider-analytics.md`.
- `app/services/alerting.py` + `app/core/queue_client.py` +
  `GET /alerts/recent` — this project's first real async job queue (RQ,
  chosen over Celery since it reuses the existing Redis infrastructure
  directly with no separate broker to stand up). An emergency-tier
  triage creates an `Alert` row and enqueues a job INLINE (one fast
  INSERT, wrapped so an alerting outage can never delay/break the
  response — same principle as audit logging); a separate `process_alert`
  job resolves the patient's on-call provider (if panel-assigned) and
  marks it sent — real notification delivery is the next epic. Verified
  live against a REAL worker process, not just tests (a test suite can't
  keep one running): started a real, throwaway Redis instance and the
  real server with the app's actual default (`ALERTING_SYNC` unset, real
  async queueing), submitted an emergency triage, confirmed the alert
  sat `queued` with the response already returned and the job genuinely
  sitting in Redis (`LLEN rq:queue:high_risk_alerts` = 1), then started a
  real `rq.Worker` process and watched it pick up and complete the job,
  flipping the alert to `sent` with a real timestamp. Fifth epic of
  Phase 03. See `docs/phase7e-high-risk-alerting.md`.
- `app/services/notifications.py` + `app/api/notifications.py` — a real
  email/SMS wrapper (stdlib `smtplib` for email, a direct Twilio REST API
  call via stdlib `urllib` for SMS — no third-party SDKs for either) with
  self-service preferences (`GET`/`PUT /notifications/preferences`) —
  the one Phase 03 resource a user manages themselves rather than an
  admin, since it's a personal preference, not an assignment. Wired
  directly into the previous epic's job:
  `process_alert()` now dispatches a real notification to the resolved
  on-call provider. Live verification caught and fixed a real bug: the
  email client unconditionally required STARTTLS, which failed outright
  against a real local debug SMTP server that doesn't support it — fixed
  with a `SMTP_USE_TLS` toggle (default on, matching real relays like
  Gmail/SendGrid), then re-verified sending cleanly. The Twilio path was
  verified by calling the REAL Twilio API with syntactically-valid-but-
  fake credentials — got back a genuine `401 Unauthorized` (not a
  connection error), proving the request itself (URL, auth header, body)
  is built correctly; only a real account is missing, unverifiable in
  this sandbox. Sixth and final epic — **Phase 03 (Provider &
  Care-Team Platform) is now complete.** See
  `docs/phase7f-notifications.md`.
- `app/models/organization.py` + `POST /organizations` + `org_slug` on
  `POST /auth/register` — multi-tenancy, with a real architectural bet:
  isolation is enforced ONCE, in `app/services/patient_panel.py`'s
  `assign_patient()` (rejects a cross-org provider/patient pair
  outright), rather than re-derived at every read. Every panel-scoped
  view built across Phase 03 (audit trail, clinical notes, referrals,
  analytics, alerts) inherits tenant isolation for free as a result — no
  changes needed to any of them. New `org_admin` role (per-tenant user
  management, cannot escalate to platform-wide `admin`); every
  pre-existing workflow keeps working unchanged via a zero-setup default
  organization seeded by the migration itself. Verified live with two
  real organizations signed up through the running server: each
  org_admin's user list showed only their own org; a cross-org panel
  assignment attempt got a real 404 from the org_admin (existence
  hidden) and a real 422 with the actual mismatch reason from the
  platform admin (who can see both orgs, and still gets rejected at the
  service layer). First epic of the scale-up plan's Phase 04
  (Multi-Tenancy & Compliance). See `docs/phase8a-organizations.md`.
- `app/services/consent.py` + `app/services/data_rights.py` +
  `app/api/consent.py` + `app/api/data_rights.py` — self-service,
  GDPR/HIPAA-style consent tracking (append-only — withdrawing is a new
  row, not an overwrite) and data export/deletion. Export is complete,
  not capped like `GET /triage/history` (a truncated "what do you have
  on me" response would be a real compliance bug). Deletion means
  **anonymization, not a hard DELETE**: chat history is genuinely
  deleted, audit records are unlinked (`patient_id` → `NULL`, same as an
  anonymous request) but kept for the audit trail's own compliance
  purpose (GDPR Art. 17(3) explicitly allows this), the account's
  email/password are scrambled beyond recovery, and every refresh token
  plus the current access token are revoked immediately. Verified live
  end to end against a real running server and real DB state: exported a
  real account's real consent + chat data, requested deletion, confirmed
  the SAME token that performed the deletion was immediately rejected as
  revoked, confirmed the original login credentials no longer worked,
  and confirmed via direct DB query that chat history was gone, the
  audit record survived with `patient_id: NULL`, and the account email
  was a real anonymized placeholder. Second epic of Phase 04. See
  `docs/phase8b-consent-and-data-rights.md`.
- `app/models/admin_action_log.py` + `app/services/admin_action_log.py` +
  `GET /admin/action-log` — a second, narrower audit trail than the
  clinical one, covering the platform's own admins: who changed which
  role, assigned/unassigned a patient panel, created an org, approved or
  rejected a KB submission, and — the roadmap's other named example —
  who VIEWED which patient's clinical notes or referral (fires on the
  read, a real access log, not just a write log). Org-scoped for
  `org_admin`, unrestricted for platform `admin`, same pattern as every
  other admin-facing list in this project. Verified live: promoted a
  real user and confirmed the exact role-change detail in the log;
  had an admin view a specific patient's clinical notes and confirmed
  `viewed_clinical_notes` appeared against that exact record id.
  Surfaced (and then fixed — see below) a real gap: six Phase 03
  endpoints still gated on `require_role("provider", "admin")` from
  before `org_admin` existed, so `org_admin` got a flat 403 on all of
  them — fail-closed, not a data leak, but a real completeness gap.
  Third epic of Phase 04. See `docs/phase8c-admin-action-audit-log.md`.
- **Fixed the `org_admin` access gap** the action-log epic surfaced:
  `GET /audit/recent`, `GET /audit/analytics`, `GET /alerts/recent`,
  both clinical-notes routes, all three referral routes, and
  `GET /panel/mine` now all accept `org_admin`, scoped correctly to
  their own org's patients (not a provider's panel — `org_admin` is
  administrative, not clinical, so a new
  `org_admin_can_view_record()`/`audit_visibility_clause` branch scopes
  by org membership instead). Verified live against a real running
  server: all three previously-403 endpoints returned real `200`s for a
  freshly signed-up `org_admin`; a dedicated 9-test regression suite
  confirms both the fix (org_admin can now use every endpoint) and that
  it's correctly scoped (can't see another org's records or notes).
- `app/services/retention.py` + `app/models/retention_purge_run.py` +
  `scripts/run_retention_purge.py` + `POST`/`GET /admin/retention/*` —
  configurable retention windows for chat history, audit records, and
  the admin action log, reusing the exact job-queue infrastructure from
  the high-risk-alerting epic (the roadmap's own named dependency,
  actually used, not just referenced). Genuine deletion, not
  anonymization — a retention policy's point is that data eventually
  goes away entirely, unlike a specific data-rights deletion request.
  The roadmap also named "the revoked-token and refresh-token tables"
  for this epic — already closed by the Phase 01 Redis migration's
  self-expiring TTL keys, said explicitly rather than silently
  reused/skipped. Verified live: seeded real 200-day and 500-day-old
  rows directly in the DB, ran the real cron script
  (`scripts/run_retention_purge.py`), confirmed via direct DB query that
  only the old rows were deleted and the recent ones survived; separately
  confirmed the API-triggered path genuinely stays queued (async) rather
  than running inline. Fourth and final epic — **Phase 04
  (Multi-Tenancy & Compliance) is now complete.** See
  `docs/phase8d-retention-and-purge-jobs.md`.
- `frontend/public/manifest.json` + real PNG icons (generated with
  Pillow, not placeholders) + `frontend/public/sw.js` — an installable
  PWA with a service worker deliberately scoped narrow: caches the app
  shell for instant loads and a real offline fallback page, but NEVER
  caches any API response — a health-triage app showing a stale cached
  triage result offline would be actively misleading, not a convenience.
  Verified live: fetched both icon files (real `200`s with actual image
  bytes), confirmed the service worker registered and reached
  `"activated"`, and inspected `CacheStorage` directly to confirm it held
  exactly the app shell and zero API responses. Also found and fixed a
  real mobile bug while auditing the existing pages at a genuine 375px
  viewport: the navbar had no wrap behavior, and logged in as admin (4
  nav links + auth controls) the Log out button was reachable in the DOM
  but visually cut off outside the navbar — fixed with proper flex-wrap
  and a stacking breakpoint, reverified with a screenshot showing
  everything visible and clickable. First epic of the scale-up plan's
  Phase 05 (Reach & Polish). See `docs/phase9a-responsive-and-pwa.md`.
- `app/intake/symptom_phrases.py` (`PHRASES_BY_LANGUAGE`) +
  `app/safety/guidance_translations.py` + 11 new `*_es.json` knowledge-base
  articles — internationalization: English + Spanish. Not a UI-strings-only
  pass — the deterministic intake extractor (symptom/severity/onset/negation
  phrase matching, including Spanish-specific negation cue words), the
  safety engine's per-rule guidance text (all 18 `rules.yaml` rules, keyed
  by `matched_rule_id`, applied as a translation overlay so `rules.yaml`
  itself stays the single English-authored source of truth), and a
  safety-prioritized subset of the knowledge base (all 9 emergency-tier
  articles + 2 common self-care ones) are all language-aware, since a
  mistranslated or unrecognized symptom is a safety issue here, not a
  cosmetic one. Found and fixed a real TF-IDF retrieval bug along the way:
  `stop_words="english"` does nothing for Spanish text, so short Spanish
  function words were inflating irrelevant articles' scores and
  mis-ranking a chest-pain query — fixed with a hand-rolled Spanish
  stopword list, applied only for `language="es"`. Frontend gained
  `lib/i18n.ts` (localStorage-backed language preference, same pattern as
  `lib/auth.ts`) and a navbar language switcher; the patient-facing
  surface (triage chat, tier badges, login form) is translated, the
  provider/admin pages deliberately are not (internal tooling, not the
  patient safety path this epic is about). Verified live end-to-end in a
  real browser: switched to Español, submitted a real Spanish emergency
  chest-pain message and got correct symptom recognition, correct
  emergency tier, and — after the guidance-translation fix — the actual
  "call emergency services" text in Spanish; then a Spanish self-care
  message got a Spanish follow-up question and a Spanish RAG-grounded
  explanation citing the correct Spanish KB article. Second epic of Phase
  05. See `docs/phase9b-internationalization.md`.
- `app/models/symptom_photo.py` + `app/services/symptom_photos.py` +
  `app/api/symptom_photos.py` — secure symptom photo upload
  (e.g. a rash), tied to a `TriageAuditRecord` (not `ChatExchange` —
  provider review needs the visibility rule only the audit record has)
  with provider-only review. Deliberately no image analysis anywhere:
  upload, list, view, delete only — a photo is stored and shown to a
  human, never fed to a model. Two independent validation layers: a
  streamed byte-size cap that never trusts `Content-Length` (rejects
  mid-stream, never buffers an oversized upload into memory), and
  Pillow actually decoding the bytes as a real JPEG/PNG/WEBP — a file
  disguised as an image (real magic bytes, garbage after) is rejected on
  content, not on filename or declared Content-Type. Storage filenames
  are always server-generated (`uuid4().hex`), never derived from client
  input, closing path-traversal/overwrite risk by construction. Reuses
  `app/services/patient_panel.py`'s existing visibility functions for
  provider review rather than a new rule, same pattern clinical notes and
  referrals already established. Found and fixed a real bug while writing
  the tests: the API-hardening epic's `MaxBodySizeMiddleware` capped
  every request at 1 MiB — including photo uploads, silently conflicting
  with this epic's own 5 MiB photo cap — fixed with a path-based
  exemption, covered by a regression test using a real >1 MiB image (seeded
  random-noise pixels so PNG compression can't shrink it back under the
  cap). Verified live end-to-end: uploaded a real photo via a logged-in
  patient's browser session, confirmed the file on disk and byte-identical
  on fetch, then logged in as a provider and saw the actual uploaded
  thumbnail render in a new "Photos" column on `/audit` via an
  authenticated `blob:` URL fetch (plain `<img src>` can't send a bearer
  token). Also caught and documented a real dev-workflow gotcha along the
  way: the PWA epic's own service worker was serving a stale cached JS
  bundle, making fresh frontend changes invisible until the service
  worker was unregistered and its cache cleared. Third epic of Phase 05.
  See `docs/phase9c-symptom-photo-upload.md`.
- `app/services/reporting.py` + `app/services/report_delivery.py` +
  `app/api/reports.py` — CSV/PDF exports off the provider analytics
  dashboard plus self-service scheduled report delivery for org admins.
  CSV exports the raw audit records; PDF (via `reportlab` — pure Python,
  no system deps) is a formatted summary reusing the analytics service's
  own aggregation functions directly, so it can never drift from what
  `/analytics` itself shows. Scheduled delivery reuses the exact
  two-phase job-queue pattern high-risk alerting and retention purge
  already established: an API-triggered send enqueues via RQ, while the
  cron entry point (`scripts/run_scheduled_reports.py`) runs
  synchronously since the script itself is already the explicit trigger.
  Found and fixed two real bugs while building this: a SQLite-specific
  timezone bug (`DateTime(timezone=True)` doesn't actually preserve
  tzinfo in SQLite, unlike Postgres — the first feature here to do
  Python-level datetime arithmetic on a DB-loaded timestamp instead of
  comparing at the SQL level, which is what exposed it), and a design
  bug where a failed email send would still silently advance
  `last_sent_at`, making a persistent SMTP outage invisible — fixed so
  delivery only counts as "sent" on actual success, letting the next
  cron run retry. Also found and fixed a real, unrelated bug while
  wiring the org_admin-only subscription UI onto `/analytics`: both
  `/audit` and `/analytics`'s frontend role gates (and the `Role`
  TypeScript type itself) never included `"org_admin"` at all — a
  leftover from before that role existed — so an org_admin got a
  client-side "forbidden" despite the backend already accepting them
  since the Phase 04 access-gap fix. Verified live: queued a real report
  via the actual UI, confirmed it landed in real Redis, processed it
  with a real `rq worker` process, and watched the UI's displayed
  "last sent" timestamp update after a reload; downloaded real CSV/PDF
  exports and read the rendered PDF content to confirm accurate,
  correctly-scoped data. Fourth and final epic — **Phase 05 (Reach &
  Polish) is now complete.** See `docs/phase9d-reporting-exports.md`.
- `frontend/e2e/` + `frontend/playwright.config.ts` — an end-to-end
  Playwright test suite replacing the manual browser verification every
  prior epic in this project relied on. Genuinely self-contained: starts
  BOTH a real FastAPI backend and a real Next.js frontend as actual child
  processes (`webServer`, a two-entry array) against a throwaway SQLite
  DB and fakeredis, so `npx playwright test` alone exercises the real
  stack with no manual setup step — same "zero setup by default"
  philosophy as everywhere else in this project. Five spec files cover
  the full patient journey (register, self-care + emergency decisions,
  the multi-turn follow-up flow, and a **real file upload** through the
  actual `<input type="file">` — closing a genuine gap in every prior
  epic's own manual verification, which had no file-picker capability at
  all), the provider journey (panel-scoped audit/analytics visibility,
  including a photo review), the admin journey (role promotion through
  the real `/admin` UI), internationalization (the language switcher
  itself, plus a full Spanish emergency flow), and reporting exports
  (subscribe, send-now, real browser downloads). Found and fixed a real
  bug while writing it: the `/admin` role-promotion dropdown's option
  list never included `"org_admin"` at all — the same class of gap
  already found in `/audit` and `/analytics`'s page-level role gates
  during the reporting-exports epic, this time meaning there was no way
  to actually *assign* that role through the UI despite the backend
  accepting it since the multi-tenancy epic. First epic of the scale-up
  plan's Phase 06 (Quality at Scale). See
  `docs/phase10a-e2e-test-suite.md`.
- `data/eval/adversarial_cases.json` expanded from 16 to 72 cases across
  15 categories + `backend/scripts/loadtest/` — the expanded adversarial
  eval and Locust load-testing epic. Before adding a single new case,
  fixed a real bug in the harness itself: `avoid_overtriage` cases (the
  alarm-fatigue guards) were toothless — `expected_tier: "self_care"` is
  the lowest tier rank, so the existing "not under-triaged" check could
  never fail no matter how badly the system over-reacted. Added a
  `max_tier` ceiling + `over_triaged` check to close it, which
  immediately surfaced that one of the two existing guard cases had a
  stale, never-actually-verified `expected_tier` claim. Every new case
  was run against the real extractor + safety engine first, not
  hand-guessed, the same discipline the original 16 were built with —
  and doing that found and fixed six real safety bugs along the way: a
  young infant's age stated in weeks wasn't parsed at all (silently
  defeating `infant_high_fever`'s age gate for real newborns), "feels
  warm" wasn't a recognized fever phrase, patient context flags
  (`is_pregnant`, `is_immunocompromised`, etc.) had zero negation
  handling at all — a completely different code path from symptom
  matching — so "I'm not pregnant" incorrectly set `is_pregnant=True`,
  and four phrase-list gaps on common lay descriptions (a stroke sign
  phrased without the word "drooping", "coughing up a lot of blood",
  the canonical "worst headache of my life" phrasing, "chest discomfort"
  and similar). Three more real gaps were found and deliberately left as
  documented `known_gap`s rather than rushed: a Spanish-specific
  negation asymmetry (Spanish's "probably nothing" hedge idiom contains
  a literal "no", unlike English's), a severity-matching substring
  collision ("extremely mild" misread as severe), and confirmation that
  `has_cardiac_history` is extracted but consulted by zero rules.
  `locustfile_triage.py` + `locustfile_auth_rate_limits.py` load-test
  the job-queue and rate-limiting layers respectively — verified live
  against a real running server with real Redis: 200 concurrent triage
  requests with 0 failures and 32 real emergency alerts genuinely
  enqueued at 12-13ms median latency, and the auth rate limiter holding
  **exactly** 5 successes each for `/auth/register` and `/auth/login`
  out of 10,182 requests at up to ~555 req/s. Second epic of the
  scale-up plan's Phase 06. See
  `docs/phase10b-expanded-eval-and-load-testing.md`.
- `backend/tests/test_cross_phase_contracts.py` — cross-phase contract
  tests, deliberately combining features from DIFFERENT epics in one
  scenario (the roadmap's own examples: "org isolation under panels,
  retention jobs against real consent records") rather than testing any
  one feature in isolation again. A research pass reading the actual
  current source (not guessing) before writing a single test found two
  real, serious bugs: symptom photo upload (Phase 05) was built a full
  epic after both data-rights deletion and retention purge (Phase 04)
  and was never wired back into either — a "delete my data" request and
  a routine retention purge BOTH left a patient's uploaded photos (DB
  rows and actual files on disk) completely untouched, indefinitely.
  Fixed both: `delete_user_data()` now deletes a patient's photos before
  anonymizing their account, and `purge_old_data()` now deletes a purged
  audit record's photos before hard-deleting the record itself
  (`RetentionPurgeRun` gained a new `symptom_photos_deleted` column, via
  a real migration, so the purge history is honest about what actually
  got cleaned up). Also confirmed and locked in with tests: retention
  correctly NEVER touches `consent_records`/`data_requests` (a
  regression guard against someone "helpfully" adding them to the purge
  scope later), and documented — without fixing, since it's currently
  unreachable through any real endpoint — a dormant risk where org
  isolation is enforced only at panel-ASSIGNMENT write-time, not
  re-checked at read-time by every panel-scoped reader. One shared
  cross-org scenario (two orgs, a panel-assigned provider/patient pair,
  a real emergency triage submitted through the actual API) is checked
  against `/audit/recent`, clinical notes, referrals, analytics, AND the
  CSV export all at once, rather than four separately-passing tests that
  could each individually be right while still disagreeing with each
  other. Caught a real bug in the test suite itself along the way: an
  early version of the CSV-export isolation check used a raw substring
  search over the whole export, which intermittently false-failed when
  run inside the full, shared-DB test suite (a record id coincidentally
  matching a digit inside an unrelated row's date) — fixed by parsing
  the CSV and checking the actual `id` column. Verified both real bugs'
  fixes live against a real running server (uploaded a real photo,
  requested real deletion, confirmed the file was actually gone from
  disk; backdated a real audit record with a real photo, ran the real
  `scripts/run_retention_purge.py`, confirmed the same). Third and final
  epic — **Phase 06 (Quality at Scale) is now complete, and so is the
  entire six-phase scale-up plan.** See
  `docs/phase10c-cross-phase-contract-tests.md`.

## What's NOT implemented yet (by design, tracked to later phases)

- Dense embeddings / vector DB now has a first implementation (see above)
  but TF-IDF is still the default (a documented bootstrap choice — see
  `docs/phase1-knowledge-base-and-rag.md` for why and its limits)
- A semantic/entailment-based groundedness check now has a first
  implementation too (opt-in via `GROUNDEDNESS_METHOD=llm` — see above)
  but the lexical-overlap heuristic is still the default, for the same
  cost/latency reasons dense retrieval isn't the default either — see
  `docs/phase6d-semantic-groundedness.md`
- Real (non-placeholder) knowledge-base content, reviewed against an
  actual verified source. There's now a review workflow (see above), but
  it verifies a submission got a second pair of eyes, not that the
  underlying claim is independently sourced — every article's
  `source_type` stays `"placeholder"` through approval
- Extractor phrase coverage beyond the seed list — real recall will need
  growing from pilot transcripts (see `docs/phase2-intake-layer.md`); one
  colloquial-phrasing gap is tracked as a known_gap eval case
- Two clinical-rule gaps (atypical heart-attack presentation, pediatric
  lethargy) that need a clinical reviewer before adding rules — tracked,
  not guessed at
- Delete/export of a patient's own chat history is now done (see above —
  `docs/phase8b-consent-and-data-rights.md`), but ENCRYPTION at rest for
  chat history and the audit trail's free-text fields is still not
  addressed (both still store real patient text unencrypted — see
  `docs/phase4c-chat-history.md`)
- Proactive/before-expiry token refresh (current auto-refresh is reactive
  — only kicks in when a stale token actually gets a 401), an
  httpOnly-cookie session instead of localStorage. Per-provider record
  scoping and a first pass of multi-tenancy are now done (see
  `docs/phase7a-patient-panels.md` and `docs/phase8a-organizations.md`)
  — this remaining item is frontend session-handling polish, not scoping
- API key / client-credential auth for non-browser API consumers, and
  `/v1/`-prefixed URL versioning (deliberately deferred — see
  `docs/phase5d-api-hardening.md` for the trigger conditions for adding
  each)
- Log aggregation destination beyond stdout; both Dockerfiles are
  unverified in this sandbox (no Docker available here — see
  `docs/phase5c-observability-ci.md` for what was and wasn't verified)
- Phase 01 (Production Foundations) itself is now complete — Postgres/
  Alembic, Redis-backed token tracking, observability/CI, and API
  hardening are all done, tested, and documented (see the four
  `docs/phase5*.md` files)

## Running the backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # run the test suite (SQLite + fakeredis, zero setup)
uvicorn app.main:app --reload --port 8000   # runs Alembic migrations on startup
```

To run against Postgres + Redis instead of the SQLite/fakeredis defaults:

```bash
docker-compose up -d              # from the repo root — starts local Postgres + Redis
export DATABASE_URL=postgresql+psycopg://triage:triage@localhost:5432/triage
export REDIS_URL=redis://localhost:6379/0
python scripts/migrate.py         # or just start uvicorn — it migrates on boot too
uvicorn app.main:app --reload --port 8000

# run the test suite against real Postgres + Redis instead of the defaults:
DATABASE_URL=postgresql+psycopg://triage:triage@localhost:5432/triage \
  REDIS_URL=redis://localhost:6379/0 python -m pytest -q
```

Try it (emergency — bypasses RAG, returns instantly):

```bash
curl -X POST http://127.0.0.1:8000/triage/evaluate \
  -H "Content-Type: application/json" \
  -d '{"symptom_ids": ["chest_pain", "shortness_of_breath"]}'
```

Try it (self-care — goes through retrieval + grounded generation):

```bash
curl -X POST http://127.0.0.1:8000/triage/evaluate \
  -H "Content-Type: application/json" \
  -d '{"symptom_ids": ["cough"], "severity": "mild", "onset": "sudden"}'
```

Try it (raw text — the chat-UI-facing path):

```bash
curl -X POST http://127.0.0.1:8000/triage/intake \
  -H "Content-Type: application/json" \
  -d '{"text": "I suddenly have severe chest pain and I am sweating"}'
```

To use real Anthropic-generated explanations instead of the extractive
fallback, set `ANTHROPIC_API_KEY` before starting the server.

Run the adversarial safety eval report on its own:

```bash
python scripts/run_eval.py
```

Check the audit trail (requires a provider/admin account — role assignment
is admin-controlled, so bootstrap one first):

```bash
# one-time: create the first admin account (prompts for a password)
python scripts/create_admin.py doc@example.com

ADMIN_TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "doc@example.com", "password": "<the password you set>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl "http://127.0.0.1:8000/audit/recent?limit=10" -H "Authorization: Bearer $ADMIN_TOKEN"
```

Note: the backend defaults to port 8000 in examples above, but if that
port is already in use locally, run it on any free port (e.g. `--port
8010`) and set `NEXT_PUBLIC_API_BASE_URL` accordingly for the frontend
(see below) — CORS is already configured for `http://localhost:3000`
regardless of which port the backend runs on.

## Running the frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000" > .env.local  # match your backend port
npm run dev
```

Open http://localhost:3000 — the backend must already be running (see
above), and the frontend must run on port 3000 specifically (`npm run dev`
with no `--port`), since the backend's CORS config only allows that exact
origin. Try "I have a mild cough" (self-care, grounded + cited) and "I
suddenly have severe chest pain and I'm sweating" (emergency fast path).

To try `/audit` or `/admin`: register at `/login` (always creates a
patient), then bootstrap an admin with `python scripts/create_admin.py
<email>` from `backend/`, log in as that admin, and use `/admin` to
promote your patient account to provider (or promote it to admin to see
`/admin` itself). Log out and back in after a promotion — a token keeps
its old role claim until it's refreshed.

## Running the end-to-end tests

```bash
cd frontend
npm install
npx playwright install chromium  # one-time browser download
npm run test:e2e
```

Genuinely zero-setup: this starts a real FastAPI backend (port 8020, to
avoid colliding with anything you might already have running on 8000)
and a real Next.js frontend as actual child processes, against a
throwaway SQLite DB and fakeredis — no manual backend/frontend startup
needed first. `npm run test:e2e:ui` opens Playwright's interactive UI
mode for debugging a specific spec. See
`docs/phase10a-e2e-test-suite.md`.

## Running the adversarial eval and load tests

```bash
cd backend
source .venv/bin/activate
python scripts/run_eval.py          # CLI report — also wired into pytest, see tests/test_adversarial_eval.py
```

Load tests need a real running server (not the test suite's fakes) —
start one on a free port, then run either script against it:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000   # a separate terminal

locust -f scripts/loadtest/locustfile_triage.py --host=http://127.0.0.1:8000 \
  --headless --users 20 --spawn-rate 10 --run-time 30s

locust -f scripts/loadtest/locustfile_auth_rate_limits.py --host=http://127.0.0.1:8000 \
  --headless --users 20 --spawn-rate 20 --run-time 20s
```

Omit `--headless`/`--users`/etc. and open http://localhost:8089 for
Locust's interactive web UI instead. See
`docs/phase10b-expanded-eval-and-load-testing.md` for what each script
actually verifies and why "some requests get a 429" is the *success*
case for the rate-limit script, not a failure.

## Project layout

```
symptom-triage-assistant/
├── backend/
│   ├── app/
│   │   ├── safety/       # deterministic red-flag engine +
│   │   │                 # guidance_translations.py (Spanish) (built out)
│   │   ├── intake/       # free-text -> SymptomInput extractor +
│   │   │                 # multi-turn conversation.py, both language-aware
│   │   │                 # (symptom_phrases.py's PHRASES_BY_LANGUAGE) (built out)
│   │   ├── rag/          # retrieval (TF-IDF default + dense/Qdrant opt-in)
│   │   │                 # + pluggable LLM generation (built out)
│   │   ├── eval/         # adversarial eval harness (built out)
│   │   ├── api/          # FastAPI routes (triage, audit, auth, admin,
│   │   │                 # kb_review, patient_panel, clinical_notes,
│   │   │                 # referrals, analytics, alerts, notifications,
│   │   │                 # organizations, consent, data_rights, retention,
│   │   │                 # symptom_photos, reports, deps)
│   │   ├── services/     # audit logging, token revocation (Redis), refresh tokens
│   │   │                 # (Redis), chat history, kb_review, patient_panel,
│   │   │                 # clinical_notes, referrals, analytics,
│   │   │                 # audit_visibility, alerting, notifications,
│   │   │                 # organizations, consent, data_rights,
│   │   │                 # admin_action_log, retention, symptom_photos,
│   │   │                 # reporting, report_delivery (built out)
│   │   ├── models/       # audit, user, chat_exchange, kb_review, patient_panel,
│   │   │                 # clinical_note, referral, alert, notification_preference,
│   │   │                 # organization, consent, data_request, admin_action_log,
│   │   │                 # retention_purge_run, symptom_photo, report_subscription
│   │   │                 # DB models (built out)
│   │   └── core/         # db, config, security/JWT, migrate.py, redis_client.py,
│   │                     # queue_client.py, logging_config.py, sentry.py, rate_limit.py,
│   │                     # request_limits.py (built out)
│   ├── migrations/               # Alembic migration history (built out)
│   ├── alembic.ini
│   ├── scripts/
│   │   ├── run_eval.py          # standalone adversarial eval CLI report
│   │   ├── create_admin.py      # bootstrap the first admin account
│   │   ├── migrate.py           # run migrations as an explicit deploy step
│   │   ├── kb_ingest.py         # KB coverage check + article ingestion (built out)
│   │   ├── run_retention_purge.py  # cron-triggered retention purge (built out)
│   │   ├── run_scheduled_reports.py  # cron-triggered report delivery (built out)
│   │   ├── loadtest/             # Locust scripts: triage + auth rate limits (built out)
│   │   └── drafts/              # KB article drafts consumed by kb_ingest.py
│   ├── Dockerfile                # multi-stage build (built out)
│   ├── .dockerignore
│   └── tests/
├── frontend/                        # Next.js app (built out)
│   ├── app/                         # pages: / (triage), /login, /audit, /admin,
│   │                                 # /analytics (built out)
│   ├── components/                  # TriageChat, TierBadge, NavBar,
│   │                                 # ServiceWorkerRegister, PhotoGallery,
│   │                                 # ReportSubscriptionPanel (built out)
│   ├── lib/                         # api.ts (backend client), auth.ts (localStorage),
│   │                                 # i18n.ts + useLanguage.ts (en/es, built out)
│   ├── public/                      # manifest.json, sw.js, offline.html,
│   │                                 # icons/ (built out)
│   ├── e2e/                         # Playwright specs + global-setup.ts +
│   │                                 # fixtures/ (built out)
│   ├── playwright.config.ts          # starts real backend+frontend (built out)
│   ├── next.config.js                # output: "standalone" (built out)
│   ├── Dockerfile                    # multi-stage build (built out)
│   └── .dockerignore
├── data/
│   ├── knowledge_base/articles/     # KB content (placeholder, 17 English +
│   │                                 # 11 Spanish translated articles)
│   ├── uploads/symptom_photos/      # patient-uploaded photos (gitignored,
│   │                                 # local disk storage — built out)
│   └── eval/adversarial_cases.json  # adversarial eval case set
├── .github/workflows/                # backend-ci.yml, frontend-ci.yml (built out)
├── docker-compose.yml                # local Postgres + Redis for dev
└── docs/
    ├── phase1-knowledge-base-and-rag.md
    ├── phase2-safety-engine.md
    ├── phase2-intake-layer.md
    ├── phase3-adversarial-eval.md
    ├── phase4a-audit-persistence.md
    ├── phase4b-auth-rbac.md
    ├── phase4c-chat-history.md
    ├── phase5-postgres-migration.md
    ├── phase5b-redis-token-tracking.md
    ├── phase5c-observability-ci.md
    ├── phase5d-api-hardening.md
    ├── phase6a-dense-retrieval.md
    ├── phase6b-knowledge-base-expansion.md
    ├── phase6c-multi-turn-triage.md
    ├── phase6d-semantic-groundedness.md
    ├── phase6e-clinical-review-workflow.md
    ├── phase7a-patient-panels.md
    ├── phase7b-clinical-notes.md
    ├── phase7c-referral-tracking.md
    ├── phase7d-provider-analytics.md
    ├── phase7e-high-risk-alerting.md
    ├── phase7f-notifications.md
    ├── phase8a-organizations.md
    ├── phase8b-consent-and-data-rights.md
    ├── phase8c-admin-action-audit-log.md
    ├── phase8d-retention-and-purge-jobs.md
    ├── phase9a-responsive-and-pwa.md
    ├── phase9b-internationalization.md
    ├── phase9c-symptom-photo-upload.md
    ├── phase9d-reporting-exports.md
    ├── phase10a-e2e-test-suite.md
    ├── phase10b-expanded-eval-and-load-testing.md
    └── phase10c-cross-phase-contract-tests.md
```

## Important: this is not a medical device

This project is scoped as an informational triage aid, not a diagnostic
tool. Any real deployment requires legal/compliance review (see the
roadmap's Phase 0 notes) before handling real patient data.
