"""Redis connection for RQ (the job queue) — deliberately SEPARATE from
app/core/redis_client.py's singleton, not a reuse of it.

RQ pickles job payloads and expects raw bytes back from Redis; the
existing `redis_client` is constructed with `decode_responses=True`
(correct for token blocklist/rate-limit keys, which are always plain
strings) and would corrupt RQ's binary job data. Two connections, same
Redis server/REDIS_URL, different decode setting — not two Redis
instances.

Same real/fake duality as redis_client.py: REDIS_FAKE=1 (set by default
in tests/conftest.py) uses fakeredis instead of a real server — verified
directly that RQ's enqueue/dequeue/job-result round-trip works against
fakeredis in `is_async=False` (synchronous) mode, which is what tests
actually use (see app/services/alerting.py's ALERTING_SYNC). The real,
`is_async=True` queueing path was verified against a real, throwaway
Redis instance with an actual `rq worker` process — see
docs/phase7e-high-risk-alerting.md for how.
"""

from __future__ import annotations

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

if os.environ.get("REDIS_FAKE") == "1":
    import fakeredis

    queue_redis_client = fakeredis.FakeStrictRedis()
else:
    import redis

    queue_redis_client = redis.Redis.from_url(REDIS_URL)
