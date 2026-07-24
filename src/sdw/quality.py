"""Measure each Recording's audio, flag what crosses a threshold, and render the digest (#26).

The third pipeline stage, and the one that completes `validate`. Reads the decoded Original and the
Normalized samples (#25) and returns :class:`QualityMetrics` — seven numbers plus advisory flags.
Nothing here aborts a run, drops a Recording, or changes an exit code — a structural failure is
ADR-0005's hard error, upstream; a flag here is descriptive metadata a consumer may filter on
(ADR-0007). Clipping reads the Original (pre-resample), the other
metrics the Normalized; what each check *means* is fixed by the constants below, and only its
threshold is a :class:`~sdw.config.QualityConfig` knob — two configs cannot disagree about what
"clipped" is while minting indistinguishable `dataset_version`s (ADR-0007). The audio is never
modified: the active-region trim is a measurement window, not an edit.
"""

from collections.abc import Sequence
from dataclasses import dataclass, fields

import numpy as np
import numpy.typing as npt

from sdw.config import QualityConfig
from sdw.normalize import TARGET_SAMPLE_RATE, NormalizedAudio

# Floor for `20*log10(0)`, otherwise -inf and unserializable (ADR-0007).
DBFS_FLOOR = -120.0

# A clip run: >= 3 consecutive samples at >= 0.99 FS (ADR-0007). Sample peak only, no true-peak
# oversampling; 0.99 catches ADCs that saturate a code below max.
CLIP_RUN_MIN = 3
CLIP_THRESHOLD = 0.99

# Silence framing: 20 ms non-overlapping frames, plus a minimum-duration guard on the leading and
# trailing runs so a natural pause is not reported as head/tail silence (ADR-0007).
SILENCE_FRAME_S = 0.02
MIN_SILENCE_RUN_S = 0.2
SILENCE_FRAME_SAMPLES = int(SILENCE_FRAME_S * TARGET_SAMPLE_RATE)
MIN_SILENCE_RUN_SAMPLES = int(MIN_SILENCE_RUN_S * TARGET_SAMPLE_RATE)

# The v0.1 flag vocabulary, in full (ADR-0007). Silence raises nothing — a pause is reported, not
# flagged. `flags` is always ordered by this tuple, so two runs agree byte for byte.
FLAG_CLIPPING = "clipping"
FLAG_LOW_VOLUME = "low_volume"
FLAG_DURATION_OUT_OF_RANGE = "duration_out_of_range"
FLAGS = (FLAG_CLIPPING, FLAG_LOW_VOLUME, FLAG_DURATION_OUT_OF_RANGE)

# Precision per metric (ADR-0007): dBFS 2 dp, ratios 4 dp, seconds 3 dp. Public because image titles
# and the Manifest's `duration` render the same quantities and must agree by construction, not by
# holding the same literals (#32, #54). These govern how many places a number is worth, not how it
# is spelled; moving one must move everywhere the metric is written or a build ships two answers for
# one Recording.
DBFS_DP = 2
RATIO_DP = 4
SECONDS_DP = 3

# Which precision each metric takes. Private: the constants above are the decision, this only maps
# fields to them. Not the source of truth for which metrics exist — :meth:`QualityMetrics.rounded`
# walks the dataclass, and a field with no entry here raises on the next render rather than dropping
# from the record in silence (#68).
_PRECISION = {
    "duration_s": SECONDS_DP,
    "peak_dbfs": DBFS_DP,
    "clip_ratio": RATIO_DP,
    "active_rms_dbfs": DBFS_DP,
    "leading_silence_s": SECONDS_DP,
    "trailing_silence_s": SECONDS_DP,
    "silence_ratio": RATIO_DP,
}


@dataclass(frozen=True)
class QualityMetrics:
    """One Recording's seven measurements plus the flags they tripped.

    All seven are reported, clean or not; `flags` is ordered by :data:`FLAGS`, empty when clean.
    """

    duration_s: float
    peak_dbfs: float
    clip_ratio: float
    active_rms_dbfs: float
    leading_silence_s: float
    trailing_silence_s: float
    silence_ratio: float
    flags: tuple[str, ...]

    def rounded(self) -> dict[str, float]:
        """The numeric metrics at ADR-0007 precision, keyed by name in declaration order (#68).

        The dict `quality.jsonl` is built from. Rounded here, not at measurement, so full-precision
        floats stay on the dataclass for the digest and image titles, and two runs within a ULP
        serialize identically — ADR-0008 needs no tolerance (#54). Declaration order *is* a line's
        key order, so reordering the fields above is an output change a `dataset_version` mismatch
        can't catch (ADR-0010); ``test_key_order_is_fixed_not_insertion_dependent`` guards it.
        """
        return {
            field.name: round(getattr(self, field.name), _PRECISION[field.name])
            for field in fields(self)
            if field.name != "flags"
        }


