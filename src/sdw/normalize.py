"""Turn an Original into its Normalized audio — mono, 16 kHz, 16-bit PCM WAV (#25, ADR-0005).

The second `build` stage — it decodes the Originals that ingest (#24) resolved — and ADR-0005's
ingest gate: a non-PCM-WAV, corrupt, truncated, or
zero-frame Original raises :class:`HardError` and aborts the run; a file that decodes but sounds bad
is a later soft quality flag, not an error here (ADR-0007). Decoding and conversion happen in
memory; writing is a separate call, so `validate` runs the gate and discards its output (ADR-0002).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf
import soxr

from sdw.errors import HardError

# The canonical ASR/dataset target; constants, not config (ADR-0005). Mono is the third leg and has
# no constant — it is the shape `samples` always has, not a parameter of anything.
TARGET_SAMPLE_RATE = 16000
TARGET_SUBTYPE = "PCM_16"

# "PCM WAV" is two independent checks libsndfile reports separately (ADR-0005): the container is a
# RIFF WAV form, and the encoding is a PCM_ subtype. Widening either set is an ADR change.
_WAV_FORMATS = frozenset({"WAV", "WAVEX", "RF64"})
_PCM_SUBTYPE_PREFIX = "PCM_"

# soxr's band-limited "HQ" resampler (ADR-0005).
RESAMPLE_QUALITY = "HQ"


@dataclass(frozen=True)
class NormalizedAudio:
    """One Original decoded, plus its Normalized form — the seam this stage exposes.

    ``samples`` is the Normalized audio (mono float64 at ``sample_rate``, always
    :data:`TARGET_SAMPLE_RATE`); ``original`` is the decoded Original as it came off disk (float64,
    native rate, shape ``(frames,)`` when mono else ``(frames, channels)``), kept as the clipping
    tap so the quality stage need not decode the file a second time (ADR-0007).
    """

    samples: npt.NDArray[np.float64]
    original: npt.NDArray[np.float64]
    original_sample_rate: int
    sample_rate: int = TARGET_SAMPLE_RATE


def normalize(path: Path) -> NormalizedAudio:
    """Decode ``path`` and convert it to mono 16 kHz float64, entirely in memory (ADR-0005).

    Reads to float64, downmixes by arithmetic mean, resamples to 16 kHz with soxr ``HQ``. Writes
    nothing and never modifies ``path``. Raises :class:`HardError` if the file cannot be decoded or
    holds no frames.
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
    sf.write(path, audio.samples, audio.sample_rate, subtype=TARGET_SUBTYPE)


def _decode(path: Path) -> tuple[npt.NDArray[np.float64], int]:
    """Read the Original to float64, or abort with :class:`HardError` (ADR-0005).

    Aborts on any of: soundfile refuses the file, it is not a WAV container, its encoding is not
    PCM, or it decodes to zero frames — see :data:`_WAV_FORMATS` for why both halves of "PCM WAV"
    are checked.
    """
    # One open, not `sf.info` then `sf.read`: header check and decode must see the same file.
    try:
        with sf.SoundFile(path) as handle:
            container, encoding = handle.format, handle.subtype
            sample_rate = int(handle.samplerate)
            samples: npt.NDArray[np.float64] = handle.read(dtype="float64", always_2d=False)
    except (sf.LibsndfileError, OSError) as error:
        raise HardError(f"cannot decode Original as WAV: {path} ({error})") from error
    if container not in _WAV_FORMATS:
        raise HardError(f"Original is not a WAV (libsndfile reports {container}): {path}")
    if not encoding.startswith(_PCM_SUBTYPE_PREFIX):
        raise HardError(f"Original is not a PCM WAV (libsndfile reports {encoding}): {path}")
    if len(samples) == 0:
        raise HardError(f"Original decodes to zero frames: {path}")
    return samples, int(sample_rate)


def _downmix(samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Mean of all channels (ADR-0005); already-mono passes through unchanged."""
    if samples.ndim == 1:
        return samples
    return np.asarray(samples.mean(axis=1), dtype=np.float64)


def _resample(samples: npt.NDArray[np.float64], sample_rate: int) -> npt.NDArray[np.float64]:
    """Resample to 16 kHz with soxr ``HQ`` (ADR-0005); skipped when the input is already 16 kHz.

    The skip is not an optimization — it keeps an already-conforming Original bit-exact.
    """
    if sample_rate == TARGET_SAMPLE_RATE:
        return samples
    resampled = soxr.resample(samples, sample_rate, TARGET_SAMPLE_RATE, quality=RESAMPLE_QUALITY)
    return np.asarray(resampled, dtype=np.float64)
