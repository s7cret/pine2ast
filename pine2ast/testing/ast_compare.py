from __future__ import annotations


def strip_spans(value):
    if isinstance(value, dict):
        return {k: strip_spans(v) for k, v in value.items() if k != "span"}
    if isinstance(value, list):
        return [strip_spans(v) for v in value]
    return value