def measure(audio: NormalizedAudio, config: QualityConfig) -> QualityMetrics:
    """Measure ``audio`` and derive its flags. Pure: reads arrays, touches nothing."""
    peak_dbfs, clip_ratio = _clipping(audio.original)
    silence = _silence(audio.samples, config.silence_threshold_dbfs)
    active_rms_dbfs = _dbfs(_rms(silence.active_region(audio.samples)))
    duration_s = len(audio.samples) / TARGET_SAMPLE_RATE

    flags = tuple(
        flag
        for flag, tripped in (
            (FLAG_CLIPPING, clip_ratio > 0.0),
            (FLAG_LOW_VOLUME, active_rms_dbfs < config.low_volume_rms_dbfs),
            (
                FLAG_DURATION_OUT_OF_RANGE,
                duration_s < config.duration_min_s or duration_s > config.duration_max_s,
            ),
        )
        if tripped
    )
    return QualityMetrics(
        duration_s=duration_s,
        peak_dbfs=peak_dbfs,
        clip_ratio=clip_ratio,
        active_rms_dbfs=active_rms_dbfs,
        leading_silence_s=silence.leading_s,
        trailing_silence_s=silence.trailing_s,
        silence_ratio=silence.ratio,
        flags=flags,
    )


# --- Clipping (measured on the Original, pre-resample) ----------------------------------------


def _clipping(original: npt.NDArray[np.float64]) -> tuple[float, float]:
    """``(peak_dbfs, clip_ratio)`` over the decoded Original.

    Runs are found *within* a channel: interleaving channels would stitch unrelated samples into a
    phantom run. `peak_dbfs` is the max across channels, `clip_ratio` the clipped-run samples over
    ``frames x channels``, so the flag trips if any channel clipped.
    """
    channels = original if original.ndim == 2 else original.reshape(-1, 1)
    magnitude = np.abs(channels)
    clipped = sum(
        _run_sample_count(magnitude[:, c] >= CLIP_THRESHOLD) for c in range(channels.shape[1])
    )
    peak = float(magnitude.max()) if magnitude.size else 0.0
    return _dbfs(peak), clipped / magnitude.size


def _run_sample_count(mask: npt.NDArray[np.bool_]) -> int:
    """How many samples of ``mask`` belong to a run of >= :data:`CLIP_RUN_MIN` consecutive Trues.

    A lone full-scale sample is a transient, not a clip run. Counted on run boundaries (the diff of
    the padded mask) so the whole channel is one vectorized pass, not a Python loop.
    """
    if not mask.any():
        return 0
    edges = np.flatnonzero(np.diff(np.concatenate(([False], mask, [False])).astype(np.int8)))
    lengths = edges[1::2] - edges[0::2]
    return int(lengths[lengths >= CLIP_RUN_MIN].sum())


# --- Silence and the active region (measured on the Normalized) --------------------------------


