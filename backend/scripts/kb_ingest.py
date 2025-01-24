#!/usr/bin/env python
"""Knowledge-base ingestion CLI.

Run from backend/:

    python scripts/kb_ingest.py check-coverage
    python scripts/kb_ingest.py add drafts/my_article.txt

`check-coverage` cross-references app/safety/rules.yaml's symptom_ids
against every KB article's `tags` and reports which symptom_ids fall
through to bare rule guidance with no citation — the gap this epic exists
to close (see docs/phase6b-knowledge-base-expansion.md).

`add` ingests a draft article from a simple frontmatter+body text file
(see drafts/ for the format) and writes a validated JSON article into
data/knowledge_base/articles/, stamping provenance automatically:
`reviewed: false` (there is no reviewer queue yet — see
docs/phase6b-knowledge-base-expansion.md's "what's still open"),
`source_type: "placeholder"`, and `added_date` (today, UTC).

Draft file format — key: value frontmatter lines, a blank line, then body
paragraphs separated by blank lines:

    id: example_symptom
    title: Example Symptom: General Information
    tags: example_symptom, some_rule_id
    source_note: PLACEHOLDER CONTENT — ...

    First paragraph of the article body.

    Second paragraph.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.knowledge_base import _DEFAULT_KB_DIR, load_chunks, write_article_file  # noqa: E402
from app.safety.engine import load_rules  # noqa: E402


def _all_rule_symptom_ids() -> set[str]:
    symptom_ids: set[str] = set()
    for rule in load_rules():
        symptom_ids.update(rule.any_of)
        symptom_ids.update(rule.all_of)
    return symptom_ids


def _all_kb_tags(kb_dir: Path = _DEFAULT_KB_DIR) -> set[str]:
    return {tag for chunk in load_chunks(kb_dir) for tag in chunk.tags}


def check_coverage() -> int:
    uncovered = sorted(_all_rule_symptom_ids() - _all_kb_tags())
    if not uncovered:
        print("Every symptom_id in rules.yaml has at least one citing KB article.")
        return 0

    print(f"{len(uncovered)} symptom_id(s) in rules.yaml have no citing KB article:")
    for symptom_id in uncovered:
        print(f"  - {symptom_id}")
    return 1


def _parse_draft(path: Path) -> dict:
    raw = path.read_text().strip("\n")
    frontmatter_block, _, body_block = raw.partition("\n\n")

    fields: dict[str, str] = {}
    for line in frontmatter_block.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    required = {"id", "title", "tags", "source_note"}
    missing = required - fields.keys()
    if missing:
        raise ValueError(f"Draft {path} is missing required field(s): {sorted(missing)}")

    body = [p.strip() for p in body_block.split("\n\n") if p.strip()]
    if not body:
        raise ValueError(f"Draft {path} has no body paragraphs")

    return {
        "id": fields["id"],
        "title": fields["title"],
        "tags": [t.strip() for t in fields["tags"].split(",") if t.strip()],
        "source_note": fields["source_note"],
        "body": body,
    }


def add_article(draft_path: Path, kb_dir: Path = _DEFAULT_KB_DIR) -> Path:
    article = _parse_draft(draft_path)
    out_path = kb_dir / f"{article['id']}.json"
    if out_path.exists():
        raise FileExistsError(f"{out_path} already exists — article id must be unique")

    article["reviewed"] = False
    article["source_type"] = "placeholder"
    article["added_date"] = datetime.now(UTC).date().isoformat()

    return write_article_file(article, kb_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-coverage")
    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("draft", type=Path)

    args = parser.parse_args()

    if args.command == "check-coverage":
        return check_coverage()

    out_path = add_article(args.draft)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
