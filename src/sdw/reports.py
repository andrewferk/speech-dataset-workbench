"""Render the two report artifacts a build emits: `quality.jsonl` and `summary.txt` (#32).

Two artifacts for two readers (ADR-0007): `quality.jsonl` is one line per kept Recording, sorted by
`id` and joinable to the manifest, for a consumer that filters; `summary.txt` omits clean
Recordings, for an operator. Both are deterministic — nothing keyed off anything but
:data:`~sdw.split.SPLIT_ORDER` (ADR-0004) — so ADR-0008's golden comparison holds; run duration, if
shown, stays on stdout (ADR-0012).
"""

from collections.abc import Sequence
from pathlib import Path

from sdw.quality import QualityMetrics, render_digest
from sdw.serialization import render_jsonl
from sdw.split import MIN_SESSIONS_FOR_REPAIR, SPLIT_ORDER, SpeakerOverlap, SplitResult

REPORTS_DIR = "reports"
QUALITY_JSONL = "quality.jsonl"
SUMMARY_TXT = "summary.txt"


def write_reports(
    directory: Path,
    results: Sequence[tuple[str, QualityMetrics]],
    split_result: SplitResult,
) -> None:
    """Write both artifacts into ``directory`` — the staging tree's `reports/` (ADR-0003).

    Called inside `build`'s staging window, so these files are committed by the same rename as
    everything else and a later error leaves no durable output.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / QUALITY_JSONL).write_text(render_quality_jsonl(results), encoding="utf-8")
    (directory / SUMMARY_TXT).write_text(render_summary(results, split_result), encoding="utf-8")


# --- The machine-readable report ----------------------------------------------------------------


def render_quality_jsonl(results: Sequence[tuple[str, QualityMetrics]]) -> str:
    """One JSON object per kept Recording, sorted by `id`, clean lines included.

    Clean lines are present because the file records what was measured, not a worklist — an absent
    line cannot distinguish "clean" from "never measured" (ADR-0007); `summary.txt` is the worklist
    that omits them. Sorted by `id` so the bytes are stable under a reordering of `recordings.csv`.
    Shares :func:`~sdw.serialization.render_jsonl` with the Manifest, so this file and `train.jsonl`
    cannot disagree about the JSONL byte format (#54).
    """
    ordered = sorted(results, key=lambda result: result[0])
    return render_jsonl(_line(rid, metrics) for rid, metrics in ordered)


def _line(recording_id: str, metrics: QualityMetrics) -> dict[str, object]:
    """One Recording's line: the `id`, the metrics as they round, then the flags.

    The metrics come from :class:`~sdw.quality.QualityMetrics` rather than being re-listed here, so
    a new metric cannot be measured and digested yet silently missing from the file (#68). `id`
    leads and `flags` (the only variable-length field) trails (ADR-0007).
    """
    return {
        "id": recording_id,
        **metrics.rounded(),
        "flags": list(metrics.flags),
    }


# --- The human summary ---------------------------------------------------------------------------


def render_summary(results: Sequence[tuple[str, QualityMetrics]], split_result: SplitResult) -> str:
    """The operator's digest: the quality section, then the split section.

    The below-three-Sessions warning appears in *both* sections so an operator scanning to the one
    they came for cannot miss it (ADR-0004). Prefixed here rather than passed into
    :func:`~sdw.quality.render_digest`, so `validate` — which never runs the splitter — cannot get a
    digest that differs from `build`'s by a parameter it has no way to fill (ADR-0007).
    """
    sections = [f"{warning}\n" for warning in _min_sessions_warning(split_result)]
    sections += [
        render_digest(results),
        "\n".join(_split_section(split_result)) + "\n",
    ]
    return "\n".join(sections)


def _min_sessions_warning(split_result: SplitResult) -> tuple[str, ...]:
    """The unmissable warning for a Dataset below :data:`~sdw.split.MIN_SESSIONS_FOR_REPAIR`.

    Produce-and-flag: a three-way split of two Sessions is impossible, so the build assigns what it
    can, emits valid empty Splits, and says so — it never aborts (ADR-0004). No companion warning
    exists for an empty Split at or above that count — pigeonhole proves an eligible donor always
    exists there, so this is the only split warning a build can emit (#70).
    """
    if not split_result.below_min_sessions:
        return ()
    sessions = len(split_result.order)
    return (
        f"WARNING: {sessions} Session(s) — a three-way split needs at least "
        f"{MIN_SESSIONS_FOR_REPAIR}, so val and/or test are empty by arithmetic, not by fault.",
    )


def _split_section(split_result: SplitResult) -> list[str]:
    """The split table, then the repair moves, then the speaker-overlap note.

    Outcome-then-mechanism: what the operator got, how, then what the partition does *not* promise.
    Each block is blank-line separated and elided when it has nothing to say — except the table,
    which always prints.
    """
    lines = _split_table(split_result)
    for warning in _min_sessions_warning(split_result):
        lines += ["", warning]
    for move in split_result.moves:
        lines += [
            "",
            f"non-emptiness repair: moved session {move.session_id} "
            f"from {move.donor} to {move.recipient}",
            f"  (≥{MIN_SESSIONS_FOR_REPAIR} Sessions → val & test must be non-empty; "
            "ratios are best-effort)",
        ]
    if split_result.speaker_overlaps:
        lines.append("")
        lines += [_overlap_note(overlap) for overlap in split_result.speaker_overlaps]
    return lines


def _overlap_note(overlap: SpeakerOverlap) -> str:
    """ "Speaker spk_02 appears in train and test — test set is not speaker-independent" (ADR-0004).

    Every Split *after the first* is named as compromised: a Speaker spanning all three leaks into
    val and test alike, and naming only `test` would call a compromised validation set clean. The
    first Split is the reference the others fail to be independent *of* — arbitrary between any two,
    but :data:`~sdw.split.SPLIT_ORDER` makes the choice total and stable.
    """
    compromised = overlap.splits[1:]
    plural = "s are" if len(compromised) > 1 else " is"
    return (
        f"Speaker {overlap.speaker_id} appears in {_join(overlap.splits)} — "
        f"{_join(compromised)} set{plural} not speaker-independent"
    )


def _split_table(split_result: SplitResult) -> list[str]:
    """The configured target beside the realized count, on every build (ADR-0004, #19).

    Cell widths are computed from the rendered content, not fixed, so a large Dataset keeps its
    columns aligned. The percentage sits by both numbers because that is the comparison invited:
    `9.6 (80%)` against `6 (50%)` names the miss the raw counts only imply.
    """
    total = split_result.total_samples
    targets = [
        f"{split_result.targets[name]:.1f} ({_percent(split_result.targets[name], total)})"
        for name in SPLIT_ORDER
    ]
    realized = [
        f"{split_result.samples[name]} ({_percent(split_result.samples[name], total)})"
        for name in SPLIT_ORDER
    ]

    name_w = max(len("split"), *(len(name) for name in SPLIT_ORDER))
    target_w = max(len("target"), *(len(cell) for cell in targets))
    realized_w = max(len("realized"), *(len(cell) for cell in realized))

    header = f"{'split':<{name_w}}  {'target':>{target_w}}  {'realized':>{realized_w}}"
    return [header] + [
        f"{name:<{name_w}}  {target:>{target_w}}  {real:>{realized_w}}"
        for name, target, real in zip(SPLIT_ORDER, targets, realized, strict=True)
    ]


def _percent(value: float, total: int) -> str:
    """``value`` as a whole-number percentage of ``total``; ``0%`` for an empty Dataset.

    Whole numbers because the comparison is coarse (80 against 50); a decimal place would widen
    every cell to say nothing an operator acts on.
    """
    if total <= 0:
        return "0%"
    return f"{value / total * 100:.0f}%"


def _join(names: Sequence[str]) -> str:
    """``"train and test"`` / ``"train, val and test"`` — prose, because the note is a sentence."""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"
