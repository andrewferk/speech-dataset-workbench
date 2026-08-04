"""Canonical JSON byte format, shared by every artifact that writes JSON (ADR-0006, #54).

Byte format is load-bearing: goldens (ADR-0008), dataset_version (ADR-0010).
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

# Compact separators (ADR-0006).
JSON_SEPARATORS = (",", ":")

# ensure_ascii off — Prompt text stays verbatim, not \uXXXX-escaped (ADR-0006).
JSON_ENSURE_ASCII = False


def render_json(document: Mapping[str, Any]) -> str:
    """One compact, LF-terminated JSON document — the same bytes `render_jsonl` writes per line.

    The Evaluation Report's machine rendering is a single object rather than JSONL (ADR-0022), and
    it shares this module for the reason ADR-0019 gives the eval path: re-deriving the byte format
    is the drift ADR-0006 exists to prevent, and no golden can detect it.
    """
    return json.dumps(document, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"


def render_jsonl(lines: Iterable[Mapping[str, Any]]) -> str:
    """Compact JSON Lines: one LF-terminated object per line, no trailing whitespace (#54)."""
    # sort_keys off: ADR-0006/ADR-0007 fix non-alphabetical key orders — don't add sort_keys=True.
    return "".join(
        json.dumps(line, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"
        for line in lines
    )
