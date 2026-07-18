"""Measure each Recording's audio, flag what crosses a threshold, and render the digest (#26).

The third pipeline stage, and the one that completes `validate`. Normalization (#25) handed back
both the decoded Original and the Normalized samples; this stage reads those arrays and returns
:class:`QualityMetrics` — seven numbers plus zero or more advisory flags. Nothing here can abort a
run, drop a Recording, or change an exit code: a structural failure is ADR-0005's hard error, and a
quality flag is descriptive metadata a downstream consumer may filter on. All attempts are data.

Three facts pin the shape:

- **Clipping reads the Original, everything else reads the Normalized.** Clipping is a flat-top
  artifact of the *capture*: the downmix can average a clipped channel away and soxr smears the
  flat top and adds overshoot, so a post-resample clip metric is systematically wrong in both
  directions. The other three metrics describe what the Sample actually ships, so they read the
  Normalized (ADR-0007).

- **What a check means is fixed; only where its threshold sits is a knob.** The constants below —
  the -120 floor, the 3-sample / 0.99 FS clip run, the 20 ms frame, the 0.2 s guard — are not
  configurable, so two configs cannot disagree about what "clipped" is while minting
  indistinguishable `dataset_version`s. :class:`~sdw.config.QualityConfig`'s four knobs move
  thresholds only.

- **Transparent math over clever math.** RMS is the raw ``20*log10(sqrt(mean(s^2)))`` convention
  with no AES17 offset, so an inspector can reproduce any number here from the PCM by hand. Nothing
  is model-based, nothing is gated, and the audio is never modified — the active-region trim is a
  *measurement* window, not an edit.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sdw.config import QualityConfig
from sdw.normalize import TARGET_SAMPLE_RATE, NormalizedAudio

# The floor for `20*log10(0)`, which is otherwise -inf and unserializable. Well below anything a
# real capture reaches, so a floored value reads unambiguously as "silent" (ADR-0007).
DBFS_FLOOR = -120.0

# A clip run: >= 3 consecutive samples at >= 0.99 FS. The 0.99 tolerance catches ADCs that saturate
# a code or two below max, and applies uniformly across any Original bit depth once decoded to
# float. Sample peak only — no true-peak oversampling.
CLIP_RUN_MIN = 3
CLIP_THRESHOLD = 0.99

# Silence framing: 20 ms non-overlapping frames (320 samples at 16 kHz), and a minimum-duration
# guard on the leading and trailing runs so a natural pause is not reported as head/tail silence.
SILENCE_FRAME_S = 0.02
MIN_SILENCE_RUN_S = 0.2
SILENCE_FRAME_SAMPLES = int(SILENCE_FRAME_S * TARGET_SAMPLE_RATE)
MIN_SILENCE_RUN_SAMPLES = int(MIN_SILENCE_RUN_S * TARGET_SAMPLE_RATE)

# The v0.1 flag vocabulary, in full. Silence contributes metrics only and raises nothing: a natural
# pause is something to report, not something to flag. `flags` is always ordered by this tuple, so
# two runs agree byte for byte.
FLAG_CLIPPING = "clipping"
FLAG_LOW_VOLUME = "low_volume"
FLAG_DURATION_OUT_OF_RANGE = "duration_out_of_range"
FLAGS = (FLAG_CLIPPING, FLAG_LOW_VOLUME, FLAG_DURATION_OUT_OF_RANGE)

# Precision for every rendered form of these metrics (ADR-0007): dBFS 2 dp, ratios 4 dp, seconds
# 3 dp. Applied at render time rather than at measurement, so the digest and a later quality.jsonl
# round one set of full-precision numbers the same way instead of rounding twice.
_DBFS_DP = 2
_RATIO_DP = 4
_SECONDS_DP = 3


@dataclass(frozen=True)
class QualityMetrics:
    """One Recording's measurements plus the flags they tripped.

    The seven metrics are always reported, flags or not — a clean Recording is as much a row of the
    quality report as a flagged one. `flags` is ordered by :data:`FLAGS` and is empty when clean.
    """

    duration_s: float
    peak_dbfs: float
    clip_ratio: float
    active_rms_dbfs: float
    leading_silence_s: float
    trailing_silence_s: float
    silence_ratio: float
    flags: tuple[str, ...]


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

    Runs are found *within* a channel, because a flat top is a per-converter event: interleaving
    channels would stitch unrelated samples into a phantom run and splitting one real run across
    channels would erase it. `peak_dbfs` is the max across channels and `clip_ratio` the total
    clipped-run samples over ``frames x channels``, so the flag trips if any channel clipped.
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

    A lone sample at full scale is a transient, not a clip run, and contributes nothing. Counting is
    done on run boundaries — the diff of the padded mask marks each run's start and end — so the
    whole channel is one vectorized pass rather than a Python loop over samples.
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

    All three reported numbers are report-only: silence raises no flag, so a Recording that opens
    with a breath and closes with a pause is described, never flagged.
    """

    leading_s: float
    trailing_s: float
    ratio: float
    active_start: int
    active_end: int

    def active_region(self, samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """``samples`` narrowed to first-to-last non-silent frame — a measurement trim only.

        Empty when every frame is silent, which floors `active_rms_dbfs` to -120 and correctly
        trips `low_volume`: a Recording with nothing in it is exactly the mic-level collapse the
        check exists to catch.
        """
        return samples[self.active_start : self.active_end]


def _silence(samples: npt.NDArray[np.float64], threshold_dbfs: float) -> _Silence:
    """Frame ``samples`` into 20 ms non-overlapping frames and locate the silent ones.

    A trailing partial frame folds into the last frame rather than forming a short frame of its
    own, so a 0.5 s Recording is 25 frames and the last one is simply a little longer — no frame
    is ever measured over a window too short to have a meaningful RMS.
    """
    bounds = _frame_bounds(len(samples))
    silent = np.array(
        [_dbfs(_rms(samples[start:end])) < threshold_dbfs for start, end in bounds], dtype=bool
    )
    active = np.flatnonzero(~silent)
    if active.size == 0:
        # Wholly silent: one run spanning the whole Recording, which is both the leading and the
        # trailing run, and no active region at all. The guard still applies — it applies to *the
        # leading and trailing runs*, and this is one, so a 0.1 s dead Recording reports 0.0 exactly
        # as a 0.1 s leading pause does. `low_volume` is what says this Recording is empty; silence
        # never does.
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

    The offset is a sine-calibration convenience v0.1 does not need, and it hides math from an
    inspector reproducing a number by hand (ADR-0007).
    """
    if amplitude <= 0.0:
        return DBFS_FLOOR
    return max(DBFS_FLOOR, float(20.0 * np.log10(amplitude)))


# --- The human digest ---------------------------------------------------------------------------


def render_digest(results: Sequence[tuple[str, QualityMetrics]]) -> str:
    """The human quality digest: a per-flag tally, then one line per flagged Recording.

    The same text `validate` prints to stdout and `build` folds into `reports/summary.txt`, so the
    two commands can never describe one input differently. Clean Recordings are counted but not
    listed — the digest is a worklist. Deterministic: no wall-clock, no host, no set iteration.

    The tally lists all three flags even at zero, so the digest has one fixed shape: an operator
    diffing two runs sees a count change rather than a line appear, and a zero is itself the useful
    answer to "did anything clip?". Only the flagged *list* is elided when empty.
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

    Fixed decimal places rather than :func:`round`, which drops trailing zeros and would render an
    exactly-full-scale peak as ``0.0dBFS`` next to a neighbouring ``-0.02dBFS``. A column of
    same-width numbers is scannable; a ragged one is not.
    """
    if flag == FLAG_CLIPPING:
        return (
            f"peak={metrics.peak_dbfs:.{_DBFS_DP}f}dBFS "
            f"clip_ratio={metrics.clip_ratio:.{_RATIO_DP}f}"
        )
    if flag == FLAG_LOW_VOLUME:
        return f"active_rms={metrics.active_rms_dbfs:.{_DBFS_DP}f}dBFS"
    # `flags` only ever holds names from :data:`FLAGS`, and the vocabulary is exactly three, so the
    # remaining case is duration. A fourth flag would be an ADR-0007 change, and this cascade is
    # one of the places that would have to change with it.
    return f"duration={metrics.duration_s:.{_SECONDS_DP}f}s"
