from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

from pine2ast.api import ParseOptions, parse_code
from pine2ast.ast.nodes import (
    Argument,
    BinaryExpr,
    CallExpr,
    ConditionalExpr,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    Literal,
    MemberAccessExpr,
    TupleExpr,
)
from pine2ast.ast.types import TypeRef
from pine2ast.cli import main
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics.sarif import diagnostics_to_sarif, diagnostics_to_sarif_json, write_sarif
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.extractors import extract_dependencies, extract_inputs
from pine2ast.semantic.qualifier_infer import infer_qualifier
from pine2ast.semantic.type_infer import infer_type
from pine2ast.semantic.validators import FORBIDDEN_IN_LOCAL_BLOCKS
from pine2ast.source.source_map import SourceMap

S = SourceSpan.zero()


def lit(value, typ):
    return Literal(S, value, typ)


def ident(name: str) -> Identifier:
    return Identifier(S, name)


def arg(value, name: str | None = None) -> Argument:
    return Argument(S, name, value)


def call(name: str, *args: Argument) -> CallExpr:
    callee = ident(name)
    for part in name.split(".")[1:]:
        # Rebuild dotted names into MemberAccessExpr so callee_name follows normal parser shape.
        pass
    if "." in name:
        root, *members = name.split(".")
        expr = ident(root)
        for member in members:
            expr = MemberAccessExpr(S, expr, member)
        callee = expr
    return CallExpr(S, callee, list(args))


def test_sarif_formatter_maps_levels_regions_hints_and_file_output(tmp_path: Path) -> None:
    diagnostic = Diagnostic(
        code="P2A9999",
        message="example",
        severity=Severity.WARNING,
        span=SourceSpan(0, 1, 2, 3, 2, 3),
        hint="fix it",
        doc_url="https://example.invalid/p2a9999",
    )

    payload = diagnostics_to_sarif([diagnostic], source_name="script.pine", tool_version="0.test")
    run = payload["runs"][0]
    assert run["tool"]["driver"]["semanticVersion"] == "0.test"
    assert run["tool"]["driver"]["rules"][0]["helpUri"].endswith("p2a9999")
    result = run["results"][0]
    assert result["level"] == "warning"
    assert result["properties"] == {"hint": "fix it"}
    assert result["locations"][0]["physicalLocation"]["region"]["endColumn"] == 4

    text = diagnostics_to_sarif_json([diagnostic], indent=0)
    assert json.loads(text)["version"] == "2.1.0"
    out = tmp_path / "out.sarif"
    write_sarif(out, [diagnostic], source_name="script.pine")
    assert json.loads(out.read_text(encoding="utf-8"))["runs"][0]["results"]


def test_source_map_and_validator_surface_are_importable_runtime_contracts() -> None:
    assert SourceMap().source_name == "<memory>"
    assert SourceMap("a.pine").source_name == "a.pine"
    assert {"plot", "strategy", "alertcondition"} <= FORBIDDEN_IN_LOCAL_BLOCKS


def test_cli_happy_and_error_paths_cover_reports_sarif_tokens_and_quality(tmp_path: Path) -> None:
    src = tmp_path / "script.pine"
    src.write_text(
        '//@version=6\nindicator("cli")\nlen = input.int(14, "Length", minval=1, maxval=50, step=1)\nplot(close)\n',
        encoding="utf-8",
    )

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert main(["tokens", str(src)]) == 0
    assert "IDENTIFIER" in stdout.getvalue()

    for cmd, key in [
        ("inspect", "inputs"),
        ("schema-check", "schema"),
        ("diagnostics-report", "summary"),
        ("semantic-report", "semantic"),
        ("sarif", "runs"),
        ("quality-gate", "ok"),
    ]:
        out = tmp_path / f"{cmd}.json"
        assert main([cmd, str(src), "--json", str(out)]) == 0
        assert key in json.loads(out.read_text(encoding="utf-8"))

    bad = tmp_path / "bad.pine"
    bad.write_text('//@version=6\nindicator("bad")\nplot(close\n', encoding="utf-8")
    bad_out = tmp_path / "bad.json"
    code = main(["parse", str(bad), "--json", str(bad_out)])
    assert code in {0, 1, 2}
    assert bad_out.exists()

    invalid = tmp_path / "invalid.pine"
    invalid.write_text('//@version=6\nindicator("invalid")\nbool b = na\n', encoding="utf-8")
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert main(["validate", str(invalid)]) == 1
    assert "P2A1203" in stdout.getvalue()

    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    current.write_text(
        json.dumps({"summary": {"total": 1, "by_code": {"P2A1": 1}}}), encoding="utf-8"
    )
    baseline.write_text(json.dumps({"summary": {"total": 0, "by_code": {}}}), encoding="utf-8")
    assert main(["diagnostics-diff", str(current), str(baseline)]) == 1


