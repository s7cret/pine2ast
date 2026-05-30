from __future__ import annotations

import pytest

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.semantic.analyzer import SemanticAnalyzer
from pine2ast.semantic.pipeline import AnalyzerPassPipeline, PASS_PIPELINE, PassResult, SemanticPass
from pine2ast.semantic.passes import (
    BuiltinValidationPass,
    DeclarationCardinalityPass,
    DeclarationIndexPass,
    QualifierInferencePass,
    ScopeSymbolPass,
    StrategyContextValidationPass,
    TypeInferencePass,
    UnsupportedFeatureExtractionPass,
)


def test_semantic_analyzer_runs_ordered_pass_pipeline() -> None:
    parsed = parse_code(
        '//@version=6\nindicator("x")\na = close\n',
        ParseOptions(run_semantic=False),
    )
    assert parsed.ast is not None

    analyzer = SemanticAnalyzer()
    analyzer.analyze(parsed.ast)

    assert tuple(result.name for result in analyzer.pass_results) == PASS_PIPELINE
    assert all(isinstance(result, PassResult) for result in analyzer.pass_results)


def test_analyzer_pass_pipeline_rejects_unexpected_order() -> None:
    parsed = parse_code(
        '//@version=6\nindicator("x")\na = close\n',
        ParseOptions(run_semantic=False),
    )
    assert parsed.ast is not None
    analyzer = SemanticAnalyzer()
    ordered: tuple[SemanticPass, ...] = (
        DeclarationIndexPass(analyzer),
        ScopeSymbolPass(analyzer),
        TypeInferencePass(analyzer),
        QualifierInferencePass(analyzer),
        BuiltinValidationPass(analyzer),
        StrategyContextValidationPass(analyzer),
        UnsupportedFeatureExtractionPass(analyzer),
        DeclarationCardinalityPass(analyzer),
    )
    pipeline = AnalyzerPassPipeline(ordered)

    assert pipeline.names == PASS_PIPELINE

    with pytest.raises(ValueError, match="Unexpected semantic pass pipeline order"):
        AnalyzerPassPipeline(ordered[:-1])


def test_declaration_cardinality_runs_as_terminal_semantic_pass() -> None:
    parsed = parse_code(
        '//@version=6\nindicator("x")\nif close > open\n    indicator("nested")\n',
        ParseOptions(run_semantic=False),
    )
    assert parsed.ast is not None

    analyzer = SemanticAnalyzer()
    model = analyzer.analyze(parsed.ast)

    assert any(diag.code == codes.MULTIPLE_DECLARATIONS for diag in model.diagnostics)
    cardinality_result = analyzer.pass_results[-1]
    assert cardinality_result.name == "declaration_cardinality"
    assert cardinality_result.diagnostics_after == cardinality_result.diagnostics_before + 1
