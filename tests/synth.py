"""The sole in-repo fixture generator (ADR-0008).

Every WAV the test suite uses is synthesized here — no external audio, ever. Fixtures are
therefore *code*: parameterized, reviewable in a diff, and this generator is itself a tested
unit. The same generator also writes the committed reference ``--data-in`` (below) and is
reused by ``examples/generate.py`` (ADR-0009), so it is the single source of fixture truth.

The core :func:`write_wav` synthesizes a signal whose properties are known by construction:
a tone (or, with ``seed``, reproducible white noise) at a chosen RMS level, duration, sample
rate, bit depth, and channel count. Those knobs drive the behaviors under test — ``amp_dbfs``
aims ``active_rms_dbfs`` to trip/clear ``low_volume``; ``duration_s`` trips/clears
``duration_out_of_range``; ``sample_rate``/``bit_depth``/``channels`` drive normalization's
resample/downmix/depth/passthrough paths (ADR-0005). Named shortcuts and the degenerate abort
inputs build on it.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
import soundfile as sf

# libsndfile subtypes for the bit depths we emit. Signed PCM only — the Normalized target and
# every Original we synthesize is integer PCM (ADR-0005).
_SUBTYPE: dict[int, str] = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}


def _subtype(bit_depth: int) -> str:
    """The libsndfile subtype for ``bit_depth``, or a clear error for an unsupported depth."""
    try:
        return _SUBTYPE[bit_depth]
    except KeyError:
        raise ValueError(
            f"unsupported bit_depth {bit_depth!r}; expected one of {sorted(_SUBTYPE)}"
        ) from None


def _tone(
    freq_hz: float, amp_dbfs: float, num_frames: int, sample_rate: int
) -> npt.NDArray[np.float64]:
    """A sine at ``freq_hz`` whose RMS is ``amp_dbfs`` dBFS (a full-scale sine reads -3 dBFS).

    peak = sqrt(2) * 10**(amp_dbfs/20), so RMS = peak/sqrt(2) = 10**(amp_dbfs/20). Choosing an
    integer number of cycles (``freq_hz * duration_s`` whole) makes the RMS exact to rounding.
    """
    t = np.arange(num_frames, dtype=np.float64) / sample_rate
    peak = np.sqrt(2.0) * 10.0 ** (amp_dbfs / 20.0)
    return cast("npt.NDArray[np.float64]", peak * np.sin(2.0 * np.pi * freq_hz * t))


def _noise(amp_dbfs: float, num_frames: int, seed: int) -> npt.NDArray[np.float64]:
    """Reproducible white noise scaled to exactly ``amp_dbfs`` RMS — a non-tonal case."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(num_frames)
    rms = np.sqrt(np.mean(x**2))
    return cast("npt.NDArray[np.float64]", (x / rms) * 10.0 ** (amp_dbfs / 20.0))


def _to_channels(mono: npt.NDArray[np.float64], channels: int) -> npt.NDArray[np.float64]:
    """Tile a mono signal across ``channels`` identical channels.

    Identical channels keep the downmix (arithmetic mean, ADR-0005) exactly equal to the
    channel, so a stereo->mono fixture has a predictable Normalized value with no half-ULP.
    """
    if channels == 1:
        return mono
    return np.column_stack([mono] * channels)


def _num_frames(duration_s: float, sample_rate: int) -> int:
    return round(duration_s * sample_rate)


def write_wav(
    path: Path,
    *,
    freq_hz: float,
    amp_dbfs: float,
    duration_s: float,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    seed: int | None = None,
) -> None:
    """Write a WAV whose properties are known by construction.

    A tone at ``freq_hz`` and ``amp_dbfs`` RMS, unless ``seed`` is given — then reproducible
    white noise at that RMS (``freq_hz`` is ignored). ``amp_dbfs`` should stay at or below
    -3 dBFS: a louder target drives the sine peak past full scale and clips (use
    :func:`clipped` for that on purpose).
    """
    subtype = _subtype(bit_depth)
    num_frames = _num_frames(duration_s, sample_rate)
    mono = (
        _noise(amp_dbfs, num_frames, seed)
        if seed is not None
        else _tone(freq_hz, amp_dbfs, num_frames, sample_rate)
    )
    data = _to_channels(mono, channels)
    sf.write(path, data, sample_rate, subtype=subtype)


