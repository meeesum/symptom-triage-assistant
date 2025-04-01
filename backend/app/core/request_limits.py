"""Request body size cap — defense in depth, not the primary defense.

A real deployment would also cap this at the reverse proxy/load balancer
(nginx's client_max_body_size, or equivalent), which is a better place for
it (rejects oversized requests before they consume an app worker's memory
and Python's own request-parsing time at all). This middleware exists so
the limit still holds when running the app directly (dev, or a deployment
without a proxy in front yet) rather than being silently unenforced.

Checks Content-Length up front (fast, no body read) when the header is
present; a request that lies about its length or omits it is bounded by
Starlette/uvicorn's own defaults, not by this middleware specifically —
this is one layer, not the whole story.

A file-upload endpoint DID land (POST /audit/{id}/photos — see
app/api/symptom_photos.py), and it needs a larger cap than a JSON API
body ever should. Rather than raising MAX_BODY_BYTES globally (which
would let every JSON endpoint accept up to 5 MiB of body for no reason),
photo-upload paths are exempted from THIS blanket check and instead
enforce their own cap in `_read_capped()` — a streamed, chunk-by-chunk
read that never trusts Content-Length either, so the safety property
this middleware exists for (never buffer an unbounded body) is preserved
at the endpoint, just with a purpose-sized limit instead of the generic
JSON one.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 1 MiB — generous for JSON API bodies here. NOT applied to photo-upload
# paths (see MAX_PHOTO_BYTES in app/core/config.py / _EXEMPT_PATH_SUFFIX
# below) — those enforce their own, larger, streamed cap instead.
MAX_BODY_BYTES = 1 * 1024 * 1024

_EXEMPT_PATH_SUFFIX = "/photos"


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path.endswith(_EXEMPT_PATH_SUFFIX):
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"request body exceeds {MAX_BODY_BYTES} byte limit"},
                    )
            except ValueError:
                pass  # malformed header — let downstream parsing reject it instead of guessing here
        return await call_next(request)
