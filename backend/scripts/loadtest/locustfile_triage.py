"""Load test: concurrent triage requests against the real pipeline.

Targets exactly what the roadmap's "Expanded adversarial eval + load
testing" epic names — the job-queue layer (app/services/alerting.py)
under real concurrent load, via the only path that actually exercises it
end to end: submitting enough emergency-tier triages fast enough to
prove the alert enqueue (a fast, inline DB insert + Redis push — see
trigger_high_risk_alert()'s docstring) doesn't become a request-latency
bottleneck as volume grows. Self-care/routine messages are mixed in at a
much higher weight than emergency ones (see SELF_CARE_WEIGHT/
EMERGENCY_WEIGHT below) — deliberately: real patient traffic is
overwhelmingly non-emergency, and self-care/routine is also the
HEAVIER path per request (it's the one that hits the RAG pipeline —
TF-IDF retrieval + the extractive/LLM client — not just the safety
engine's fast path), so this mix is what actually stresses the pipeline
realistically rather than only ever taking the cheap fast-path branch.

Deliberately anonymous (no auth) — this exercises the exact path real
unauthenticated patient traffic takes (see app/api/triage.py: /triage/
intake never requires login) and keeps this locustfile independent of
locustfile_auth_rate_limits.py, which owns hammering the auth endpoints
specifically. Running both files against the same target at once would
conflate two different things being measured.

Usage (from backend/, against a real running server — see
docs/phase10b-expanded-eval-and-load-testing.md for what env vars that
server needs and why, e.g. ALERTING_SYNC unset so the job queue is
actually exercised for real):

    locust -f scripts/loadtest/locustfile_triage.py --host=http://127.0.0.1:8000

Then open http://localhost:8089 to configure user count/spawn rate and
watch live throughput/latency, or run headless:

    locust -f scripts/loadtest/locustfile_triage.py --host=http://127.0.0.1:8000 \\
        --headless --users 50 --spawn-rate 10 --run-time 2m
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task

SELF_CARE_MESSAGES = [
    "I have a mild cough that started suddenly",
    "a mild rash on my arm that's been going on for a few days",
    "I have a mild sore throat and runny nose",
    "slight headache since this morning, mild",
    "mild joint pain in my knee, started gradually",
]

EMERGENCY_MESSAGES = [
    "sudden severe chest pain and I'm sweating a lot",
    "my face is suddenly drooping on one side and my speech is slurred",
    "I've been thinking about suicide and want to hurt myself",
    "severe difficulty breathing, can't speak in full sentences",
    "uncontrolled bleeding that won't stop with pressure",
]

# Roughly matches real-world triage volume shape: most traffic is
# non-emergency. Also, deliberately, the HEAVIER (RAG-pipeline) path —
# see this module's docstring for why that's the realistic stress case,
# not just "make emergency common because it's interesting."
SELF_CARE_WEIGHT = 5
EMERGENCY_WEIGHT = 1


class TriagePatient(HttpUser):
    # 1-3s between a patient's messages — approximates real typing/
    # reading pace rather than a tight request-per-request hammer, which
    # would test something closer to a DoS scenario than realistic load.
    wait_time = between(1, 3)

    @task(SELF_CARE_WEIGHT)
    def submit_self_care(self):
        text = random.choice(SELF_CARE_MESSAGES)
        with self.client.post(
            "/triage/intake",
            json={"text": text},
            name="/triage/intake [self_care]",
            catch_response=True,
        ) as resp:
            self._validate_triage_response(resp)

    @task(EMERGENCY_WEIGHT)
    def submit_emergency(self):
        text = random.choice(EMERGENCY_MESSAGES)
        with self.client.post(
            "/triage/intake",
            json={"text": text},
            name="/triage/intake [emergency]",
            catch_response=True,
        ) as resp:
            self._validate_triage_response(resp, expect_tier="emergency")

    def _validate_triage_response(self, resp, expect_tier: str | None = None):
        if resp.status_code != 200:
            resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")
            return
        body = resp.json()
        if expect_tier is not None and body.get("tier") != expect_tier:
            # A real correctness regression under load, not just a
            # latency/availability problem — e.g. the safety engine
            # returning a stale or wrong result under concurrent DB
            # writes would be exactly this kind of failure.
            resp.failure(f"expected tier={expect_tier!r}, got {body.get('tier')!r}")
            return
        resp.success()
