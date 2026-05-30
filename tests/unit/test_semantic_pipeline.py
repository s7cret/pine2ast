from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.semantic.analyzer import SemanticAnalyzer
from pine2ast.semantic.pipeline import AnalyzerPassPipeline, PASS_PIPELINE, PassResult, SemanticPass
from pine2ast.semantic.passes import (
    BuiltinValidationPass,
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
    )
    pipeline = AnalyzerPassPipeline(ordered)

    assert pipeline.names == PASS_PIPELINE
