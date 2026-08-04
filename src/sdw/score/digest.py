"""The text digest: the operator's rendering of the Report (ADR-0022).

v0.1's `summary.txt` register. The shape is **invariant** — every line prints at every value,
including at zero failures and zero over-length Samples — so a diff between two Reports shows a
count changing rather than a line appearing (ADR-0007's `render_digest` rule, with more force here
because the goldens diff a captured stream).

The header is five items in a fixed order — Scope, N of M, the Reference, the comparability rule,
attribution — followed by the Run's Transcription provenance under ADR-0020's tier names (ADR-0024).
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

from sdw.score.report import COMPARABILITY_NOTE, REFERENCE_NOTE, Report, normalizers

# Wrapped at a fixed width rather than at the terminal's: the digest is a compared artifact, so its
# bytes may not depend on where it was printed (ADR-0022). Wide enough to hold the model row — the
# tier-1 fact a reader compares first — on one line.
WIDTH = 100

# A fact `run.json` does not carry. The row still prints — the shape is fixed.
ABSENT = "—"

_SEPARATOR = " · "


def render(report: Report) -> str:
    """The whole digest as one string, LF-terminated."""
    return "\n".join([*_header(report), "", *_provenance(report.provenance)]) + "\n"


def _header(report: Report) -> list[str]:
    """ADR-0022's five items, in its order, each unconditionally present."""
    tier_a, tier_b = normalizers()
    items = [
        ("Scope", report.scope_label),
        # Printed even when N = M, so a Report over a subset can never be mistaken for one over
        # everything — the whole point of the disclosure (ADR-0017).
        (
            "Samples",
            f"{report.scored} of {report.in_scope} scored — "
            f"{report.failed} Transcription failure(s), {report.long_form} long_form",
        ),
        ("Reference", REFERENCE_NOTE),
        ("Comparing", COMPARABILITY_NOTE),
        (
            "Attribution",
            f"Normalizers {tier_a} and {tier_b}{_SEPARATOR}scored by sdw {report.tool_version}",
        ),
    ]
    return _wrapped(items, indent="", label_width=max(len(label) for label, _ in items))


def _provenance(provenance: Mapping[str, Any]) -> list[str]:
    """The Run's provenance, grouped under ADR-0020's tier names as section headings (ADR-0024).

    The *never relevant* tier (`timing`, `record_version`, `record_line_count`) is omitted; the JSON
    rendering carries the file whole.
    """
    dataset = _block(provenance, "dataset")
    sections: Sequence[tuple[str, Sequence[tuple[str, str]]]] = (
        (
            "Transcription conditions — must match to compare",
            (
                ("model", _model(_block(provenance, "model"))),
                ("decode", _pairs(_block(provenance, "decode"))),
                ("language", _language(_block(provenance, "language"))),
            ),
        ),
        (
            "Dataset — must match, or escalate to a masked diff of the two Records",
            # Full, not elided: this row and the model's revision exist to be compared, and a
            # shortened id is a difference a reader can miss. `dataset.tool_version` and
            # `manifest_version` are on no tier, so the digest omits them (ADR-0020/ADR-0024).
            (("dataset_version", _get(dataset, "dataset_version")),),
        ),
        (
            "Disclosed — may differ; the same question under different arithmetic",
            (
                ("runtime", _pairs(_block(provenance, "runtime"))),
                ("host", _pairs(_block(provenance, "host"))),
                # `run.json`'s top-level `tool_version` names the tool that wrote that file, which
                # is the one that transcribed — not the scoring one in the header (ADR-0020).
                ("tool", f"transcribed {_get(provenance, 'tool_version')}"),
            ),
        ),
    )
    width = max(len(label) for _, rows in sections for label, _ in rows)
    lines: list[str] = []
    for heading, rows in sections:
        lines.append(heading)
        lines += _wrapped(rows, indent="  ", label_width=width)
    return lines


def _wrapped(items: Sequence[tuple[str, str]], *, indent: str, label_width: int) -> list[str]:
    """Label-and-value rows, wrapped to :data:`WIDTH` with the value column kept flush."""
    lines: list[str] = []
    for label, value in items:
        prefix = f"{indent}{label:<{label_width}}  "
        lines += textwrap.wrap(
            value,
            width=WIDTH,
            initial_indent=prefix,
            subsequent_indent=" " * len(prefix),
            # A `k=v · k=v` run of provenance is one long token to `textwrap`; breaking it would
            # split an identifier across lines rather than overrunning by a few columns.
            break_long_words=False,
        ) or [prefix.rstrip()]
    return lines


def _block(provenance: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    block = provenance.get(key)
    return block if isinstance(block, Mapping) else {}


def _model(block: Mapping[str, Any]) -> str:
    """``openai/whisper-large-v3-turbo @ <revision> (mit)`` — ADR-0016's identity set, as
    ADR-0024 renders it."""
    if not block:
        return ABSENT
    return f"{_get(block, 'repo_id')} @ {_get(block, 'revision')} ({_get(block, 'license')})"


def _language(block: Mapping[str, Any]) -> str:
    """``en (declared)`` — the seventh decode constant, stated once beside its source (ADR-0020)."""
    if not block:
        return ABSENT
    return f"{_get(block, 'value')} ({_get(block, 'source')})"


def _pairs(block: Mapping[str, Any]) -> str:
    """``k=v · k=v`` over a block, in file order.

    The keys are kept rather than compacted into prose as ADR-0024's example does: a decode
    constant that moved would then be reworded rather than shown.
    """
    if not block:
        return ABSENT
    return _SEPARATOR.join(f"{key}={_value(value)}" for key, value in block.items())


def _get(mapping: Mapping[str, Any], key: str) -> str:
    """One fact by name, or :data:`ABSENT` — a fact the file does not carry is not a `null`."""
    if key not in mapping:
        return ABSENT
    return _value(mapping[key])


def _value(value: Any) -> str:
    """A JSON scalar as the file spells it — ``null``/``true``, never ``None``/``True``."""
    return value if isinstance(value, str) else json.dumps(value)
