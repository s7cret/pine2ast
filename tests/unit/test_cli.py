import contextlib
import io
from pathlib import Path
from pine2ast.cli import main


def test_cli_parse_json(tmp_path: Path):
    f = tmp_path / "a.pine"
    out = tmp_path / "a.json"
    f.write_text('//@version=6\nindicator("x")\nplot(close)\n', encoding="utf-8")
    assert main(["parse", str(f), "--json", str(out), "--no-semantic"]) == 0
    assert out.exists()


def test_cli_bench_json(tmp_path: Path):
    f = tmp_path / "a.pine"
    out = tmp_path / "bench.json"
    f.write_text('//@version=6\nindicator("x")\nplot(close)\n', encoding="utf-8")
    assert main(["bench", str(tmp_path), "--repeat", "1", "--json", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert '"schema_version": 1' in text
    assert '"normalizer_ms"' in text
    assert '"ast_node_count"' in text


def test_cli_golden_and_symbols_json(tmp_path):
    from pine2ast.cli import main

    src = tmp_path / "script.pine"
    src.write_text(
        """//@version=6
indicator("cli")
plot(close)
""",
        encoding="utf-8",
    )
    ast = tmp_path / "script.ast.json"
    diag = tmp_path / "script.diag.json"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert (
            main(
                [
                    "golden",
                    str(src),
                    "--ast",
                    str(ast),
                    "--diagnostics",
                    str(diag),
                    "--ignore-spans",
                ]
            )
            == 0
        )
        assert ast.exists()
        assert diag.exists()
        assert main(["golden", str(src), "--ast", str(ast), "--ignore-spans", "--compare"]) == 0
        assert main(["dump-symbols", str(src), "--json"]) == 0
