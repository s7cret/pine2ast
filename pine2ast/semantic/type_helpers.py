"""Pure semantic type-string helpers."""

from __future__ import annotations


def type_ref_name(type_ref) -> str:
    if type_ref is None:
        return "unknown"
    args = getattr(type_ref, "template_args", None) or []
    if not args:
        return type_ref.name
    return type_ref.name + "<" + ",".join(type_ref_name(arg) for arg in args) + ">"


def split_type_args(inner: str) -> list[str]:
    result: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(inner):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            result.append(inner[start:idx].strip() or "unknown")
            start = idx + 1
    tail = inner[start:].strip()
    if tail:
        result.append(tail)
    return result


def for_in_target_types(iterable_type: str, target_count: int) -> list[str]:
    if iterable_type.startswith("array<") and iterable_type.endswith(">"):
        element = iterable_type[len("array<") : -1].strip() or "unknown"
        return ["int", element] if target_count == 2 else [element]
    if iterable_type.startswith("matrix<") and iterable_type.endswith(">"):
        element = iterable_type[len("matrix<") : -1].strip() or "unknown"
        return ["int", element] if target_count == 2 else [element]
    if iterable_type.startswith("map<") and iterable_type.endswith(">"):
        parts = split_type_args(iterable_type[len("map<") : -1])
        if target_count == 2 and len(parts) >= 2:
            return [parts[0], parts[1]]
        return ["tuple<" + ",".join(parts[:2]) + ">" if parts else "unknown"]
    if iterable_type.startswith("tuple<") and iterable_type.endswith(">"):
        return split_type_args(iterable_type[len("tuple<") : -1])
    return ["unknown"] * target_count


def tuple_element_types(typ: str) -> list[str]:
    if not typ.startswith("tuple<") or not typ.endswith(">"):
        return list()
    return split_type_args(typ[len("tuple<") : -1])


def generic_type_parts(typ: str | None) -> tuple[str | None, list[str]]:
    if not typ:
        return None, []
    if "<" not in typ or not typ.endswith(">"):
        return typ, []
    base, inner = typ.split("<", 1)
    return base.strip(), split_type_args(inner[:-1])


def is_assignable_type(expected: str | None, actual: str | None) -> bool:
    if not expected or expected in {"any", "unknown"}:
        return True
    if not actual or actual in {"unknown", "na"}:
        return True
    if actual == "any":
        return True
    if expected == actual:
        return True
    enum_like_types = {
        "display",
        "line.style",
        "label.style",
        "box.style",
        "table.position",
        "barmerge.gaps",
        "barmerge.lookahead",
        "dividends.field",
        "earnings.field",
        "splits.field",
        "strategy.risk.type",
        "strategy.direction",
        "strategy.order_type",
        "extend",
    }
    if expected in enum_like_types and actual == expected:
        return True
    if expected == "int" and actual in enum_like_types:
        return True
    if expected == "float" and actual == "int":
        return True
    if expected.startswith("series<") and expected.endswith(">"):
        if actual.startswith("series<") and actual.endswith(">"):
            inner_actual = actual[len("series<") : -1]
            if inner_actual == "any":
                return True
        return is_assignable_type(expected[len("series<") : -1], actual)
    exp_base, exp_args = generic_type_parts(expected)
    act_base, act_args = generic_type_parts(actual)
    if exp_base in {"array", "map", "matrix"}:
        if exp_base == "array" and act_base == "tuple":
            if not exp_args or exp_args[0] in {"any", "unknown"}:
                return True
            return all(is_assignable_type(exp_args[0], a) for a in act_args)
        if act_base != exp_base:
            return False
        if not exp_args:
            return True
        if not act_args:
            return True
        if len(exp_args) != len(act_args):
            return False
        return all(is_assignable_type(e, a) for e, a in zip(exp_args, act_args))
    if expected.endswith("_direction") and actual.startswith("strategy."):
        return True
    return False
