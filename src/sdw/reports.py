"""Render the two report artifacts a build emits: `quality.jsonl` and `summary.txt` (#32).

The emitted record of what the run measured and decided, and the reason `--data-out` is explicable
on its own. :mod:`sdw.quality` returned metrics as data and :mod:`sdw.split` returned its
disclosures as data; neither rendered anything durable. This module is where both become files.

Four facts pin the shape:

- **Two artifacts because there are two readers.** `quality.jsonl` is one line per kept Recording,
  sorted by `id` and joinable to the manifest on it, for a consumer that filters; `summary.txt` is
  a digest that omits clean Recordings, for an operator who wants the state of a Dataset at a
  glance. Neither is derivable from the other without work, so both are written (ADR-0007).

- **Every disclosure prints unconditionally.** The split table appears on every build with no
  threshold and no conditional, because an operator who configures 80-10-10 and receives 50-25-25
  needs to see the target beside the realized count to read that as arithmetic — whole Sessions are
  indivisible — rather than as a bug (ADR-0004). The per-flag tally lists all three flags even at
  zero for the same reason: a fixed shape means a diff of two runs shows a count change rather than
  a line appearing.

- **The exceptions are the notes that would be noise.** The `Flagged:` list is elided when nothing
  is flagged, the repair lines when nothing was repaired, and the speaker-overlap note on
  single-speaker data — where the overlap is unavoidable and naming it would fire on every build
  while pointing at nothing the operator could act on. ``SplitResult.speaker_overlaps`` is already
  empty in that case, so the suppression is the splitter's and this module only inherits it.

- **Both artifacts are deterministic.** No wall-clock, no host facts, no set iteration, no
  dictionary built from anything but :data:`~sdw.split.SPLIT_ORDER` — so ADR-0008's exact
  golden-file comparison holds with no tolerance machinery. Wall-clock and run duration, if they
  are ever reported at all, go to stdout only (ADR-0012).
"""

from collections.abc import Sequence
from pathlib import Path

from sdw.quality import DBFS_DP, RATIO_DP, SECONDS_DP, QualityMetrics, render_digest
from sdw.serialization import render_jsonl
from sdw.split import MIN_SESSIONS_FOR_REPAIR, SPLIT_ORDER, SpeakerOverlap, SplitResult

REPORTS_DIR = "reports"
QUALITY_JSONL = "quality.jsonl"
SUMMARY_TXT = "summary.txt"

# Decimal places per field *type*, not per field (ADR-0007). Imported from :mod:`sdw.quality`
# rather than restated, because the digest and this file round the same full-precision numbers and
# a drift between them would put two different values for one metric in one build. Rounding at
# render is what lets the file be an exact golden — two runs that agree to within a float ULP still
# serialize identically, so no test needs a tolerance.

# The line's numeric fields: key order *and* precision in one table, because they are one decision.
# Two parallel structures would let a key exist with no precision beside it, and that mismatch would
# surface as a KeyError at render time rather than as an obviously incomplete edit here. `id` leads
# and `flags` trails around them — the file is sorted by `id` and joined on it, and `flags` is the
# only variable-length field (ADR-0007).
_METRIC_FIELDS = (
    ("duration_s", SECONDS_DP),
    ("peak_dbfs", DBFS_DP),
    ("clip_ratio", RATIO_DP),
    ("active_rms_dbfs", DBFS_DP),
    ("leading_silence_s", SECONDS_DP),
    ("trailing_silence_s", SECONDS_DP),
    ("silence_ratio", RATIO_DP),
)

QUALITY_KEYS = ("id", *(key for key, _ in _METRIC_FIELDS), "flags")


