"""The pinned checkpoint, loaded and called (ADR-0016).

The one module under `sdw.transcribe` that imports the ASR extra; every other one stays importable
with no extra installed, which is what keeps the plumbing suite in the torch-free `check` job
(ADR-0023, ADR-0025). Everything ADR-0016 fixed is a source constant here — widening any of them is
an ADR change, not a code change.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import torch
import transformers
from transformers import WhisperForConditionalGeneration, WhisperProcessor
from transformers.utils.hub import cached_file

from sdw.errors import HardError
from sdw.transcribe import audio
from sdw.transcribe.backend import BackendProvenance, Language

# A sha, never a tag or a branch: those could name different bytes online than the cached ones, and
# the offline Run would be the one telling the truth (ADR-0016).
REPO_ID = "openai/whisper-large-v3-turbo"
REVISION = "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"

# No accelerator path exists, opportunistic or otherwise (ADR-0016).
DEVICE = "cpu"
DTYPE = torch.float32
DTYPE_NAME = "float32"

RUNTIME_NAME = "transformers"

# ADR-0005's Normalized target, spelled here rather than imported from the build path (ADR-0023):
# the array carries no rate, so the feature extractor has to be told one.
SAMPLE_RATE = 16_000

# Six of ADR-0016's seven decode constants; the seventh, `language`, is resolved per Run and passed
# beside them. One mapping feeds both `generate()` and `run.json`, so the call and the Run's
# provenance cannot disagree — splitting them is what this shape prevents.
DECODE: Mapping[str, Any] = {
    "task": "transcribe",
    "do_sample": False,
    "num_beams": 1,
    "temperature": None,
    "condition_on_prev_tokens": False,
    # Adding a guard here — a repetition penalty, an n-gram block, a length cap — changes the model
    # output to flatter the Metric (ADR-0016).
    "return_timestamps": False,
}

_CARD = "README.md"
_FENCE = "---"
_LICENSE_KEY = "license"

_DOWNLOAD_NOTICE = (
    f"the pinned weights are not cached; fetching {REPO_ID} at {REVISION} from the Hub (~1.6 GB)"
)


def load() -> Whisper:
    """The loaded checkpoint, or :class:`HardError` if the weights will not resolve.

    Called after the structural preflight and before the Run directory exists, so unresolvable
    weights cost no Run (ADR-0017). The three network states of ADR-0016, in the order tried.
    """
    # Cache-first, so a warm cache never touches the network and `HF_HUB_OFFLINE` is never
    # overridden by this tool (ADR-0016).
    try:
        return _load(local_files_only=True)
    except OSError:
        pass
    print(f"note: {_DOWNLOAD_NOTICE}", file=sys.stderr)
    try:
        return _load(local_files_only=False)
    except OSError as error:
        raise HardError(
            f"the pinned weights are neither cached nor reachable: "
            f"{REPO_ID} at {REVISION} ({error})"
        ) from error


def _load(*, local_files_only: bool) -> Whisper:
    """One resolution attempt; the two differ by this flag and nothing else."""
    processor = WhisperProcessor.from_pretrained(
        REPO_ID, revision=REVISION, local_files_only=local_files_only
    )
    model = WhisperForConditionalGeneration.from_pretrained(
        REPO_ID, revision=REVISION, dtype=DTYPE, local_files_only=local_files_only
    )
    # Checked, not moved: with no `device_map` and no `.to(...)` there is no line here that could
    # name an accelerator, so ADR-0016's device decision is a property of the file.
    # `from_pretrained` also returns the model in evaluation mode, which it documents.
    if model.device.type != DEVICE:
        raise HardError(f"the checkpoint loaded onto {model.device.type}, not {DEVICE}")
    return Whisper(
        processor=processor,
        model=model,
        license=_license(local_files_only=local_files_only),
        # Read here, not when `run.json` is written: `_attn_implementation` is private, so an
        # upstream rename must surface in the preflight rather than after a Run has decoded.
        attn_implementation=str(model.config._attn_implementation),
    )


def _license(*, local_files_only: bool) -> str | None:
    """The licence the fetched checkpoint declares, or `None` if its card does not say (ADR-0016).

    Fetched at the pinned revision, so it describes the weights actually loaded. An unresolvable
    card is an absent licence, never an abort: the weights are already in hand.
    """
    try:
        path = cached_file(
            REPO_ID,
            _CARD,
            revision=REVISION,
            local_files_only=local_files_only,
            _raise_exceptions_for_missing_entries=False,
        )
    except OSError:
        return None
    if path is None:
        return None
    return _declared_license(Path(path).read_text(encoding="utf-8"))


def _declared_license(card: str) -> str | None:
    """The `license` scalar of a card's YAML front matter, or `None`, read without a YAML parser."""
    lines = card.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return None
    for line in lines[1:]:
        # Below the closing fence is body text, and a `license:` line there declares nothing.
        if line.strip() == _FENCE:
            return None
        key, separator, value = line.partition(":")
        if separator and key.strip() == _LICENSE_KEY:
            return value.strip().strip("\"'") or None
    return None


