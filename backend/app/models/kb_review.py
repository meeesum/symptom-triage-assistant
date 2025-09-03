"""Clinical review queue for knowledge-base articles.

Closes the gap docs/phase6b-knowledge-base-expansion.md deliberately left
open: articles were ingestable via scripts/kb_ingest.py, but nothing
actually reviewed them before they went live — every article's `reviewed`
field stayed `false` forever. This table is the reviewer queue that
field always pointed toward.

One row per SUBMISSION, not per article — an article's full edit history
is just every row sharing its `article_id`, ordered by `version`. This is
the "version history" the roadmap epic asked for: nothing is overwritten,
a rejected submission stays in the table as a permanent record, and an
approved submission never retroactively changes what an earlier approved
version said (see app/services/kb_review.py for how `version` and
`status` are actually driven, since SQLite/Postgres portability rules out
a DB-level trigger for the increment-and-validate logic here).
"""

from __future__ import annotations

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

VALID_STATUSES = ("pending", "approved", "rejected")


class KbArticleSubmission(Base):
    __tablename__ = "kb_article_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    article_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source_note: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    submitted_by: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reviewed_by: Mapped[int] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(String, nullable=True)
