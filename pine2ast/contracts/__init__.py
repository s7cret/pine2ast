"""Public contract validation helpers for Pine2AST integration payloads.

Exports are resolved lazily so ``python -m pine2ast.contracts.validation`` can run
without importing the target module during package initialization.
"""

from __future__ import annotations

__all__ = [
    "ContractIssue",
    "ContractValidationReport",
    "validate_contract_payload",
    "contract_check_file_payload",
    "contract_check_json",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    from pine2ast.contracts import validation

    return getattr(validation, name)
