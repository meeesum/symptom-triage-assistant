"""Knowledge base loading and chunking.

Articles live as JSON files in data/knowledge_base/articles/ — one file per
topic, each with a body split into paragraph-level chunks already (source
authors control chunk boundaries rather than an automatic splitter, since
medical content reads better chunked at natural paragraph breaks than at
arbitrary token windows).

Every chunk carries provenance (article id, title, source_note, plus
reviewed/added_date/source_type — see below) so any answer built from it
can cite where it came from — required for the groundedness story, not
optional metadata.

Provenance fields (`reviewed`, `added_date`, `source_type`) default to
`False` / `null` / `"placeholder"` when absent so the original six
articles (authored before these fields existed) still load without a
migration step. `reviewed` is always `False` today — there is no reviewer
queue yet to have approved anything (see scripts/kb_ingest.py and
docs/phase6b-knowledge-base-expansion.md); it exists now so the field is
already in place for the clinical review workflow epic to populate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_KB_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge_base" / "articles"


@dataclass(frozen=True)
class Chunk:
    text: str
    article_id: str
    title: str
    source_note: str
    tags: tuple[str, ...]
    reviewed: bool = False
    added_date: str | None = None
    source_type: str = "placeholder"
    # Absent on the original (pre-i18n) English articles — defaults to
    # "en" so every existing article keeps loading/matching unchanged.
    # See docs/phase9b-internationalization.md: only a safety-prioritized
    # subset of articles has a Spanish sibling file today.
    language: str = "en"


def load_chunks(kb_dir: Path = _DEFAULT_KB_DIR, language: str | None = None) -> list[Chunk]:
    """Load KB chunks, optionally filtered to one `language`.

    `language=None` (the default) loads every article regardless of
    language, matching pre-i18n behavior exactly for existing callers.
    """
    if not kb_dir.exists():
        raise FileNotFoundError(
            f"Knowledge base directory not found: {kb_dir}. "
            "Expected data/knowledge_base/articles/*.json"
        )

    chunks: list[Chunk] = []
    for path in sorted(kb_dir.glob("*.json")):
        with open(path) as f:
            article = json.load(f)

        article_language = article.get("language", "en")
        if language is not None and article_language != language:
            continue

        for paragraph in article["body"]:
            chunks.append(
                Chunk(
                    text=paragraph,
                    article_id=article["id"],
                    title=article["title"],
                    source_note=article["source_note"],
                    tags=tuple(article.get("tags", [])),
                    reviewed=article.get("reviewed", False),
                    added_date=article.get("added_date"),
                    source_type=article.get("source_type", "placeholder"),
                    language=article_language,
                )
            )

    if not chunks:
        raise ValueError(
            f"No article chunks loaded from {kb_dir} for language={language!r} — "
            "knowledge base is empty for this filter."
        )

    return chunks


def write_article_file(article: dict, kb_dir: Path = _DEFAULT_KB_DIR) -> Path:
    """Write one article dict as a KB article JSON file (create or
    overwrite). The article file format is owned here, not duplicated in
    its two callers: scripts/kb_ingest.py's CLI ingestion, and
    app/services/kb_review.py's approval flow (see
    docs/phase6e-clinical-review-workflow.md)."""
    kb_dir.mkdir(parents=True, exist_ok=True)
    out_path = kb_dir / f"{article['id']}.json"
    out_path.write_text(json.dumps(article, indent=2, ensure_ascii=False) + "\n")
    return out_path