def write_reports(
    directory: Path,
    results: Sequence[tuple[str, QualityMetrics]],
    split_result: SplitResult,
) -> None:
    """Write both artifacts into ``directory`` — the staging tree's `reports/` (ADR-0003).

    Called inside `build`'s staging window, so a hard error after this point still leaves no
    durable output: these files are committed by the same rename as everything else.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / QUALITY_JSONL).write_text(render_quality_jsonl(results), encoding="utf-8")
    (directory / SUMMARY_TXT).write_text(render_summary(results, split_result), encoding="utf-8")


# --- The machine-readable report ----------------------------------------------------------------


def render_quality_jsonl(results: Sequence[tuple[str, QualityMetrics]]) -> str:
    """One JSON object per kept Recording, sorted by `id`, clean lines included.

    Clean lines are present because the file is the *record* of what was measured, not a worklist:
    a consumer asking "was this Sample checked, and what did it measure?" must get an answer for
    every Sample, and an absent line cannot distinguish "clean" from "never measured". `summary.txt`
    is the worklist, and it is the one that omits them.

    Sorted by `id` rather than by input order so that the file is stable under a reordering of
    `recordings.csv` — the same Dataset described in a different row order yields the same bytes.

    The join is :func:`~sdw.serialization.render_jsonl`, shared with the Manifest, so this file and
    `train.jsonl` cannot come to disagree about the JSONL byte format (#54).
    """
    ordered = sorted(results, key=lambda result: result[0])
    return render_jsonl(_line(rid, metrics) for rid, metrics in ordered)


def _line(recording_id: str, metrics: QualityMetrics) -> dict[str, object]:
    """One Recording's line, rounded per field type, in :data:`QUALITY_KEYS` order.

    ``round`` rather than fixed-decimal string formatting, because JSON has no notion of trailing
    zeros to preserve and a numeric literal keeps the field a number for any consumer that parses
    it. The human digest formats to fixed width for a different reason — column alignment — which
    is why the two renderings differ.
    """
    line: dict[str, object] = {"id": recording_id}
    for key, places in _METRIC_FIELDS:
        line[key] = round(getattr(metrics, key), places)
    line["flags"] = list(metrics.flags)
    return line


# --- The human summary ---------------------------------------------------------------------------


def render_summary(results: Sequence[tuple[str, QualityMetrics]], split_result: SplitResult) -> str:
    """The operator's digest: the quality section, then the split section.

    The below-three-Sessions warning appears in *both* sections rather than once (ADR-0004). It is a
    fact about the Dataset that changes how either section should be read — the split table's
    realized counts and the quality tally are both describing a Dataset too small to partition — and
    an operator scanning to the section they came for must not be able to miss it. It is prefixed
    here rather than passed into :func:`~sdw.quality.render_digest`, so that `validate`, which never
    runs the splitter, cannot end up with a digest that differs from `build`'s by a parameter it has
    no way to fill (ADR-0007).
    """
    sections = [f"{warning}\n" for warning in _min_sessions_warning(split_result)]
    sections += [
        render_digest(results),
        "\n".join(_split_section(split_result)) + "\n",
    ]
    return "\n".join(sections)


def _min_sessions_warning(split_result: SplitResult) -> tuple[str, ...]:
    """The unmissable warning for a Dataset below :data:`~sdw.split.MIN_SESSIONS_FOR_REPAIR`.

    Produce-and-flag: a three-way split of two Sessions is arithmetically impossible, so the build
    assigns what it can, emits valid empty Splits, and says so — it never aborts (ADR-0004). Empty
    Splits at or above three Sessions would be a different warning about a different thing (a repair
    that failed to buy a promise the tool made), and this one does not claim to cover it.
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

    Ordered outcome-then-mechanism: the table says what the operator got, the moves say how, and the
    overlap note says what the partition does *not* promise. Each block is separated by a blank line
    and every one of them is elided when it has nothing to say — except the table, which never is.
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

    Every Split *after the first* is named as compromised, not just the last one. A Speaker spanning
    all three leaks into val and test alike, and naming only `test` would tell an operator their
    validation set was clean when it is not. The first Split is the reference the others fail to be
    independent *of* — arbitrary between any two, but :data:`~sdw.split.SPLIT_ORDER` makes the
    choice total and stable, and it lands on `train`, which is the one nobody expects to be held
    out anyway.
    """
    compromised = overlap.splits[1:]
    plural = "s are" if len(compromised) > 1 else " is"
    return (
        f"Speaker {overlap.speaker_id} appears in {_join(overlap.splits)} — "
        f"{_join(compromised)} set{plural} not speaker-independent"
    )


def _split_table(split_result: SplitResult) -> list[str]:
    """The configured target beside the realized count, on every build (ADR-0004, #19).

    Cell widths are computed from the rendered content rather than fixed, so a Dataset of a hundred
    thousand Samples keeps its columns aligned instead of overflowing a hand-chosen constant. The
    percentage is shown next to both numbers because that is the comparison being invited: `9.6
    (80%)` against `6 (50%)` names the 30-point miss the raw counts only imply.
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

    Whole numbers because the comparison the table invites is coarse — 80 against 50 — and a second
    decimal place would widen every cell to say nothing an operator acts on.
    """
    if total <= 0:
        return "0%"
    return f"{value / total * 100:.0f}%"


def _join(names: Sequence[str]) -> str:
    """``"train and test"`` / ``"train, val and test"`` — prose, because the note is a sentence."""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"
