from .analyzer import SemanticAnalyzer, SemanticModel
from pine2ast.catalog import load_catalog_view
from .extractors import (
    InputParameter,
    StrategyCall,
    extract_inputs,
    extract_plots,
    extract_request_calls,
    extract_strategy_calls,
)
from .reports import SemanticReport, semantic_report
from .completeness import StaticCompletenessReport, pinned_catalog_static_completeness
from .scopes import Scope, ScopeKind
from .symbols import Symbol, SymbolKind

__all__ = [
    "SemanticAnalyzer",
    "SemanticModel",
    "load_catalog_view",
    "Symbol",
    "SymbolKind",
    "Scope",
    "ScopeKind",
    "InputParameter",
    "StrategyCall",
    "extract_inputs",
    "extract_plots",
    "extract_request_calls",
    "extract_strategy_calls",
    "SemanticReport",
    "semantic_report",
    "StaticCompletenessReport",
    "pinned_catalog_static_completeness",
]

from pine2ast.semantic.version_coverage import build_version_coverage_report
from pine2ast.semantic.version_semantics import (
    SemanticRequirement,
    apply_version_semantics,
    load_semantic_requirements,
    requirements_for_version,
    requirements_hash,
)

__all__ = list(globals().get("__all__", ())) + [
    "SemanticRequirement",
    "apply_version_semantics",
    "build_version_coverage_report",
    "load_semantic_requirements",
    "requirements_for_version",
    "requirements_hash",
]
from pine2ast.semantic.version_coverage import (
    validate_version_coverage_report as validate_version_coverage_report,
)

if "validate_version_coverage_report" not in __all__:
    __all__.append("validate_version_coverage_report")
