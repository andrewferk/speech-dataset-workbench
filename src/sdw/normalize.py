"""Turn an Original into its Normalized audio — mono, 16 kHz, 16-bit PCM WAV (#25, ADR-0005).

The second pipeline stage. Ingest (#24) resolved which Originals make up the Dataset without
decoding a byte; this stage decodes them, and in doing so *is* ADR-0005's ingest gate: a file that
is not WAV, or is a corrupt, truncated, or zero-frame WAV, raises :class:`HardError` and aborts the
run (non-zero exit, no durable output). A file that decodes but sounds bad — silent, clipped, too
quiet — is not an error here; that is a soft quality flag owned by a later stage (ADR-0007).

Three things pin the shape:

- **Normalization happens in memory; writing is a separate call.** :func:`normalize` decodes and
  converts and returns; :func:`write_normalized` is the only thing that touches the filesystem. That
  is what lets ``validate`` normalize every Original — running the decode gate in full — and discard
  the result, as ADR-0002 requires of a command that writes nothing, anywhere.

- **The decoded Original is part of the return value.** The clipping check has to measure the
  *Original's* samples: the downmix can average a clipped channel away, and the resample smears the
  flat top. Those are exactly the samples :func:`normalize` already reads as its first step, so
  :class:`NormalizedAudio` hands them back as a measurement tap rather than making the quality stage
  decode the file a second time.

- **Format only, and no knobs.** Every parameter below is a hard-coded constant, and nothing here
  changes a level: no gain, no loudness normalization, no dither. The levels the quality checks
  report are the levels that were recorded, and changing any constant is a tool change (a new
  ``dataset_version``), not a per-run option — there is deliberately no ``[normalize]`` config
  section (ADR-0005).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf
import soxr

from sdw.errors import HardError

# The canonical target: the near-universal ASR/dataset convention (ADR-0005). Constants, not
# config — see the module docstring.
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SUBTYPE = "PCM_16"

# python-soxr's quality setting. "HQ" is soxr's default-quality band-limited resampler; ADR-0005
# picked it over `scipy.signal.resample_poly` on quality, accepting libsoxr's LGPL.
RESAMPLE_QUALITY = "HQ"


@dataclass(frozen=True)
class NormalizedAudio:
    """One Original decoded, plus its Normalized form — the whole seam this stage exposes.

    ``samples`` is the Normalized audio: mono float64 at :data:`TARGET_SAMPLE_RATE`, ready for
    :func:`write_normalized`. ``original`` is the decoded Original exactly as it came off disk —
    float64, native sample rate, shape ``(frames,)`` when mono and ``(frames, channels)`` otherwise
    — for the clipping tap. It is float64 rather than the file's integer codes so that every
    consumer measures on one scale (-1.0 to 1.0) regardless of the Original's bit depth.
    """

    samples: npt.NDArray[np.float64]
    original: npt.NDArray[np.float64]
    original_sample_rate: int
    sample_rate: int = TARGET_SAMPLE_RATE


def normalize(path: Path) -> NormalizedAudio:
    """Decode ``path`` and convert it to mono 16 kHz float64, entirely in memory.

    ADR-0005's procedure, in order: read to float64, downmix by arithmetic mean, resample to 16 kHz
    with soxr ``HQ``. Nothing is written and ``path`` is never modified. Raises :class:`HardError`
    if the file cannot be decoded or holds no frames.
    """
    original, original_sample_rate = _decode(path)
    samples = _resample(_downmix(original), original_sample_rate)
    return NormalizedAudio(
        samples=samples, original=original, original_sample_rate=original_sample_rate
    )


def write_normalized(audio: NormalizedAudio, path: Path) -> None:
    """Write ``audio.samples`` to ``path`` as mono 16 kHz ``PCM_16``.

    libsndfile's float-to-PCM_16 conversion is deterministic round-to-nearest with no dither
    (ADR-0005), so the same samples always produce the same bytes on a given build.
    """
    sf.write(path, audio.samples, TARGET_SAMPLE_RATE, subtype=TARGET_SUBTYPE)


def _decode(path: Path) -> tuple[npt.NDArray[np.float64], int]:
    """Read the Original to float64, or abort.

    Decodability is the gate: soundfile refusing the file — because it is not WAV, or is corrupt or
    truncated — is a structural error, as is a WAV that decodes to zero frames (a header with no
    audio behind it). Either aborts the run rather than letting a Dataset Version quietly stand for
    a subset of the intended input (ADR-0005).
    """
    try:
        samples, sample_rate = sf.read(path, dtype="float64", always_2d=False)
    except (sf.LibsndfileError, OSError) as error:
        raise HardError(f"cannot decode Original as WAV: {path} ({error})") from error
    if len(samples) == 0:
        raise HardError(f"Original decodes to zero frames: {path}")
    return samples, int(sample_rate)


def _downmix(samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Mean of all channels; already-mono passes through unchanged.

    The mean is phase-preserving and standard. It is deliberately not a sum (which would raise the
    level and could clip) and not a channel pick: a dead channel halves the mean, and the
    low-volume quality check is what surfaces that — it is not corrected here (ADR-0005).
    """
    if samples.ndim == 1:
        return samples
    return np.asarray(samples.mean(axis=1), dtype=np.float64)


def _resample(samples: npt.NDArray[np.float64], sample_rate: int) -> npt.NDArray[np.float64]:
    """Resample to 16 kHz with soxr ``HQ`` — skipped entirely when the input is already 16 kHz.

    The skip is not an optimization: it keeps an already-conforming Original bit-exact instead of
    pushing it through a needless FFT round-trip (ADR-0005).
    """
    if sample_rate == TARGET_SAMPLE_RATE:
        return samples
    resampled = soxr.resample(samples, sample_rate, TARGET_SAMPLE_RATE, quality=RESAMPLE_QUALITY)
    return np.asarray(resampled, dtype=np.float64)
