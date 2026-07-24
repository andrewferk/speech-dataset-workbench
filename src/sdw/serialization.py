"""Canonical JSON byte format, shared by every artifact that writes JSON (ADR-0006, #54).

Load-bearing: exact goldens (ADR-0008), Manifest bytes hashed into dataset_version (ADR-0010).
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

# Compact separators (ADR-0006).
JSON_SEPARATORS = (",", ":")

# ensure_ascii off — Prompt text stays verbatim, not \uXXXX-escaped (ADR-0006).
JSON_ENSURE_ASCII = False


def render_jsonl(lines: Iterable[Mapping[str, Any]]) -> str:
    """Compact JSON Lines: one LF-terminated object per line, no trailing whitespace (#54)."""
    # sort_keys off: ADR-0006/ADR-0007 fix non-alphabetical key orders — don't add sort_keys=True.
    return "".join(
        json.dumps(line, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"
        for line in lines
    )
