"""The model seam: what Transcription calls, and what it quotes into `run.json` (ADR-0025).

The seam is a **parameter** on :func:`sdw.transcribe.pipeline.run` — never an argument, a config key
or a registry, any of which would be checkpoint selection by the back door. Widening it is an ADR
change (ADR-0016, ADR-0025).

Nothing here imports the ASR extra: the leaf module that does supplies a :class:`Backend`, and the
tests supply a fake, which is what keeps the write path testable in a torch-free venv.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

# The effective language when the dataset declares none — v0.1's default is `null` (ADR-0016).
DEFAULT_LANGUAGE = "en"

# How the effective language was arrived at. Recorded so a convenience never becomes a silent
# assumption (ADR-0016).
DECLARED = "declared"
DEFAULTED = "defaulted"


@dataclass(frozen=True)
class Language:
    """The effective decode language and where it came from — one fact, stated once (ADR-0020)."""

    value: str
    source: str


@dataclass(frozen=True)
class BackendProvenance:
    """The three `run.json` blocks only the backend can answer for (ADR-0016, ADR-0020).

    Each is rendered verbatim, in the order the backend supplies, so the decode constants the call
    site passes and the constants the provenance quotes come from one place. `language` is
    deliberately **not** here: it is resolved from the dataset, sits in its own block, and a fact
    recorded twice can disagree with itself.
    """

    model: Mapping[str, Any]
    decode: Mapping[str, Any]
    runtime: Mapping[str, Any]


class Backend(Protocol):
    """A loaded model, ready to transcribe — the whole of what the plumbing knows about ASR."""

    @property
    def provenance(self) -> BackendProvenance:
        """The model, decode and runtime facts of this loaded backend."""

    def transcribe(self, waveform: npt.NDArray[np.float32], language: Language) -> str:
        """The Hypothesis for one Sample's Normalized audio, raw and unnormalized.

        Raising is a per-Sample failure: it is recorded and the Run continues (ADR-0017).
        """


def resolve_language(declared: str | None) -> Language:
    """The effective language for the Run, and its source (ADR-0016).

    Defaulting rather than aborting keeps an unlabelled v0.1 dataset evaluable — labelling one
    changes the Manifest bytes and therefore its `dataset_version`, a re-versioning this declines to
    force.
    """
    if declared is None:
        return Language(value=DEFAULT_LANGUAGE, source=DEFAULTED)
    return Language(value=declared, source=DECLARED)
