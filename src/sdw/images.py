"""Render a waveform and a spectrogram PNG for every Recording (#31, ADR-0011).

The fifth pipeline stage, and the only one whose output no consumer ever sees: an Image is an
**operator inspection aid**, not a dataset deliverable, and it sits outside `dataset_version`
(ADR-0010). Both PNGs render from the Normalized samples, so every image shares one 8 kHz Nyquist
and one amplitude scale and any two are comparable.

Four facts pin the shape:

- **An image states measurements, never verdicts.** The title renders the peak and RMS the quality
  stage already computed; no flag, no threshold, and no prompt text appears. The levels are *not*
  recomputed here, and cannot be: :func:`render` takes the :class:`~sdw.quality.QualityMetrics`
  record as a parameter and this module imports none of the math that produces one. ADR-0007 takes
  `peak_dbfs` on the **Original** (pre-resample) and the low-volume RMS over the **active region**
  (silence excluded), so recomputing either from the plotted signal would put a title and a
  `quality.jsonl` line into disagreement about one Recording — both correct, neither explained.
  The labels admit the gap: ``peak (orig)`` and ``RMS (active)``.

- **The scales are absolute and fixed.** Waveform y is always -1.0 .. +1.0 and magnitude is always
  -80 .. 0 dBFS, clamped — never autoscaled, never per-image normalized. A quiet Recording
  therefore *looks* quiet instead of being autoscaled into a lie, the same colour means the same
  energy across any two Images, and an Image can never contradict a Quality flag. Only x is
  per-recording (0 .. duration), because duration is already legible everywhere else and fixing it
  to `duration_max_s` would couple this stage to a quality threshold.

- **Constants, not config — there is no `[images]` section.** The `dataset_version` preimage hashes
  the effective config (ADR-0010), so any `[images]` key would mint a new dataset identity for a
  byte-identical manifest. Changing a constant below is a *tool* change, which `tool_version`
  already covers. This stage reads no config at all.

- **Determinism is same-machine byte-identity.** Agg, an explicit rcParams style context (so a
  user's `~/.matplotlib/matplotlibrc` cannot silently alter output on one machine and not another),
  pinned figsize and DPI, and matplotlib's `Software` tEXt chunk stripped. Cross-machine identity
  is explicitly not sought — freetype rasterizes glyphs differently across versions — and nothing
  needs it: ADR-0008's test builds twice on one machine.

A render failure is a tool bug, not a property of the data — every decoded Recording is renderable
by construction — so it raises :class:`~sdw.errors.HardError` and aborts the build. Warn-and-skip
would invent a third outcome in a two-outcome pipeline and make a missing PNG indistinguishable
from one never rendered.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import matplotlib
import numpy as np
import numpy.typing as npt
from scipy.signal import ShortTimeFFT
from scipy.signal.windows import hann

from sdw.errors import HardError
from sdw.ingest import Recording
from sdw.normalize import NormalizedAudio
from sdw.quality import DBFS_DP, SECONDS_DP, QualityMetrics

# Headless, and set before pyplot is imported so no display backend is ever probed.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow the backend selection)
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# Figure geometry (ADR-0011). Wide suits a time series; the spectrogram is taller for its frequency
# axis and colorbar. 100 DPI keeps each PNG in the ~50-150 KB band.
DPI = 100
WAVEFORM_FIGSIZE = (10.0, 3.0)
SPECTROGRAM_FIGSIZE = (10.0, 4.0)
WAVEFORM_SIZE_PX = (int(WAVEFORM_FIGSIZE[0] * DPI), int(WAVEFORM_FIGSIZE[1] * DPI))
SPECTROGRAM_SIZE_PX = (int(SPECTROGRAM_FIGSIZE[0] * DPI), int(SPECTROGRAM_FIGSIZE[1] * DPI))

# The two absolute scales, and the reason this module exists in the shape it does. Neither is a
# function of the signal being plotted.
WAVEFORM_YLIM = (-1.0, 1.0)
DB_RANGE = (-80.0, 0.0)

# STFT framing: 25 ms window / 10 ms hop / Hann — the Whisper/NeMo/Kaldi frontend convention, so
# what an operator reads is what a v0.2 model eats. 201 bins spanning 0 .. 8 kHz, fixed by the
# 16 kHz Normalized rate.
N_FFT = 400
HOP = 160

# The shortest signal `ShortTimeFFT` will accept: half a window, rounded up. Shorter Recordings are
# zero-extended to it rather than refused — see :func:`_padded`.
_MIN_STFT_SAMPLES = -(-N_FFT // 2)

# `magma`: perceptually uniform, colorblind-safe, greyscale-safe, and the conventional map for a
# dB spectrogram.
COLORMAP = "magma"

# The dB floor for `20*log10(0)`, which is otherwise -inf. Well below `DB_RANGE`'s bottom, so it
# clamps to the darkest colour like any other inaudible bin — this is a plotting guard, not a
# measurement (ADR-0007 owns the reported -120 floor).
_MAGNITUDE_FLOOR = 1e-12

# The subtree this module writes into, owned here as `reports` owns its own: every directory under
# `--data-out` is named by exactly one module, so the tree's shape is never reassembled from string
# literals in the code that composes the paths (ADR-0003).
IMAGES_DIR = "images"

# The filename suffixes. Images share the `recording_id` stem with the audio and the quality line,
# so every artifact for a Recording is one `ls` away (ADR-0003).
WAVEFORM_SUFFIX = ".waveform.png"
SPECTROGRAM_SUFFIX = ".spectrogram.png"

# Everything the render depends on that matplotlib would otherwise read from a user's matplotlibrc.
# Fonts are pinned to matplotlib's bundled DejaVu family: a system font list would resolve
# differently per machine and, worse, per machine over time.
_RC_PARAMS: dict[str, Any] = {
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "savefig.bbox": None,
    "savefig.pad_inches": 0.0,
    "savefig.transparent": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "font.size": 9.0,
    "axes.titlesize": 9.0,
    "axes.labelsize": 8.0,
    "xtick.labelsize": 7.0,
    "ytick.labelsize": 7.0,
    "axes.grid": False,
    "axes.linewidth": 0.8,
    "lines.linewidth": 0.5,
    "lines.antialiased": True,
    "text.usetex": False,
    "path.simplify": True,
    "path.simplify_threshold": 1.0 / 9.0,
    "agg.path.chunksize": 0,
}

# `Software: Matplotlib version X` is the one non-deterministic chunk matplotlib's PNG writer adds
# by default; it writes no timestamp. Setting it to None omits it, so a matplotlib upgrade does not
# change every byte of every image.
_PNG_METADATA: dict[str, Any] = {"Software": None}

# Fixed axes rectangles, in figure coordinates. Pinned rather than left to a layout engine so the
# plotted area is identical in every image regardless of tick-label width — and so the colorbar
# never shrinks the spectrogram's axes by an amount that depends on the data.
_WAVEFORM_AXES = (0.06, 0.17, 0.92, 0.70)
_SPECTROGRAM_AXES = (0.06, 0.13, 0.84, 0.77)
_COLORBAR_AXES = (0.92, 0.13, 0.02, 0.77)


def image_paths(recording_id: str, out_dir: Path) -> tuple[Path, Path]:
    """The two paths :func:`render` writes for ``recording_id``, waveform first.

    The naming rule in one place, so a caller that needs to name an Image — a report, a test — does
    not restate the convention and drift from it.
    """
    return (
        out_dir / f"{recording_id}{WAVEFORM_SUFFIX}",
        out_dir / f"{recording_id}{SPECTROGRAM_SUFFIX}",
    )


def render(
    audio: NormalizedAudio,
    metrics: QualityMetrics,
    recording: Recording,
    out_dir: Path,
) -> None:
    """Write both PNGs for ``recording`` into ``out_dir``, creating it if absent.

    ``metrics`` is rendered, never recomputed: this signature is the mechanism, not a convention —
    the values in the title can only be the quality stage's (ADR-0012). Raises
    :class:`~sdw.errors.HardError` if either render or write fails, which aborts the build and
    keeps `images/` a 1:1 mirror of the Manifest — a build never emits a partial `images/`.
    """
    waveform_path, spectrogram_path = image_paths(recording.recording_id, out_dir)
    heading = title(recording, metrics)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # `rc_context` is typed with a Literal key union that a module-level dict cannot satisfy;
        # every key below is a real rcParam, and a typo would raise at render time.
        with plt.rc_context(_RC_PARAMS):  # type: ignore[arg-type]
            _render_waveform(audio.samples, audio.sample_rate, heading, waveform_path)
            _render_spectrogram(audio.samples, audio.sample_rate, heading, spectrogram_path)
    except Exception as error:
        raise HardError(f"could not render images for {recording.recording_id}: {error}") from error


def title(recording: Recording, metrics: QualityMetrics) -> str:
    """The one-line heading both Images carry: identity, then measurements.

    Self-contained enough to read a level off the picture without opening `quality.jsonl`, and
    nothing more. The flags are deliberately absent — rendering them would couple this stage to
    `[quality]` thresholds, redraw every PNG when one moved, and duplicate a verdict into two
    artifacts that can drift apart. The prompt text is deliberately absent too: an
    arbitrary-length sentence forces wrapping and font-metric layout, the most determinism-hostile
    thing available.

    Precision is ADR-0007's, imported from :mod:`sdw.quality` rather than restated (#54): a title
    reading 1.23 s beside a `quality.jsonl` line reading 1.234 would describe one Recording in two
    precisions. Fixed decimal places rather than ``round`` — so a column of numbers keeps one width
    — is this module's formatting choice; the number of places is not.
    """
    return (
        f"{recording.recording_id} | {recording.speaker_id} | {recording.session_id} | "
        f"{metrics.duration_s:.{SECONDS_DP}f} s | "
        f"peak (orig) {metrics.peak_dbfs:.{DBFS_DP}f} dBFS | "
        f"RMS (active) {metrics.active_rms_dbfs:.{DBFS_DP}f} dBFS"
    )


@contextmanager
def _image(
    figsize: tuple[float, float],
    axes_rect: tuple[float, float, float, float],
    heading: str,
    path: Path,
) -> Iterator[tuple[Figure, Axes]]:
    """A titled figure on a pinned axes rectangle, written to ``path`` and always closed.

    Every Image shares this lifecycle, and each step of it is load-bearing for determinism: the
    fixed `add_axes` rectangle (no layout engine, so tick-label width cannot move the plotted
    area), the `Software`-stripped save, and the `finally` close, without which a build of any
    size leaks figures until matplotlib warns and then until the process is out of memory.
    """
    figure = plt.figure(figsize=figsize)
    try:
        axes = figure.add_axes(axes_rect)
        axes.set_title(heading)
        yield figure, axes
        figure.savefig(path, format="png", metadata=_PNG_METADATA)
    finally:
        plt.close(figure)


def _render_waveform(
    samples: npt.NDArray[np.float64], sample_rate: int, heading: str, path: Path
) -> None:
    """Amplitude against time, on a y-axis that is never a function of the signal.

    y is fixed at full scale because level is invisible otherwise: autoscale draws a -45 dBFS
    whisper and a -1 dBFS shout as the identical picture, silently contradicting `low_volume` —
    the single most common reason to open one of these. x is per-recording precisely because
    duration is *not* hidden: it is a manifest field, a summary number, and its own flag.
    """
    duration_s = len(samples) / sample_rate
    times = np.arange(len(samples), dtype=np.float64) / sample_rate

    with _image(WAVEFORM_FIGSIZE, _WAVEFORM_AXES, heading, path) as (_, axes):
        axes.plot(times, samples, color="#1f77b4")
        axes.set_xlim(0.0, duration_s)
        axes.set_ylim(*WAVEFORM_YLIM)
        axes.set_xlabel("time (s)")
        axes.set_ylabel("amplitude (full scale)")


def _render_spectrogram(
    samples: npt.NDArray[np.float64], sample_rate: int, heading: str, path: Path
) -> None:
    """Energy against time and frequency, on a colour scale that is never a function of the signal.

    Per-image dB normalization (dB relative to this file's own max, the common default) re-lies
    about level exactly as waveform autoscale does, and would put the spectrogram in direct
    contradiction with the fixed-scale waveform sitting beside it. The scale here is absolute, so
    the same colour means the same energy in any two Images and a quiet Recording renders dim.
    """
    duration_s = len(samples) / sample_rate
    decibels, plotted_s = stft_dbfs(samples, sample_rate)

    with _image(SPECTROGRAM_FIGSIZE, _SPECTROGRAM_AXES, heading, path) as (figure, axes):
        mesh = axes.imshow(
            decibels,
            origin="lower",
            aspect="auto",
            interpolation="nearest",
            extent=(plotted_s[0], plotted_s[1], 0.0, sample_rate / 2),
            cmap=COLORMAP,
            vmin=DB_RANGE[0],
            vmax=DB_RANGE[1],
        )
        # The x-axis is the waveform's, not the data's: the two Images of one Recording must align
        # in time, so the few milliseconds of unsupported frames at each end are left blank rather
        # than allowed to shift the axis.
        axes.set_xlim(0.0, duration_s)
        axes.set_xlabel("time (s)")
        axes.set_ylabel("frequency (Hz)")
        colorbar = figure.colorbar(mesh, cax=figure.add_axes(_COLORBAR_AXES))
        colorbar.set_label("magnitude (dBFS)")


def stft_dbfs(
    samples: npt.NDArray[np.float64], sample_rate: int
) -> tuple[npt.NDArray[np.float64], tuple[float, float]]:
    """The STFT magnitude in absolute dBFS clamped to :data:`DB_RANGE`, and the seconds it covers.

    The returned array is ``(201 bins, frames)`` spanning 0 .. 8 kHz, and ``plotted_s`` is the
    ``(start, end)`` time of the plotted region's outer edges — half a hop beyond the first and
    last frame centres, since a frame paints a pixel of width `hop`, not a line.

    Magnitude is scaled by ``2 / sum(window)`` so a bin's value is the amplitude of the sinusoid
    that produced it, on the same 0 .. 1 full-scale ruler the waveform uses — that is what makes
    the dB value *absolute* and comparable across images rather than an arbitrary FFT scale. The
    dB conversion is ADR-0007's raw ``20*log10``, with a magnitude floor standing in for -inf.
    Clamping (rather than letting matplotlib clip) makes the rendered range explicit in the data.

    Where the Recording is long enough to have them, only frames whose whole window lies inside it
    are kept: the border frames a zero-padded STFT also produces see a window that is part signal
    and part silence, which reads as a broadband vertical stripe at each end — a picture of the
    padding, not of the audio. A Recording too short to hold two such frames keeps the padded
    frames instead, because a Recording is *always* renderable: a 5 ms Original is valid data
    carrying at most an advisory `duration_out_of_range`, and it must produce a picture, not a
    render failure that would abort the whole build.
    """
    window = hann(N_FFT, sym=False)
    transform = ShortTimeFFT(window, hop=HOP, fs=sample_rate, scale_to=None, fft_mode="onesided")
    signal = _padded(samples)
    first, last = _frame_range(transform, len(signal))
    magnitude = np.abs(transform.stft(signal, p0=first, p1=last)) * (2.0 / window.sum())
    decibels = 20.0 * np.log10(np.maximum(magnitude, _MAGNITUDE_FLOOR))

    times = transform.t(len(signal), p0=first, p1=last)
    half_hop = HOP / (2.0 * sample_rate)
    plotted_s = (float(times[0]) - half_hop, float(times[-1]) + half_hop)
    return cast("npt.NDArray[np.float64]", np.clip(decibels, *DB_RANGE)), plotted_s


def _padded(samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """``samples``, zero-extended if it is shorter than one STFT can accept.

    `ShortTimeFFT` refuses a signal shorter than half a window outright, so a Recording under
    12.5 ms would raise — and a raise here aborts the whole build. But a Recording that short is
    *valid data*: it carries an advisory `duration_out_of_range` and nothing more, and ADR-0011
    guarantees it an Image. The padding is the same silence the transform's own border frames are
    made of, and the x-axis still ends at the true duration, so nothing invented is on display.
    """
    shortfall = _MIN_STFT_SAMPLES - len(samples)
    return samples if shortfall <= 0 else np.pad(samples, (0, shortfall))


def _frame_range(transform: ShortTimeFFT, num_samples: int) -> tuple[int | None, int | None]:
    """The fully-supported frame range, or ``(None, None)`` to keep every frame.

    ``upper_border_begin`` is only defined once the signal is at least half a window long, and the
    supported range can be empty or a single frame for a Recording of a few tens of milliseconds —
    both of which would leave nothing meaningful to plot. Falling back to the default (padded)
    range is what keeps such a Recording renderable at all.
    """
    if num_samples < N_FFT:
        return None, None
    first = transform.lower_border_end[1]
    last = transform.upper_border_begin(num_samples)[1]
    if last - first < 2:
        return None, None
    return first, last
