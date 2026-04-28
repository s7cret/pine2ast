from __future__ import annotations

import json

from pine2ast.ast.nodes import Program


def ast_to_dict(ast: Program) -> dict:
    return ast.to_dict()


def ast_to_json(ast: Program, *, indent: int = 2) -> str:
    return json.dumps(ast_to_dict(ast), ensure_ascii=False, indent=indent)