def _provenance(*, license: str | None, attn_implementation: str) -> BackendProvenance:
    """The three `run.json` blocks only the backend can answer for (ADR-0016, ADR-0020).

    Takes the two resolved facts rather than the model, so what is recorded is checkable without a
    checkpoint — the only way it can be checked, since no test may resolve a weight (ADR-0025).
    """
    return BackendProvenance(
        model={"repo_id": REPO_ID, "revision": REVISION, _LICENSE_KEY: license},
        decode=dict(DECODE),
        runtime={
            "name": RUNTIME_NAME,
            "transformers_version": transformers.__version__,
            "torch_version": torch.__version__,
            # The third resolved version, and a numerics input like the other two (ADR-0020).
            "python_version": platform.python_version(),
            "device": DEVICE,
            "dtype": DTYPE_NAME,
            # Both are recorded and neither is pinned (ADR-0016); dropping either loses a numerics
            # input a future comparison needs.
            "attn_implementation": attn_implementation,
            "torch_num_threads": torch.get_num_threads(),
        },
    )


@dataclass(frozen=True)
class Whisper:
    """A loaded checkpoint, satisfying :class:`sdw.transcribe.backend.Backend`."""

    processor: WhisperProcessor
    model: WhisperForConditionalGeneration
    license: str | None
    # The kernel `transformers` actually selected, not the one requested: the request would record
    # a preference where ADR-0016 asks for a numerics input.
    attn_implementation: str

    @property
    def provenance(self) -> BackendProvenance:
        """This checkpoint's three blocks, resolved when it loaded."""
        return _provenance(license=self.license, attn_implementation=self.attn_implementation)

    def transcribe(self, waveform: npt.NDArray[np.float32], language: Language) -> str:
        """The raw, unnormalized Hypothesis for one Sample; raising is a per-Sample failure.

        Raises for an over-length Sample, which is disclosed rather than decoded under altered
        constants — see ADR-0016's implementation note on the long-form regime.
        """
        # The array, never a path: a path parameter would route through FFmpeg (ADR-0005/ADR-0016).
        long_form = audio.is_long_form(waveform)
        inputs = self.processor(
            audio=waveform,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
            truncation=not long_form,
            padding="longest" if long_form else "max_length",
            return_attention_mask=long_form,
        )
        with torch.no_grad():
            tokens = self.model.generate(
                inputs.input_features.to(device=DEVICE, dtype=DTYPE),
                attention_mask=inputs.get("attention_mask"),
                language=language.value,
                **DECODE,
            )
        # `batch_decode` carries no annotations upstream, so `--strict` refuses the call, not the
        # types; one Sample per call, so the batch is always the one Hypothesis.
        decoded = self.processor.batch_decode(  # type: ignore[no-untyped-call]
            tokens, skip_special_tokens=True
        )
        return str(decoded[0])
