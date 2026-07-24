"""Render a waveform and a spectrogram PNG for every Recording (#31, ADR-0011).

The fifth pipeline stage. Both PNGs render from the Normalized samples on fixed absolute scales, so
any two are comparable and neither can contradict a Quality flag. An Image is an operator inspection
aid, outside `dataset_version` (ADR-0010): there is no `[images]` config section — adding one would
mint a new dataset identity for a byte-identical Manifest — so every constant below is a
`tool_version` change, not a config one. Determinism is same-machine byte-identity, verified by a
twice-on-one-machine build (ADR-0008); cross-machine identity is not sought. A render failure raises
:class:`~sdw.errors.HardError` and aborts the build (ADR-0011), so `images/` is never a partial
mirror of the Manifest.
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

# Figure geometry (ADR-0011). 100 DPI keeps each PNG in the ~50-150 KB band.
DPI = 100
WAVEFORM_FIGSIZE = (10.0, 3.0)
SPECTROGRAM_FIGSIZE = (10.0, 4.0)
WAVEFORM_SIZE_PX = (int(WAVEFORM_FIGSIZE[0] * DPI), int(WAVEFORM_FIGSIZE[1] * DPI))
SPECTROGRAM_SIZE_PX = (int(SPECTROGRAM_FIGSIZE[0] * DPI), int(SPECTROGRAM_FIGSIZE[1] * DPI))

# The two absolute scales (ADR-0011): never autoscaled, never a function of the signal plotted —
# what keeps any two Images comparable and stops one contradicting a Quality flag.
WAVEFORM_YLIM = (-1.0, 1.0)
DB_RANGE = (-80.0, 0.0)

# STFT framing (ADR-0011): 25 ms Hann window, 10 ms hop. 201 bins over 0 .. 8 kHz at 16 kHz.
N_FFT = 400
HOP = 160

# The shortest signal `ShortTimeFFT` accepts: half a window. Shorter Recordings are zero-extended
# rather than refused (see :func:`_padded`).
_MIN_STFT_SAMPLES = -(-N_FFT // 2)

# The dB-spectrogram colormap fixed by ADR-0011.
COLORMAP = "magma"

# dB floor for `20*log10(0)` in the plot — a rendering guard that clamps to the darkest colour, not
# the measured -120 floor (ADR-0007 owns that).
_MAGNITUDE_FLOOR = 1e-12

# The subtree this module owns under `--data-out` (ADR-0003).
IMAGES_DIR = "images"

# Images share the `recording_id` stem with the audio and the quality line (ADR-0003).
WAVEFORM_SUFFIX = ".waveform.png"
SPECTROGRAM_SUFFIX = ".spectrogram.png"

# Everything the render would otherwise read from a user's matplotlibrc, pinned for determinism
# (ADR-0011). Fonts pinned to bundled DejaVu — a system font list resolves differently per machine.
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

# Omit matplotlib's `Software` tEXt chunk — the one non-deterministic value its PNG writer adds by
# default, so an upgrade does not change every byte of every image (ADR-0011).
_PNG_METADATA: dict[str, Any] = {"Software": None}

# Fixed axes rectangles (figure coords): pinned so tick-label width and the colorbar can never move
# the plotted area between images.
_WAVEFORM_AXES = (0.06, 0.17, 0.92, 0.70)
_SPECTROGRAM_AXES = (0.06, 0.13, 0.84, 0.77)
_COLORBAR_AXES = (0.92, 0.13, 0.02, 0.77)


def image_paths(recording_id: str, out_dir: Path) -> tuple[Path, Path]:
    """The two paths :func:`render` writes for ``recording_id``, waveform first."""
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

    ``metrics`` is rendered, never recomputed — the title's values can only be the quality stage's
    (ADR-0012). Raises :class:`~sdw.errors.HardError` on any render or write failure, aborting the
    build so `images/` never partially mirrors the Manifest.
    """
    waveform_path, spectrogram_path = image_paths(recording.recording_id, out_dir)
    heading = title(recording, metrics)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # `rc_context`'s Literal-key type rejects a plain dict; every key in _RC_PARAMS is a real
        # rcParam, and a typo would raise at render time.
        with plt.rc_context(_RC_PARAMS):  # type: ignore[arg-type]
            _render_waveform(audio.samples, audio.sample_rate, heading, waveform_path)
            _render_spectrogram(audio.samples, audio.sample_rate, heading, spectrogram_path)
    except Exception as error:
        raise HardError(f"could not render images for {recording.recording_id}: {error}") from error


