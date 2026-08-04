"""Read a Sample's Normalized audio as the array the model is handed (#164, ADR-0016)."""

from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from sdw.errors import HardError

# Audio frames, not the 3000 encoder frames ADR-0016 states the same threshold in: 30 s at 16 kHz,
# above which a Sample decodes in Whisper's long-form regime.
LONG_FORM_FRAMES = 480_000


def read(path: Path) -> npt.NDArray[np.float32]:
    """Decode one Normalized WAV to mono `float32`, or raise :class:`HardError` naming the file.

    The array is the whole seam: passing a *path* to the model would route through FFmpeg and undo
    ADR-0005's zero-FFmpeg property (ADR-0016).
    """
    try:
        waveform, _ = sf.read(path, dtype="float32", always_2d=False)
    except (sf.LibsndfileError, OSError) as error:
        raise HardError(
            f"Normalized audio is missing or will not decode: {path} ({error})"
        ) from error
    return np.asarray(waveform, dtype=np.float32)


def is_long_form(waveform: npt.NDArray[np.float32]) -> bool:
    """Whether this Sample decodes in the long-form regime (ADR-0016).

    Not v0.1's `duration_out_of_range`: that threshold is configurable and this one is Whisper's,
    so reusing the flag would assert an identity that does not hold (ADR-0019).
    """
    return len(waveform) > LONG_FORM_FRAMES
