from pathlib import Path

import pytest

from scripts.kb_ingest import _all_kb_tags, _all_rule_symptom_ids, add_article, check_coverage


def test_check_coverage_passes_against_the_real_knowledge_base(capsys):
    # The real data/knowledge_base/articles/ is expected to cite every
    # symptom_id in rules.yaml — see docs/phase6b-knowledge-base-expansion.md.
    exit_code = check_coverage()
    assert exit_code == 0
    assert "Every symptom_id" in capsys.readouterr().out


def test_all_rule_symptom_ids_includes_known_ids():
    symptom_ids = _all_rule_symptom_ids()
    assert "chest_pain" in symptom_ids
    assert "headache" in symptom_ids


def test_all_kb_tags_includes_known_tags():
    assert "chest_pain" in _all_kb_tags()


def test_add_article_writes_valid_json(tmp_path: Path):
    draft = tmp_path / "draft.txt"
    draft.write_text(
        "id: test_symptom\n"
        "title: Test Symptom\n"
        "tags: test_symptom, some_rule\n"
        "source_note: PLACEHOLDER\n"
        "\n"
        "First paragraph.\n"
        "\n"
        "Second paragraph.\n"
    )
    kb_dir = tmp_path / "articles"

    out_path = add_article(draft, kb_dir=kb_dir)

    assert out_path == kb_dir / "test_symptom.json"
    import json

    article = json.loads(out_path.read_text())
    assert article["id"] == "test_symptom"
    assert article["tags"] == ["test_symptom", "some_rule"]
    assert article["body"] == ["First paragraph.", "Second paragraph."]
    assert article["reviewed"] is False
    assert article["source_type"] == "placeholder"
    assert article["added_date"]


def test_add_article_rejects_duplicate_id(tmp_path: Path):
    draft = tmp_path / "draft.txt"
    draft.write_text(
        "id: dup\ntitle: Dup\ntags: dup\nsource_note: PLACEHOLDER\n\nBody paragraph.\n"
    )
    kb_dir = tmp_path / "articles"
    add_article(draft, kb_dir=kb_dir)

    with pytest.raises(FileExistsError):
        add_article(draft, kb_dir=kb_dir)


def test_add_article_rejects_missing_required_field(tmp_path: Path):
    draft = tmp_path / "draft.txt"
    draft.write_text("id: incomplete\ntitle: Incomplete\n\nBody paragraph.\n")

    with pytest.raises(ValueError, match="missing required field"):
        add_article(draft, kb_dir=tmp_path / "articles")


def test_add_article_rejects_empty_body(tmp_path: Path):
    draft = tmp_path / "draft.txt"
    draft.write_text(
        "id: empty_body\ntitle: Empty\ntags: x\nsource_note: PLACEHOLDER\n\n"
    )

    with pytest.raises(ValueError, match="no body paragraphs"):
        add_article(draft, kb_dir=tmp_path / "articles")
