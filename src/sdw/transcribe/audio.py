"""Read a Sample's Normalized audio as the array the model is handed (#164, ADR-0016).

The array, never the path: every path-based ASR entry point routes through FFmpeg, and ADR-0005's
zero-FFmpeg promise is kept structural by there being no path to pass. `float32` because that is
what every runtime casts to anyway, and `soundfile`'s `float64` default buys nothing here.
"""

from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

from sdw.errors import HardError

# Whisper's short-form path is selected by 3000 encoder frames — 30 s at 16 kHz (ADR-0016). Above
# it a Sample decodes in the long-form regime, which is disclosed per line and never rejected.
LONG_FORM_FRAMES = 480_000


def read(path: Path) -> npt.NDArray[np.float32]:
    """Decode one Normalized WAV to mono `float32`, or abort naming the file (ADR-0017).

    Called twice per Sample across a Run — once in the preflight, once with the model loaded — so
    that *"any Sample's audio will not decode"* is knowable in seconds rather than at minute 39.
    """
    try:
        samples, _ = sf.read(path, dtype="float32", always_2d=False)
    except (sf.LibsndfileError, OSError) as error:
        raise HardError(
            f"Normalized audio is missing or will not decode: {path} ({error})"
        ) from error
    return np.asarray(samples, dtype=np.float32)


def is_long_form(samples: npt.NDArray[np.float32]) -> bool:
    """Whether this Sample decodes in the long-form regime (ADR-0016, ADR-0019).

    Not v0.1's `duration_out_of_range`: that flag fires against a *configurable* threshold and
    expresses an opinion about dataset quality, where this one fires against Whisper's fixed window
    and expresses which decode regime produced the Hypothesis.
    """
    return len(samples) > LONG_FORM_FRAMES