def title(recording: Recording, metrics: QualityMetrics) -> str:
    """The one-line heading both Images carry: identity, then measurements.

    Flags and prompt text are deliberately excluded: a flag would couple this stage to `[quality]`
    thresholds and duplicate a verdict, and arbitrary-length prompt text forces determinism-hostile
    layout. Precision is ADR-0007's, imported from :mod:`sdw.quality`, not restated (#54); fixed
    decimal places (not ``round``) are this module's spelling, so a column keeps one width.
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

    The `finally` close is load-bearing: without it a build of any size leaks figures until the
    process is out of memory.
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
    """Amplitude against time, on a y-axis fixed at full scale (never autoscaled).

    Autoscale would draw a -45 dBFS whisper and a -1 dBFS shout identically, silently contradicting
    `low_volume`. x is per-recording because duration is legible elsewhere — a field and a flag.
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
    """Energy against time and frequency, on an absolute colour scale (never per-image normalized).

    Per-image dB normalization would re-lie about level the way waveform autoscale does and
    contradict the fixed-scale waveform beside it; the absolute scale makes a quiet Recording dim.
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
        # x-axis is the waveform's, not the data's: the two Images must align in time, so the
        # unsupported frames at each end stay blank rather than shift the axis.
        axes.set_xlim(0.0, duration_s)
        axes.set_xlabel("time (s)")
        axes.set_ylabel("frequency (Hz)")
        colorbar = figure.colorbar(mesh, cax=figure.add_axes(_COLORBAR_AXES))
        colorbar.set_label("magnitude (dBFS)")


def stft_dbfs(
    samples: npt.NDArray[np.float64], sample_rate: int
) -> tuple[npt.NDArray[np.float64], tuple[float, float]]:
    """The STFT magnitude in absolute dBFS clamped to :data:`DB_RANGE`, and the seconds it covers.

    Returns ``(201 bins, frames)`` over 0 .. 8 kHz and ``plotted_s``, the ``(start, end)`` of the
    plotted region's outer edges (half a hop beyond the first and last frame centres). Magnitude is
    scaled by ``2 / sum(window)`` so a bin reads on the waveform's 0 .. 1 full-scale ruler — what
    makes the dB absolute and comparable across images; the conversion is ADR-0007's ``20*log10``.

    Only fully-supported frames are kept where the Recording has them — a zero-padded border frame
    reads as a broadband stripe. A Recording too short for two such frames keeps the padded frames:
    it is always renderable (ADR-0011).
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
    """``samples``, zero-extended if shorter than one STFT can accept.

    `ShortTimeFFT` refuses a signal under half a window, but such a Recording is valid data owed an
    Image (ADR-0011); the padding is silence and the x-axis still ends at the true duration.
    """
    shortfall = _MIN_STFT_SAMPLES - len(samples)
    return samples if shortfall <= 0 else np.pad(samples, (0, shortfall))


def _frame_range(transform: ShortTimeFFT, num_samples: int) -> tuple[int | None, int | None]:
    """The fully-supported frame range, or ``(None, None)`` to keep every frame.

    Falls back to the padded range when the supported range would be empty or a single frame — what
    keeps a Recording of a few tens of milliseconds renderable at all.
    """
    if num_samples < N_FFT:
        return None, None
    first = transform.lower_border_end[1]
    last = transform.upper_border_begin(num_samples)[1]
    if last - first < 2:
        return None, None
    return first, last
