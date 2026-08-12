"""The text digest: the operator's rendering of the Report (ADR-0022).

v0.1's `summary.txt` register. The shape is **invariant** — every line prints at every value,
including at zero failures and zero over-length Samples — so a diff between two Reports shows a
count changing rather than a line appearing (ADR-0007's `render_digest` rule, with more force here
because the goldens diff a captured stream).

The header is five items in a fixed order — Scope, N of M, the Reference, the comparability rule,
attribution — followed by the Run's Transcription provenance under ADR-0020's tier names (ADR-0024).
Below it, in ADR-0022's order: the Tier A headline, the six-number table, the Tier B − Tier A delta,
the five Breakdowns, the worklist.

Rates render as percentages here and as dimensionless rates in the JSON document (ADR-0022), with
fixed decimal places rather than `round`, which leaves a ragged column (v0.1's `_evidence`).
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple

from sdw.score.aggregate import (
    TIERS,
    Aggregation,
    Breakdown,
    Macro,
    MacroStatistic,
    Pooled,
    ScoredSample,
)
from sdw.score.alignment import Alignment
from sdw.score.metrics import SampleMetrics
from sdw.score.report import COMPARABILITY_NOTE, REFERENCE_NOTE, Report, normalizers
from sdw.score.text_normalization import TIER_A, TIER_B

# Wrapped at a fixed width rather than at the terminal's: the digest is a compared artifact, so its
# bytes may not depend on where it was printed (ADR-0022). Wide enough to hold the model row — the
# tier-1 fact a reader compares first — on one line.
WIDTH = 100

# One spelling of *no number here* — a fact `run.json` does not carry, or a rate ADR-0018 leaves
# undefined. Never an empty normalized text, which is a fact rather than an absence: see
# :func:`_text`.
ABSENT = "—"

# ADR-0007's `RATIO_DP`, reimplemented rather than imported for ADR-0017's reason: the eval path is
# a stranger consumer, and `sdw.quality` is build-path. A percentage is that rounded rate shifted by
# the same two places, not a second precision decision (ADR-0022).
RATIO_DP = 4
PERCENT_DP = RATIO_DP - 2

_SEPARATOR = " · "

# An empty normalized text — the model said nothing, or a tier deleted everything it said.
EMPTY = '""'


class _Metric(NamedTuple):
    """One Metric's label, and how to read it off a Pooled and off a Macro.

    Accessors rather than attribute names: a renamed field is a type error here rather than a cell
    that silently goes :data:`ABSENT`.
    """

    label: str
    pooled: Callable[[Pooled], float | None]
    macro: Callable[[Macro], MacroStatistic]


# In the order every level of the Report states them (ADR-0018).
_METRICS = (
    _Metric("WER", lambda pooled: pooled.word_error_rate, lambda macro: macro.word_error_rate),
    _Metric(
        "CER",
        lambda pooled: pooled.character_error_rate,
        lambda macro: macro.character_error_rate,
    ),
    _Metric(
        "SER", lambda pooled: pooled.sentence_error_rate, lambda macro: macro.sentence_error_rate
    ),
)

# The tiers as the tables column them, zipped onto :data:`~sdw.score.aggregate.TIERS` rather than
# re-listed: `strict` makes a third Normalizer a loud failure here instead of a dropped column.
_TIERS: tuple[tuple[str, str], ...] = tuple(zip(("A", "B"), TIERS, strict=True))


def render(report: Report) -> str:
    """The whole digest as one string, LF-terminated."""
    sections: list[list[str]] = [
        _header(report),
        _provenance(report.provenance),
        _headline(report),
        _table(report.aggregation),
        _delta(report.aggregation),
        *[_breakdown(breakdown) for breakdown in report.aggregation.breakdowns],
        _worklist(report),
    ]
    # One blank line between sections, none inside one: a section is the unit a reader scans to,
    # and every one of them prints at every value, so the blank lines are structure rather than
    # spacing (ADR-0022's fixed shape).
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


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


def _headline(report: Report) -> list[str]:
    """The Tier A Pooled WER, once, with its Scope attached (ADR-0022).

    Tier A, not Tier B: heading the Report with the aggressive normalizer would lower the number by
    hiding disfluency (ADR-0018).
    """
    pooled = report.aggregation.pooled[TIER_A]
    return _wrapped(
        [
            (
                "Headline",
                f"Tier A Pooled WER {_percent(pooled.word_error_rate)} over "
                f"{report.aggregation.samples} scored Sample(s), Scope {report.scope_label}",
            )
        ],
        indent="",
        label_width=len("Headline"),
    )


def _table(aggregation: Aggregation) -> list[str]:
    """The six numbers — three Metrics × two tiers — Pooled over the whole Scope (ADR-0018)."""
    rows = [("Metric", *(f"Tier {label}" for label, _ in _TIERS))]
    rows += [
        (metric.label, *(_percent(metric.pooled(aggregation.pooled[tier])) for _, tier in _TIERS))
        for metric in _METRICS
    ]
    return ["Pooled over the Scope", *_columns(rows, indent="  ")]


def _delta(aggregation: Aggregation) -> list[str]:
    """Tier B − Tier A, a first-class number, named a **delta** and never a "deviation" (ADR-0018).

    In percentage points, both sides being percentages here; the JSON rendering carries the
    dimensionless rates.
    """
    rows = [
        (
            metric.label,
            _points(
                metric.pooled(aggregation.pooled[TIER_B]),
                metric.pooled(aggregation.pooled[TIER_A]),
            ),
        )
        for metric in _METRICS
    ]
    return [
        f"Tier B − Tier A delta, in percentage points ({TIER_B} − {TIER_A})",
        *_columns(rows, indent="  "),
    ]


def _breakdown(breakdown: Breakdown) -> list[str]:
    """One axis: every group with its `n`, then the Macro across them (ADR-0018/ADR-0022).

    Nothing is suppressed and no threshold exists: `n` prints beside every rate, and an undefined
    group rate prints :data:`ABSENT` rather than vanishing.
    """
    heading = f"Breakdown — {breakdown.attribute}, {len(breakdown.groups)} group(s)"
    columns = tuple(f"{metric.label} {tier}" for metric in _METRICS for tier, _ in _TIERS)
    rows = [("group", "n", *columns)]
    rows += [
        (
            group.value,
            str(group.samples),
            *(
                _percent(metric.pooled(group.pooled[tier]))
                for metric in _METRICS
                for _, tier in _TIERS
            ),
        )
        for group in breakdown.groups
    ]
    rows += _macro_rows(breakdown)
    return [heading, *_columns(rows, indent="  ")]


def _macro_rows(breakdown: Breakdown) -> list[tuple[str, ...]]:
    """Mean, SD and median across the groups, and the per-Metric exclusion counts (ADR-0018).

    The exclusions print as a row rather than a footnote: a Macro over two of five groups is a
    different claim from one over five, and a diff has to show that as a value change.
    """
    statistics: tuple[tuple[str, Callable[[MacroStatistic], str]], ...] = (
        ("macro mean", lambda statistic: _percent(statistic.mean)),
        ("macro sd", lambda statistic: _percent(statistic.standard_deviation)),
        ("macro median", lambda statistic: _percent(statistic.median)),
        # `n` is the group count, so the exclusions are stated in groups, not Samples.
        ("groups excluded", lambda statistic: str(statistic.excluded_groups)),
    )
    return [
        (
            label,
            ABSENT,
            *(
                cell(metric.macro(breakdown.macro[tier]))
                for metric in _METRICS
                for _, tier in _TIERS
            ),
        )
        for label, cell in statistics
    ]


def _worklist(report: Report) -> list[str]:
    """Every Sample with any Tier A error, worst-first, ties by `id`; clean ones counted, not
    listed (ADR-0022).

    There is no top-N: introducing one would need a constant nothing here can supply.
    """
    erred = sorted(
        (sample for sample in report.samples if _erred(sample.metrics[TIER_A])), key=_worst_first
    )
    clean = len(report.samples) - len(erred)
    lines = [
        f"Worklist — {len(erred)} of {len(report.samples)} scored Sample(s) erred under "
        f"{TIER_A}, worst first; {clean} clean, counted not listed"
    ]
    for sample in erred:
        metrics = sample.metrics[TIER_A]
        lines += _wrapped(
            [
                (
                    sample.id,
                    f"WER {_percent(metrics.word_error_rate)}{_SEPARATOR}"
                    f"CER {_percent(metrics.character_error_rate)}{_SEPARATOR}"
                    f"words {_counts(metrics.words)}{_SEPARATOR}"
                    f"chars {_counts(metrics.characters)}",
                ),
                # The normalized pair, which exists in no other artifact and is what the manual
                # gate reads to tell recognition error from speaker deviation (ADR-0026).
                ("  ref", _text(metrics.reference)),
                ("  hyp", _text(metrics.hypothesis)),
            ],
            indent="  ",
            label_width=max(len(sample.id), len("  ref")),
        )
    return lines


def _erred(metrics: SampleMetrics) -> bool:
    """Any error at all under this tier — word, character, or the sentence-level binary."""
    return bool(metrics.words.errors or metrics.characters.errors or metrics.sentence_error)


def _worst_first(sample: ScoredSample) -> tuple[int, float, str]:
    """Tier A WER descending, ties by `id` ascending (ADR-0022).

    An undefined WER cannot be ranked against a rate, so it sorts after every ranked Sample rather
    than being given a number it does not have.
    """
    rate = sample.metrics[TIER_A].word_error_rate
    if rate is None:
        return (1, 0.0, sample.id)
    return (0, -rate, sample.id)


def _counts(alignment: Alignment) -> str:
    """``S=1 D=0 I=0 N=4`` — the integer evidence behind a rate (ADR-0018)."""
    return (
        f"S={alignment.substitutions} D={alignment.deletions} "
        f"I={alignment.insertions} N={alignment.reference_length}"
    )


def _text(text: str) -> str:
    """A normalized text, or :data:`EMPTY` — a tier producing `""` is a fact, not an absence."""
    return text or EMPTY


def _percent(rate: float | None) -> str:
    """``8.33%``, or :data:`ABSENT` for a rate ADR-0018 leaves undefined — never `0.00%`.

    The canonical rate is rounded first, so the percentage is that number shifted rather than a
    second rounding of the float behind it (ADR-0022).
    """
    if rate is None:
        return ABSENT
    return f"{round(rate, RATIO_DP) * 100:.{PERCENT_DP}f}%"


def _points(later: float | None, earlier: float | None) -> str:
    """``+1.25`` / ``-4.17`` percentage points, or :data:`ABSENT` if either side is undefined.

    Subtracted after rounding, so the delta is the difference of the two numbers printed above it
    rather than a third one. The sign always prints — a direction a diff changes, never one that
    appears.
    """
    if later is None or earlier is None:
        return ABSENT
    difference = round(later, RATIO_DP) - round(earlier, RATIO_DP)
    return f"{difference * 100:+.{PERCENT_DP}f}"


def _columns(rows: Sequence[Sequence[str]], *, indent: str) -> list[str]:
    """A table: first column left-aligned, every other right-aligned, widths from the content.

    Widths are computed rather than fixed, so a long `session_id` or Prompt id keeps the columns
    lined up instead of shifting one row's numbers out of the reader's eye line (v0.1's split
    table). Every row must be the same length — a shape error, not a formatting one.
    """
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    return [
        (
            indent
            + "  ".join(
                cell.ljust(width) if index == 0 else cell.rjust(width)
                for index, (cell, width) in enumerate(zip(row, widths, strict=True))
            )
        ).rstrip()
        for row in rows
    ]


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

    Compacting into prose to match ADR-0024's example would reword a moved decode constant rather
    than show it.
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
