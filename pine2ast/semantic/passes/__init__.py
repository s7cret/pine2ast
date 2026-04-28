"""Named semantic pass boundaries for the Pine2AST frontend contract.

The analyzer still owns shared state for diagnostic stability, but public pass
classes make the phase order explicit and give future work safe extraction seams.
"""

from pine2ast.semantic.passes.builtin_validation import BuiltinValidationPass
from pine2ast.semantic.passes.declaration_index import DeclarationIndexPass
from pine2ast.semantic.passes.qualifier_inference import QualifierInferencePass
from pine2ast.semantic.passes.scope_symbols import ScopeSymbolPass
from pine2ast.semantic.passes.strategy_context import StrategyContextValidationPass
from pine2ast.semantic.passes.type_inference import TypeInferencePass
from pine2ast.semantic.passes.unsupported_features import UnsupportedFeatureExtractionPass

PASS_PIPELINE = (
    "declaration_index",
    "scope_symbols",
    "type_inference",
    "qualifier_inference",
    "builtin_validation",
    "strategy_context_validation",
    "unsupported_feature_extraction",
)

__all__ = [
    "BuiltinValidationPass",
    "DeclarationIndexPass",
    "PASS_PIPELINE",
    "QualifierInferencePass",
    "ScopeSymbolPass",
    "StrategyContextValidationPass",
    "TypeInferencePass",
    "UnsupportedFeatureExtractionPass",
]
