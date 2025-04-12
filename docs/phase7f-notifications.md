# Phase 7f deep-dive: notifications

Sixth and final epic of the scale-up roadmap's Phase 03 (Provider &
Care-Team Platform), depending directly on
`docs/phase7e-high-risk-alerting.md` — this is what actually plugs
delivery into the job queue that epic built. **With this, Phase 03 is
complete.**

## What's built

- `app/services/notifications.py` — same pluggable pattern as
  `app/rag/llm_client.py`'s `LLMClient`: a zero-setup default
  (`ConsoleNotificationClient`, logs instead of sending) plus real
  backends that activate only when configured.
  - `SmtpEmailClient` — real email via stdlib `smtplib` +
    `email.message`. No third-party email SDK; SMTP needs nothing more
    than what the standard library provides.
  - `TwilioSmsClient` — real SMS via Twilio's REST API, called directly
    with stdlib `urllib.request` (HTTP Basic Auth, form-encoded POST)
    rather than pulling in the `twilio` SDK for what is, at this call
    volume, a single API call. Same "don't add a dependency for what
    stdlib already covers" judgment as the email client.
- `app/models/notification_preference.py` + `app/api/notifications.py`
  (`GET`/`PUT /notifications/preferences`) — **self-service**, a real
  departure from the rest of Phase 03. Patient panels, clinical notes,
  and referral tracking are all admin-controlled or provider-actioned
  because they're assignments or clinical actions; which channel a
  person wants their own alerts on is a personal preference, so the
  current user manages it directly rather than needing an admin.
- `app/services/alerting.py`'s `process_alert()` now calls
  `notify_user()` after resolving a recipient — the actual connection the
  roadmap asked for between the two epics.

## Two real bugs caught by live testing, not just unit tests

1. **`SmtpEmailClient` unconditionally called `smtp.starttls()`.**
   Verified against a real local debug SMTP server (`aiosmtpd`) — it
   doesn't advertise STARTTLS support, and the unconditional call failed
   outright with `SMTPNotSupportedError`. Real production relays on port
   587 (Gmail, SendGrid) DO require STARTTLS, so the failure wasn't in
   the default — it was in having no way to turn it off for a server
   that doesn't support it (a local dev server, or an internal relay on
   plain port 25). Fixed with `SMTP_USE_TLS` (default `"1"`, matching the
   common real-relay case).
2. Re-verified after the fix: the same debug server accepted the message
   cleanly (`send()` returned `True`, no exception) — a real, complete
   SMTP conversation, not a mocked one.

Also verified the Twilio path's request construction is genuinely
correct, not just "doesn't crash": called `TwilioSmsClient.send()` with
syntactically-valid-but-fake credentials against the REAL Twilio API
endpoint. It reached Twilio and got back a real `401 Unauthorized` —
proof the URL, Basic Auth header, and form-encoded body are all built
correctly; the only thing missing is a real account, which this sandbox
doesn't have (same category of "unverified in this sandbox" as
`AnthropicLLMClient`'s real API calls).

## Design choices worth calling out

- **A notification failure never rolls back the alert's `sent` status.**
  The durable `Alert` record (queryable via `GET /alerts/recent`) is the
  thing that must not be lost; a failed email/SMS is a delivery-channel
  problem, logged loudly by `notify_user()` itself. Conflating "the alert
  happened" with "the notification succeeded" would make a flaky email
  provider capable of hiding that an emergency case was ever flagged.
- **`notify_user()` never raises.** Every client call is wrapped; a
  crash in a notification client can't propagate up into the job queue
  worker and fail the whole `process_alert()` job over something as
  replaceable as an email send.
- **Preferences default to email-on, SMS-off** for a user who never sets
  any — matches `NotificationPreference` not existing being a valid,
  common state (most users), not an error state requiring a row.

## What's still open

- **No verification that a phone number is actually valid** before
  accepting it via `PUT /notifications/preferences` — any string is
  stored as-is. A real deployment would want at least format validation
  before handing it to Twilio.
- **No notification history/audit trail** — `notify_user()`'s
  `dict[str, bool]` result isn't persisted anywhere; there's no way to
  later ask "did this provider actually get paged for this case," only
  whether the `Alert` itself reached `status: "sent"`. A
  `NotificationLog` table mirroring `ReferralStatusChange`'s
  append-only pattern would be the natural addition if this becomes a
  real operational need.
- **Only the FIRST panel-assigned provider gets notified** — inherited
  directly from `docs/phase7e-high-risk-alerting.md`'s own open item
  (no on-call rotation/priority concept). Multiple assigned providers
  currently means only one of them is ever paged.
- **No frontend UI** for managing preferences — backend-only pass, same
  scope decision as most of Phase 03's other epics.