@dataclass(frozen=True)
class _Silence:
    """The silence measurements plus the active window the low-volume check reuses.

    All three numbers are report-only — silence raises no flag (ADR-0007).
    """

    leading_s: float
    trailing_s: float
    ratio: float
    active_start: int
    active_end: int

    def active_region(self, samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """``samples`` narrowed to first-to-last non-silent frame — a measurement trim only.

        Empty when every frame is silent, flooring `active_rms_dbfs` to -120 and tripping
        `low_volume` — the mic-level collapse the check exists to catch.
        """
        return samples[self.active_start : self.active_end]


def _silence(samples: npt.NDArray[np.float64], threshold_dbfs: float) -> _Silence:
    """Frame ``samples`` into 20 ms non-overlapping frames and locate the silent ones.

    A trailing partial frame folds into the last frame rather than forming its own, so no frame is
    ever measured over a window too short to have a meaningful RMS.
    """
    bounds = _frame_bounds(len(samples))
    silent = np.array(
        [_dbfs(_rms(samples[start:end])) < threshold_dbfs for start, end in bounds], dtype=bool
    )
    active = np.flatnonzero(~silent)
    if active.size == 0:
        # Wholly silent: one run spanning the Recording, counted as both leading and trailing, no
        # active region. The guard still applies, so a 0.1 s dead Recording reports 0.0 like a 0.1 s
        # pause; `low_volume`, not silence, is what says the Recording is empty.
        return _Silence(
            leading_s=_guarded(len(samples)),
            trailing_s=_guarded(len(samples)),
            ratio=1.0,
            active_start=0,
            active_end=0,
        )

    active_start = bounds[active[0]][0]
    active_end = bounds[active[-1]][1]
    return _Silence(
        leading_s=_guarded(active_start),
        trailing_s=_guarded(len(samples) - active_end),
        ratio=float(silent.mean()),
        active_start=active_start,
        active_end=active_end,
    )


def _frame_bounds(num_samples: int) -> list[tuple[int, int]]:
    """``(start, end)`` per 20 ms frame, the last one absorbing any partial remainder."""
    num_frames = max(1, num_samples // SILENCE_FRAME_SAMPLES)
    starts = [i * SILENCE_FRAME_SAMPLES for i in range(num_frames)]
    return [(start, start + SILENCE_FRAME_SAMPLES) for start in starts[:-1]] + [
        (starts[-1], num_samples)
    ]


def _guarded(run_samples: int) -> float:
    """A leading/trailing run in seconds, or 0.0 if it is shorter than the 0.2 s ``D_min`` guard."""
    return _seconds(run_samples) if run_samples >= MIN_SILENCE_RUN_SAMPLES else 0.0


def _seconds(num_samples: int) -> float:
    return num_samples / TARGET_SAMPLE_RATE


# --- Level math ---------------------------------------------------------------------------------


def _rms(samples: npt.NDArray[np.float64]) -> float:
    """Root mean square over normalized amplitude. An empty window is 0.0, which floors to -120."""
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def _dbfs(amplitude: float) -> float:
    """Raw ``20*log10`` — deliberately no AES17 offset, so a full-scale sine reads about -3 dBFS.

    The offset would hide math from an inspector reproducing a number by hand (ADR-0007).
    """
    if amplitude <= 0.0:
        return DBFS_FLOOR
    return max(DBFS_FLOOR, float(20.0 * np.log10(amplitude)))


# --- The human digest ---------------------------------------------------------------------------


def render_digest(results: Sequence[tuple[str, QualityMetrics]]) -> str:
    """The human quality digest: a per-flag tally, then one line per ``(Recording, flag)`` pair.

    A Recording with two flags gets two lines — a line's evidence is per flag (ADR-0007). The same
    text `validate` prints and `build` folds into `reports/summary.txt`. Clean Recordings are
    counted, not listed — the digest is a worklist. Deterministic: no wall-clock, host, or set
    iteration. The tally lists all three flags even at zero, so the shape is fixed and a diff shows
    a count change rather than a line appearing; only the flagged list is elided when empty.
    """
    flagged = [(rid, metrics) for rid, metrics in results if metrics.flags]
    lines = [
        f"Quality: {len(results)} recordings — "
        f"{len(results) - len(flagged)} clean, {len(flagged)} flagged"
    ]
    width = max(len(flag) for flag in FLAGS)
    for flag in FLAGS:
        tally = sum(1 for _, metrics in results if flag in metrics.flags)
        lines.append(f"  {flag:<{width}} {tally}")

    if flagged:
        lines += ["", "Flagged:"]
        lines += [
            f"  {rid} {flag:<{width}} {_evidence(flag, metrics)}"
            for rid, metrics in flagged
            for flag in metrics.flags
        ]
    return "\n".join(lines) + "\n"


def _evidence(flag: str, metrics: QualityMetrics) -> str:
    """The numbers that justify one flag — the operator should not have to open quality.jsonl.

    Fixed decimal places, not :func:`round`: `round` drops trailing zeros, rendering a full-scale
    peak as ``0.0dBFS`` beside a ``-0.02dBFS`` — a ragged column instead of a scannable one.
    """
    if flag == FLAG_CLIPPING:
        return (
            f"peak={metrics.peak_dbfs:.{DBFS_DP}f}dBFS clip_ratio={metrics.clip_ratio:.{RATIO_DP}f}"
        )
    if flag == FLAG_LOW_VOLUME:
        return f"active_rms={metrics.active_rms_dbfs:.{DBFS_DP}f}dBFS"
    # The vocabulary is exactly three (ADR-0007), so the remaining case is duration; a fourth flag
    # would have to extend this cascade.
    return f"duration={metrics.duration_s:.{SECONDS_DP}f}s"