def silence(
    path: Path,
    *,
    duration_s: float,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
) -> None:
    """An all-zero WAV: exercises the silence metrics and the wholly-silent -> ``low_volume``
    floor (a signal with no active frames reads ``active_rms_dbfs`` = -120, ADR-0007)."""
    subtype = _subtype(bit_depth)
    num_frames = _num_frames(duration_s, sample_rate)
    mono = np.zeros(num_frames, dtype=np.float64)
    sf.write(path, _to_channels(mono, channels), sample_rate, subtype=subtype)


def clipped(
    path: Path,
    *,
    duration_s: float = 1.0,
    freq_hz: float = 440.0,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
) -> None:
    """A genuinely clipped tone: an overdriven sine hard-limited to full scale, producing a
    real flat-top run (>= 3 consecutive samples at >= 0.99 FS), not a scaled sine (ADR-0007).

    The 2x overdrive holds ``|sin| > 0.5`` for a third of every cycle, so the flat top spans
    ``~(sample_rate/freq_hz)/3`` samples; the defaults leave that comfortably above the
    3-sample minimum. Works at any ``bit_depth`` — full scale quantizes to the max code, which
    reads back >= 0.99 in every depth.
    """
    subtype = _subtype(bit_depth)
    num_frames = _num_frames(duration_s, sample_rate)
    t = np.arange(num_frames, dtype=np.float64) / sample_rate
    overdriven = 2.0 * np.sin(2.0 * np.pi * freq_hz * t)
    mono = np.clip(overdriven, -1.0, 1.0)
    sf.write(path, _to_channels(mono, channels), sample_rate, subtype=subtype)


def leading_trailing_silence(
    path: Path,
    *,
    lead_s: float,
    tone_s: float,
    trail_s: float,
    freq_hz: float = 440.0,
    amp_dbfs: float = -18.0,
    sample_rate: int = 16000,
    bit_depth: int = 16,
    channels: int = 1,
) -> None:
    """A tone padded with head/tail silence: exercises the 0.2 s silence guard and the
    active-region trim of the low-volume/silence metrics (ADR-0007)."""
    subtype = _subtype(bit_depth)
    lead = np.zeros(_num_frames(lead_s, sample_rate), dtype=np.float64)
    tone = _tone(freq_hz, amp_dbfs, _num_frames(tone_s, sample_rate), sample_rate)
    trail = np.zeros(_num_frames(trail_s, sample_rate), dtype=np.float64)
    mono = np.concatenate([lead, tone, trail])
    sf.write(path, _to_channels(mono, channels), sample_rate, subtype=subtype)


# --- Abort-case inputs (structural failures that must abort a build, ADR-0005/ADR-0007) ------


def write_non_wav(path: Path) -> None:
    """Write non-WAV bytes to a ``.wav``-named file: a decode-fail (soundfile cannot open it)."""
    path.write_bytes(b"This is not a WAV file. It carries a .wav name but no RIFF header.\n")


def write_zero_frame_wav(path: Path) -> None:
    """Write a structurally valid WAV with a header but zero frames: nothing to ingest."""
    sf.write(path, np.zeros(0, dtype=np.float64), 16000, subtype=_SUBTYPE[16])


def write_wrong_container(path: Path) -> None:
    """Write a FLAC to a ``.wav``-named file: decodable, but not a WAV.

    The sharpest case for the WAV-only contract (ADR-0005) — libsndfile decodes this happily, so
    only a container check rejects it. The name is what lies; the bytes are honest FLAC.
    """
    sf.write(path, np.zeros(16000, dtype=np.float64), 16000, format="FLAC", subtype=_SUBTYPE[16])


def write_truncated_wav(path: Path, *, keep_bytes: int = 20) -> None:
    """Write the first ``keep_bytes`` of a real WAV: a header cut mid-chunk, so the decode fails.

    Truncating inside the ``fmt `` chunk (the default) is what makes this a *decode* failure rather
    than a short-but-readable file: libsndfile happily reads a file whose *data* chunk is short, so
    lopping off the tail would not exercise the abort path (ADR-0005).
    """
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(16000, dtype=np.float64), 16000, subtype=_SUBTYPE[16], format="WAV")
    path.write_bytes(buffer.getvalue()[:keep_bytes])


