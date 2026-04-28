from __future__ import annotations

from pine2ast.diagnostics.diagnostic import Diagnostic


def format_diagnostic(d: Diagnostic, source_name: str = "<memory>") -> str:
    line = f"{d.severity.value} {d.code} at {source_name}:{d.span.start_line}:{d.span.start_col}"
    parts = [line, f"  {d.message}"]
    if d.hint:
        parts.append(f"Hint: {d.hint}")
    if d.doc_url:
        parts.append(f"Docs: {d.doc_url}")
    return "\n".join(parts)
