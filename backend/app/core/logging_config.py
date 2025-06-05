"""Structured logging setup — third epic of the scale-up plan's Phase 01
(Production Foundations).

Wraps stdlib `logging` with structlog rather than replacing every call
site: the codebase has exactly one existing `logging.getLogger(...)` user
(app/services/audit_log.py), and any future code that reaches for
stdlib `logging` (the obvious default) gets the same structured output
for free — no need to remember to import structlog specifically.

Two render modes:
  - LOG_FORMAT=json (default when ENVIRONMENT=production): one JSON object
    per line, the format a real log aggregator (Datadog, CloudWatch, etc.)
    actually wants.
  - LOG_FORMAT=console (default otherwise): structlog's human-readable
    colored console renderer, for local dev.

Called once from app/main.py before the app object is constructed, not
inside the lifespan — logging should be configured before the first log
line is emitted, including ones from imports.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging() -> None:
    log_format = os.environ.get(
        "LOG_FORMAT", "json" if os.environ.get("ENVIRONMENT") == "production" else "console"
    )
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # uvicorn's own loggers otherwise bypass this and print their own
    # unstructured lines — route them through the same handler/formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [handler]
        uv_logger.propagate = False
