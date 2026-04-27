import json
from pathlib import Path

from pine2ast.cli import main
from pine2ast.corpus import validate_corpus


def test_validate_corpus_summary(tmp_path: Path):
    (tmp_path / "ok.pine").write_text(
        '//@version=6\nindicator("ok")\nplot(close)\n', encoding="utf-8"
    )
    (tmp_path / "bad.pine").write_text('//@version=6\nindicator("bad")\nx := 1\n', encoding="utf-8")
    summary = validate_corpus(tmp_path)
    assert summary["file_count"] == 2
    assert summary["ok_count"] == 1
    assert summary["error_count"] >= 1


def test_validate_corpus_cli_json(tmp_path: Path):
    src = tmp_path / "ok.pine"
    out = tmp_path / "corpus.json"
    src.write_text('//@version=6\nindicator("ok")\nplot(close)\n', encoding="utf-8")
    assert main(["validate-corpus", str(tmp_path), "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    assert payload["ok_count"] == 1