# --- The committed reference --data-in (ADR-0008) --------------------------------------------

# The single small reference input the golden end-to-end test will anchor to, and a
# human-inspectable worked example. Each Recording isolates one normalization axis (ADR-0005):
# the already-16 kHz-mono passthrough, a 48 kHz resample, a stereo downmix, and a 24-bit depth
# reduction. All four are parked away from rounding cliffs — one clean level (-18 dBFS, clear of
# the -30 low_volume knob), a whole 2.000 s duration, and integer tone cycles — so a later
# quality.jsonl can be an exact golden with no tolerance machinery (ADR-0008). Prompts are
# honest English; the audio is tones (ADR-0009). Four Sessions across two Speakers clear
# ADR-0004's >= 3-Session floor for the future split golden.

_REFERENCE_COLUMNS = ["path", "speaker_id", "session_id", "prompt_text", "device", "environment"]


@dataclass(frozen=True)
class _ReferenceRecording:
    """One reference Recording: the WAV to synthesize plus its recordings.csv row."""

    path: str
    sample_rate: int
    channels: int
    bit_depth: int
    speaker_id: str
    session_id: str
    prompt_text: str
    device: str
    environment: str

    def csv_row(self) -> dict[str, str]:
        return {
            "path": self.path,
            "speaker_id": self.speaker_id,
            "session_id": self.session_id,
            "prompt_text": self.prompt_text,
            "device": self.device,
            "environment": self.environment,
        }


_REFERENCE_RECORDINGS = [
    _ReferenceRecording(
        path="passthrough_16k_mono.wav",
        sample_rate=16000,
        channels=1,
        bit_depth=16,
        speaker_id="spk_a",
        session_id="sess_a1",
        prompt_text="The quick brown fox jumps over the lazy dog.",
        device="usb condenser microphone",
        environment="quiet room",
    ),
    _ReferenceRecording(
        path="resample_48k_mono.wav",
        sample_rate=48000,
        channels=1,
        bit_depth=16,
        speaker_id="spk_a",
        session_id="sess_a2",
        prompt_text="She sells sea shells by the sea shore.",
        device="usb condenser microphone",
        environment="quiet room",
    ),
    _ReferenceRecording(
        path="downmix_16k_stereo.wav",
        sample_rate=16000,
        channels=2,
        bit_depth=16,
        speaker_id="spk_b",
        session_id="sess_b1",
        prompt_text="How much wood would a woodchuck chuck.",
        device="laptop stereo array",
        environment="home office",
    ),
    _ReferenceRecording(
        path="depth_16k_mono_24bit.wav",
        sample_rate=16000,
        channels=1,
        bit_depth=24,
        speaker_id="spk_b",
        session_id="sess_b2",
        prompt_text="A stitch in time saves nine.",
        device="field recorder",
        environment="home office",
    ),
]

# Parked signal constants shared by every reference Recording (see the block comment above).
_REFERENCE_FREQ_HZ = 400.0
_REFERENCE_AMP_DBFS = -18.0
_REFERENCE_DURATION_S = 2.0


def write_reference_tree(root: Path) -> None:
    """Write the committed reference ``--data-in`` (recordings.csv + the four WAVs) into ``root``.

    Deterministic and resample-free — every WAV is written at its native rate/depth/channels
    with no soxr in the loop — so its bytes are safe to byte-compare as a committed fixture
    (the drift test in ``tests/unit/test_reference_tree.py``).
    """
    root.mkdir(parents=True, exist_ok=True)
    for rec in _REFERENCE_RECORDINGS:
        write_wav(
            root / rec.path,
            freq_hz=_REFERENCE_FREQ_HZ,
            amp_dbfs=_REFERENCE_AMP_DBFS,
            duration_s=_REFERENCE_DURATION_S,
            sample_rate=rec.sample_rate,
            bit_depth=rec.bit_depth,
            channels=rec.channels,
        )
    with (root / "recordings.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_REFERENCE_COLUMNS)
        writer.writeheader()
        for rec in _REFERENCE_RECORDINGS:
            writer.writerow(rec.csv_row())
