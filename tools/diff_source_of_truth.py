#!/usr/bin/env python3
"""Offline TradingView source-of-truth snapshot drift checker.

The tool compares two local documentation snapshots and reports likely changes in
namespaces, functions, methods, signatures, named arguments, return types, and
strategy() declaration arguments. It intentionally uses heuristic parsing so it
can work with committed markdown/html/text fixtures or privately captured local
snapshots without scraping TradingView or requiring login.

Missing or unparseable signatures are emitted as ambiguous findings rather than
being silently ignored.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".html", ".htm", ".txt", ".json"}
SIGNATURE_RE = re.compile(
    r"(?P<prefix>\b(?:function|method|builtin|declaration)\b\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?(?:<[^>]+>)?)"
    r"\s*\((?P<params>[^)]*)\)"
    r"\s*(?:(?:→|->|=>|returns?\s+)\s*(?P<returns>[^`\n;<]+))?",
    re.IGNORECASE,
)
PAREN_MENTION_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*\([^)]*($|\n)")
HEADING_NAMESPACE_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?:namespace\s+)?`?(?P<ns>[A-Za-z_][A-Za-z0-9_]*)`?\s*$", re.I)
CODE_TAG_RE = re.compile(r"<code[^>]*>(.*?)</code>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str | None = None
    default: str | None = None
    required: bool = True

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "required": self.required}
        if self.type:
            out["type"] = self.type
        if self.default is not None:
            out["default"] = self.default
        return out


@dataclass
class SignatureItem:
    name: str
    kind: str
    params: list[Parameter]
    returns: str | None
    source: str
    line: int
    raw: str
    catalog_id: str | None = None

    @property
    def namespace(self) -> str | None:
        if "." not in self.name:
            return None
        return self.name.split(".", 1)[0]

    @property
    def param_names(self) -> list[str]:
        return [p.name for p in self.params]

    def signature_key(self) -> list[dict[str, Any]]:
        return [p.as_dict() for p in self.params]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "parameters": [p.as_dict() for p in self.params],
            "returns": self.returns,
            "source": self.source,
            "line": self.line,
            "catalog_id": self.catalog_id,
            "raw": self.raw,
        }


@dataclass
class Snapshot:
    root: Path
    items: dict[str, SignatureItem] = field(default_factory=dict)
    namespaces: set[str] = field(default_factory=set)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)


def split_params(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in {'"', "'"}:
            quote = ch
            current.append(ch)
            continue
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_parameter(text: str, index: int) -> Parameter:
    raw = text.strip().strip("`")
    default: str | None = None
    if "=" in raw:
        before, after = raw.split("=", 1)
        raw = before.strip()
        default = after.strip() or None
    raw = raw.lstrip("[]")
    # Common TV-ish forms: "source series float", "series float source", "source: series float".
    if ":" in raw:
        name, typ = raw.split(":", 1)
        return Parameter(clean_name(name, index), typ.strip() or None, default, default is None)
    tokens = raw.split()
    if not tokens:
        return Parameter(f"arg{index + 1}", None, default, default is None)
    if len(tokens) == 1:
        return Parameter(clean_name(tokens[0], index), None, default, default is None)
    # Prefer a valid identifier on the left, but handle "series float source" too.
    if is_identifier(tokens[0]):
        return Parameter(clean_name(tokens[0], index), " ".join(tokens[1:]), default, default is None)
    return Parameter(clean_name(tokens[-1], index), " ".join(tokens[:-1]), default, default is None)


def clean_name(value: str, index: int) -> str:
    name = value.strip().strip("`[]")
    name = re.sub(r"[^A-Za-z0-9_]", "", name)
    return name or f"arg{index + 1}"


def is_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value))


def parse_params(text: str) -> list[Parameter]:
    text = text.strip()
    if not text:
        return list()
    return [parse_parameter(part, i) for i, part in enumerate(split_params(text))]


def html_to_lines(text: str) -> list[str]:
    code_fragments = [html.unescape(TAG_RE.sub("", match.group(1))) for match in CODE_TAG_RE.finditer(text)]
    stripped = html.unescape(TAG_RE.sub("\n", text))
    return code_fragments + stripped.splitlines()


def iter_snapshot_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def parse_json_snapshot(path: Path, root: Path, catalog: dict[str, str]) -> Snapshot:
    snap = Snapshot(root=root)
    data = json.loads(path.read_text(encoding="utf-8"))
    records: Iterable[Any]
    if isinstance(data, dict) and isinstance(data.get("functions"), dict):
        records = data["functions"].values()
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        records = data["items"]
    elif isinstance(data, list):
        records = data
    else:
        snap.ambiguous.append(ambiguous_record(root, path, 1, "json_unrecognized_shape", path.name))
        return snap
    for idx, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not record.get("name"):
            snap.ambiguous.append(ambiguous_record(root, path, idx, "json_item_unparseable", repr(record)[:160]))
            continue
        params = []
        for i, param in enumerate(record.get("parameters") or record.get("params") or []):
            if isinstance(param, dict):
                params.append(
                    Parameter(
                        clean_name(str(param.get("name", "")), i),
                        str(param.get("type")) if param.get("type") is not None else None,
                        str(param.get("default")) if param.get("default") is not None else None,
                        bool(param.get("required", param.get("default") is None)),
                    )
                )
            else:
                params.append(parse_parameter(str(param), i))
        item = SignatureItem(
            name=str(record["name"]),
            kind=str(record.get("kind") or infer_kind(str(record["name"]), "")),
            params=params,
            returns=str(record.get("returns")) if record.get("returns") is not None else None,
            source=str(path.relative_to(root)),
            line=idx,
            raw=json.dumps(record, ensure_ascii=False, sort_keys=True),
            catalog_id=catalog_id(str(record["name"]), catalog),
        )
        add_item(snap, item)
    return snap


def parse_snapshot(root: Path, catalog: dict[str, str] | None = None) -> Snapshot:
    catalog = catalog or {}
    root = root.resolve()
    snap = Snapshot(root=root)
    if not root.exists():
        raise FileNotFoundError(root)
    for path in iter_snapshot_files(root):
        if path.suffix.lower() == ".json":
            json_snap = parse_json_snapshot(path, root, catalog)
            snap.items.update(json_snap.items)
            snap.namespaces.update(json_snap.namespaces)
            snap.ambiguous.extend(json_snap.ambiguous)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = html_to_lines(text) if path.suffix.lower() in {".html", ".htm"} else text.splitlines()
        current_namespace: str | None = None
        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            heading = HEADING_NAMESPACE_RE.match(stripped)
            if heading:
                current_namespace = heading.group("ns")
                snap.namespaces.add(current_namespace)
                continue
            for match in SIGNATURE_RE.finditer(stripped):
                name = match.group("name")
                params_text = match.group("params")
                returns = normalize_return(match.group("returns"))
                if name in {"if", "for", "while", "switch"}:
                    continue
                if "." not in name and current_namespace and name not in {"strategy", "indicator", "library"}:
                    name = f"{current_namespace}.{name}"
                item = SignatureItem(
                    name=name,
                    kind=infer_kind(name, match.group("prefix") or stripped),
                    params=parse_params(params_text),
                    returns=returns,
                    source=str(path.relative_to(root)),
                    line=line_no,
                    raw=stripped,
                    catalog_id=catalog_id(name, catalog),
                )
                add_item(snap, item)
            if "(" in stripped and ")" in stripped and not SIGNATURE_RE.search(stripped):
                snap.ambiguous.append(ambiguous_record(root, path, line_no, "unparseable_signature", stripped))
            elif PAREN_MENTION_RE.search(stripped):
                snap.ambiguous.append(ambiguous_record(root, path, line_no, "incomplete_signature", stripped))
    return snap


def normalize_return(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().strip("` .")
    value = re.sub(r"\s+", " ", value)
    return value or None


def infer_kind(name: str, context: str) -> str:
    lower = context.lower()
    if "method" in lower:
        return "method"
    if name in {"strategy", "indicator", "library"} or "declaration" in lower:
        return "declaration"
    return "function"


def add_item(snapshot: Snapshot, item: SignatureItem) -> None:
    snapshot.items[item.name] = item
    if item.namespace:
        snapshot.namespaces.add(item.namespace)


def ambiguous_record(root: Path, path: Path, line: int, reason: str, raw: str) -> dict[str, Any]:
    return {"source": str(path.relative_to(root)), "line": line, "reason": reason, "raw": raw.strip()}


def load_catalog_ids(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    functions = data.get("functions", {}) if isinstance(data, dict) else {}
    return {str(key): str(value.get("name", key)) for key, value in functions.items() if isinstance(value, dict)}


def catalog_id(name: str, catalog: dict[str, str]) -> str | None:
    if name in catalog:
        return catalog[name]
    base = re.sub(r"<[^>]+>", "", name)
    return catalog.get(base)


def compare_snapshots(baseline: Snapshot, current: Snapshot) -> dict[str, Any]:
    baseline_names = set(baseline.items)
    current_names = set(current.items)
    new_names = sorted(current_names - baseline_names)
    removed_names = sorted(baseline_names - current_names)
    common_names = sorted(baseline_names & current_names)
    changed_signatures: list[dict[str, Any]] = []
    changed_returns: list[dict[str, Any]] = []
    named_arg_changes: list[dict[str, Any]] = []
    method_changes: list[dict[str, Any]] = []
    strategy_arg_changes: list[dict[str, Any]] = []

    for name in common_names:
        old = baseline.items[name]
        new = current.items[name]
        if old.signature_key() != new.signature_key():
            entry = change_entry(name, old, new, "signature_changed")
            changed_signatures.append(entry)
            if old.kind == "method" or new.kind == "method":
                method_changes.append(entry)
            added_args = sorted(set(new.param_names) - set(old.param_names))
            removed_args = sorted(set(old.param_names) - set(new.param_names))
            if added_args or removed_args:
                named_arg_changes.append(
                    {
                        "name": name,
                        "catalog_id": new.catalog_id or old.catalog_id,
                        "added": added_args,
                        "removed": removed_args,
                        "baseline": old.as_dict(),
                        "current": new.as_dict(),
                    }
                )
            if name == "strategy":
                strategy_arg_changes.append(entry)
        if old.returns != new.returns:
            changed_returns.append(change_entry(name, old, new, "return_type_changed"))

    for name in new_names:
        if current.items[name].kind == "method":
            method_changes.append({"change": "method_added", "current": current.items[name].as_dict()})
    for name in removed_names:
        if baseline.items[name].kind == "method":
            method_changes.append({"change": "method_removed", "baseline": baseline.items[name].as_dict()})

    return {
        "summary": {
            "baseline_items": len(baseline.items),
            "current_items": len(current.items),
            "baseline_namespaces": len(baseline.namespaces),
            "current_namespaces": len(current.namespaces),
            "ambiguous": len(baseline.ambiguous) + len(current.ambiguous),
            "changes": len(new_names)
            + len(removed_names)
            + len(changed_signatures)
            + len(changed_returns)
            + len(baseline.namespaces ^ current.namespaces),
        },
        "new_namespaces": sorted(current.namespaces - baseline.namespaces),
        "removed_namespaces": sorted(baseline.namespaces - current.namespaces),
        "new_functions": [current.items[name].as_dict() for name in new_names if current.items[name].kind != "method"],
        "removed_functions": [baseline.items[name].as_dict() for name in removed_names if baseline.items[name].kind != "method"],
        "changed_signatures": changed_signatures,
        "new_removed_named_args": named_arg_changes,
        "changed_return_types": changed_returns,
        "method_changes": method_changes,
        "strategy_declaration_args": strategy_arg_changes,
        "ambiguous": {"baseline": baseline.ambiguous, "current": current.ambiguous},
    }


def change_entry(name: str, old: SignatureItem, new: SignatureItem, change: str) -> dict[str, Any]:
    return {
        "change": change,
        "name": name,
        "catalog_id": new.catalog_id or old.catalog_id,
        "baseline": old.as_dict(),
        "current": new.as_dict(),
    }


def render_markdown(report: dict[str, Any], baseline: Path, current: Path) -> str:
    summary = report["summary"]
    lines = [
        "# TradingView Source-of-Truth Diff Report",
        "",
        "Offline heuristic diff generated from local snapshots. This is a drift detector, not a full TradingView parity claim.",
        "",
        f"- Baseline: `{baseline}`",
        f"- Current: `{current}`",
        f"- Baseline items: {summary['baseline_items']}",
        f"- Current items: {summary['current_items']}",
        f"- Ambiguous signatures: {summary['ambiguous']}",
        f"- Total change buckets/items: {summary['changes']}",
        "",
    ]
    section_specs = [
        ("New namespaces", "new_namespaces"),
        ("Removed namespaces", "removed_namespaces"),
        ("New functions/declarations", "new_functions"),
        ("Removed functions/declarations", "removed_functions"),
        ("Changed signatures", "changed_signatures"),
        ("Named argument additions/removals", "new_removed_named_args"),
        ("Changed return types", "changed_return_types"),
        ("Methods", "method_changes"),
        ("Strategy declaration args", "strategy_declaration_args"),
    ]
    for title, key in section_specs:
        lines.extend([f"## {title}", ""])
        values = report.get(key) or []
        if not values:
            lines.extend(["None detected.", ""])
            continue
        for value in values:
            if isinstance(value, str):
                lines.append(f"- `{value}`")
            else:
                lines.append(f"- {format_change(value)}")
        lines.append("")
    lines.extend(["## Ambiguous / unparseable signatures", ""])
    amb = report.get("ambiguous", {})
    if not amb.get("baseline") and not amb.get("current"):
        lines.append("None detected.")
    else:
        for side in ("baseline", "current"):
            lines.append(f"### {side.title()}")
            entries = amb.get(side) or []
            if not entries:
                lines.append("None.")
            for entry in entries:
                lines.append(
                    f"- `{entry['source']}:{entry['line']}` {entry['reason']}: {entry['raw'][:140]}"
                )
            lines.append("")
    lines.extend(
        [
            "",
            "## Detector capabilities and limitations",
            "",
            "- Parses local markdown, HTML, text, and JSON snapshots; no network access or TradingView login is used.",
            "- Detects item-level namespace/function/method additions/removals, parameter/name changes, return changes, and strategy() declaration argument drift where signatures are parseable.",
            "- Links changed/new/removed items to `pine2ast/semantic/builtins_v6.json` catalog ids when names match exactly or after generic suffix removal.",
            "- Heuristic parsing can misclassify prose examples or miss complex rendered documentation. Lines with parenthesized API-like content that cannot be parsed are reported as ambiguous.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def format_change(value: dict[str, Any]) -> str:
    if "current" in value and "baseline" in value:
        name = value.get("name") or value["current"].get("name") or value["baseline"].get("name")
        catalog = value.get("catalog_id") or value["current"].get("catalog_id") or value["baseline"].get("catalog_id")
        suffix = f" (catalog `{catalog}`)" if catalog else ""
        if "added" in value or "removed" in value:
            added = ", ".join(f"`{arg}`" for arg in value.get("added", [])) or "none"
            removed = ", ".join(f"`{arg}`" for arg in value.get("removed", [])) or "none"
            return f"`{name}` named args changed{suffix}: added {added}; removed {removed}"
        return f"`{name}` {value.get('change', 'changed')}{suffix}"
    if "current" in value:
        item = value["current"]
        suffix = f" (catalog `{item['catalog_id']}`)" if item.get("catalog_id") else ""
        return f"`{item['name']}` {value.get('change', 'added')}{suffix}"
    if "baseline" in value:
        item = value["baseline"]
        suffix = f" (catalog `{item['catalog_id']}`)" if item.get("catalog_id") else ""
        return f"`{item['name']}` {value.get('change', 'removed')}{suffix}"
    if "name" in value:
        suffix = f" (catalog `{value['catalog_id']}`)" if value.get("catalog_id") else ""
        return f"`{value['name']}`{suffix}"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_outputs(report: dict[str, Any], markdown_path: Path, json_path: Path, baseline: Path, current: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report, baseline, current), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="baseline local snapshot directory")
    parser.add_argument("--current", type=Path, required=True, help="current local snapshot directory")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("pine2ast/semantic/builtins_v6.json"),
        help="Pine2AST builtin catalog JSON used for catalog id links",
    )
    parser.add_argument("--markdown-out", type=Path, default=Path("docs/TV_DIFF_REPORT.md"))
    parser.add_argument("--json-out", type=Path, default=Path("reports/tv_diff_report.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    catalog = load_catalog_ids(args.catalog)
    baseline = parse_snapshot(args.baseline, catalog)
    current = parse_snapshot(args.current, catalog)
    report = compare_snapshots(baseline, current)
    write_outputs(report, args.markdown_out, args.json_out, args.baseline, args.current)
    print(
        f"wrote {args.markdown_out} and {args.json_out} "
        f"({report['summary']['changes']} change buckets/items, {report['summary']['ambiguous']} ambiguous)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
