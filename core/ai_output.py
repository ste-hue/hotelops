"""Validate positional JSON batches before model output is joined to sources.

This module has no provider, business routing, or write authority. Field-level
contracts remain with the consumer. Missing/extra results make alignment
unprovable, so the entire batch stays unclassified.
"""

from __future__ import annotations

import json
import re


def _reject_constant(value: str):
    raise ValueError("Non-finite JSON number")


def parse_json_batch(raw: str, count: int) -> list[dict | None]:
    """Return exactly count slots; invalid items never shift later results."""
    empty = [None for _ in range(count)]
    if not isinstance(raw, str):
        return empty
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match is None:
        return empty
    try:
        items = json.loads(match.group(), parse_constant=_reject_constant)
    except (ValueError, TypeError):
        return empty
    if not isinstance(items, list) or len(items) != count:
        return empty
    return [item if isinstance(item, dict) else None for item in items]