def test_extractors_cover_input_options_dependencies_and_external_calls() -> None:
    source = """//@version=6
indicator("E")
import user/lib/1 as ext

 type Dummy
    int x

f(x) => x
method get(Dummy this) => this.x
choice = input.string("a", "Choice", options = array.from("a", "b"))
d = Dummy.new(1)
y = d.get()
z = ext.remote(close)
plot(f(close))
""".replace("\n type", "\ntype")
    result = parse_code(source, ParseOptions(run_semantic=True))
    assert result.ast is not None

    inputs = extract_inputs(result.ast, result.semantic_model)
    assert inputs[0].name == "choice"
    assert inputs[0].options == ["a", "b"]

    deps = extract_dependencies(result.ast, result.semantic_model)
    assert deps.imports == ["user/lib/1"]
    assert "ext.remote" in deps.external_calls
    assert "f" in deps.user_function_calls
    assert "get" in deps.method_calls
    assert "Dummy" in deps.udt_constructors


def test_type_and_qualifier_edges_without_schema_changes() -> None:
    symbols = {
        "Point": SimpleNamespace(kind="TYPE", type="type"),
        "p": SimpleNamespace(kind="VARIABLE", type="Point", qualifier="simple"),
        "Point.x": SimpleNamespace(kind="FIELD", type="float", qualifier="simple"),
        "arr": SimpleNamespace(kind="VARIABLE", type="array<int>", qualifier="series"),
        "m": SimpleNamespace(kind="VARIABLE", type="map<string,float>", qualifier="series"),
        "fun": SimpleNamespace(kind="FUNCTION", type="bool", qualifier="simple"),
    }

    assert infer_type(MemberAccessExpr(S, ident("p"), "x"), symbols) == "float"
    assert infer_type(call("Point.new"), symbols) == "Point"
    assert infer_type(call("array.get", arg(ident("arr")), arg(lit(0, "int"))), symbols) == "int"
    assert infer_type(call("map.get", arg(ident("m")), arg(lit("k", "string"))), symbols) == "float"
    assert (
        infer_type(call("array.from", arg(lit(1, "int")), arg(lit(2.0, "float"))), symbols)
        == "array<float>"
    )
    assert (
        infer_type(
            call(
                "request.security",
                arg(lit("AAPL", "string")),
                arg(lit("D", "string")),
                arg(TupleExpr(S, [lit(1, "int"), lit(2.0, "float")])),
            ),
            symbols,
        )
        == "tuple<int,float>"
    )
    assert infer_type(call("fun"), symbols) == "bool"

    generic = GenericInstantiationExpr(
        S, MemberAccessExpr(S, ident("array"), "new"), [TypeRef("float")]
    )
    assert infer_type(CallExpr(S, generic, []), symbols) == "array<float>"

    expr = ConditionalExpr(
        S,
        ident("p"),
        BinaryExpr(S, "+", lit(1, "int"), lit(2.0, "float")),
        HistoryRefExpr(S, ident("arr"), lit(1, "int")),
    )
    assert infer_qualifier(expr, symbols) == "series"
    assert infer_qualifier(call("input.int", arg(lit(14, "int")))) == "input"
