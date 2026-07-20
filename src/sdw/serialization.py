"""The tool's canonical JSON byte format, stated once for every artifact that writes JSON (#54).

Three modules used to re-derive these decisions independently — the Manifest, the HF view, and the
quality report — and they had already drifted apart on ``ensure_ascii`` before anyone noticed. That
drift could not fail a test: each artifact has its own golden, so two files disagreeing about how to
spell a character reads as two intentional baselines rather than as a bug. Stating the format once
and importing it is what makes "the Manifest and the quality report agree" a property of the code.

The format is load-bearing rather than cosmetic. ADR-0008 compares artifacts as exact goldens, and
ADR-0010 hashes the emitted Manifest bytes into ``dataset_version`` — so a separator is part of a
Dataset's identity.

This module is a leaf: it imports nothing from ``sdw``, so every writer can depend on it and none of
them can create a cycle. :mod:`sdw.config` depends on it too — the ``dataset_version`` preimage
needs the same byte format — rather than owning it, because a JSONL join does not belong to "the
effective config" and config would then change for two unrelated reasons.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

# `json.dumps` defaults to `", "` and `": "`; every artifact here is compact.
JSON_SEPARATORS = (",", ":")

# UTF-8 throughout, so a non-ASCII character is emitted as itself rather than as a `\uXXXX` escape.
# The choice is deliberate and it is the *text* that forces it: `text` carries Prompt text verbatim
# (ADR-0006), so escaping would make a Manifest of accented or non-Latin prompts unreadable to the
# operator who has to check it, and would inflate the bytes a consumer decodes for no gain. Every
# file is written as UTF-8 already, so there is nothing an escape would protect against. The
# Manifest can therefore differ byte for byte on real data, and that is the point; `quality.jsonl`
# cannot, since every field of it is either hash-derived or drawn from a fixed ASCII vocabulary,
# which is why unifying the two writers on this value re-baselines no golden.
JSON_ENSURE_ASCII = False


def render_jsonl(lines: Iterable[Mapping[str, Any]]) -> str:
    """Objects as JSON Lines: one compact object per line, LF-terminated, no trailing whitespace.

    The one JSONL writer, used by the Manifest, the HF view, and the quality report alike (#54).
    A shared pair of constants would still let a writer import them and forget to pass one; a
    shared join makes the byte format something a writer cannot express an opinion about.

    Every line is terminated, so an empty sequence yields an empty file rather than a lone newline,
    and appending one is always a whole-line change. Key order is the caller's insertion order —
    ``sort_keys`` is deliberately off, because both ADR-0006's Manifest and ADR-0007's quality line
    fix an order that is not alphabetical. The config's own preimage is the one JSON in the tool
    that *is* key-sorted, and it is a single object rather than a line-per-record file, so it
    serializes through :meth:`~sdw.config.Config.canonical_json` instead of through here.
    """
    return "".join(
        json.dumps(line, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"
        for line in lines
    )
