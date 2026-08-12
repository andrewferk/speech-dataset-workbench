"""The pinned checkpoint, loaded and called — the one module here that imports the ASR extra.

Everything ADR-0016 fixed lives in this file as a source constant: the repo id, the revision, the
device, the dtype and the decode parameters. None of them is configuration, a CLI argument or a
registry entry, so "which model was this?" is answered by the repository rather than by the
operator's memory. Widening any of them is an ADR change, not a code change.

Nothing else under `sdw.transcribe` imports `torch` or `transformers`, which is what keeps the
plumbing suite in the torch-free `check` job (ADR-0023, ADR-0025). The import boundary is checked by
`tests/unit/test_import_graph.py`; that this import *resolves* is checked by the `asr` job's
leaf-module smoke, because `transformers` carries an `ignore_missing_imports` override that blinds
`mypy --strict` to a wrong name.

The explicit processor plus `generate()`, never `pipeline(...)`: every path-based entry point routes
through FFmpeg, and under this API there is no path parameter to reach for (ADR-0005, ADR-0016).
"""

from __future__ import annotations

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

# The checkpoint, by content rather than by name: a tag or a branch could name different bytes
# online than the ones already cached, and the offline Run would be the one telling the truth
# (ADR-0016).
REPO_ID = "openai/whisper-large-v3-turbo"
REVISION = "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"

# torch documents that CPU and GPU results may differ under identical seeds, and mentions MPS
# nowhere at all. Transcription being attributed-not-reproducible licenses disclosing irreducible
# variance; it does not license adding removable variance, and device is removable (ADR-0016).
DEVICE = "cpu"
DTYPE = torch.float32
DTYPE_NAME = "float32"

RUNTIME_NAME = "transformers"

# ADR-0005's Normalized target, restated where the model is called rather than imported from the
# build path (ADR-0023): the array carries no rate, so the feature extractor has to be told one.
SAMPLE_RATE = 16_000

# Six of ADR-0016's seven decode constants; the seventh, `language`, is resolved per Run from the
# Manifest and passed beside them. One mapping feeds both the `generate()` call and `run.json`, so
# the call site and the Run's provenance cannot disagree.
#
# No repetition penalty, no `no_repeat_ngram_size` and no `max_new_tokens`: a runaway decode must
# surface as a Metric above 1.0 rather than be tidied away at generation time. Whisper is
# architecturally bounded at 448 decoder positions, so it is already finite (ADR-0016).
DECODE: Mapping[str, Any] = {
    "task": "transcribe",
    "do_sample": False,
    "num_beams": 1,
    # Load-bearing: `transformers` is the only surveyed runtime whose temperature default is
    # already 0 rather than a fallback ladder that engages an RNG. Inherited, and still stated.
    "temperature": None,
    "condition_on_prev_tokens": False,
    "return_timestamps": False,
}

# The licence is read from the checkpoint's own card, never from a constant here: turbo makes the
# README/card conflict vanish today, but a hard-coded string would be a lie waiting for the next
# checkpoint (ADR-0016).
_CARD = "README.md"
_FENCE = "---"
_LICENSE_KEY = "license"

# Announced rather than silent: a 1.6 GB pause should never be a mystery. Worded as an attempt
# because the operator may have the network down, in which case the hard error follows immediately.
_DOWNLOAD_NOTICE = (
    f"the pinned weights are not cached; fetching {REPO_ID} at {REVISION} from the Hub (~1.6 GB)"
)


def load() -> Whisper:
    """Resolve the pinned weights and return the loaded model, or abort naming what failed.

    The Run's second preflight phase: this is called after the structural preflight and before the
    Run directory exists, so unresolvable weights cost the operator no Run at all (ADR-0017).

    ADR-0016's three network states, in the order they are tried. A **warm cache** resolves without
    touching the network, which is why the cached attempt comes first — `HF_HUB_OFFLINE` is honoured
    and never overridden here. A **cold cache with network** falls through to the download and says
    so, because a 1.6 GB pause should never be a mystery. **Neither** is a hard error rather than a
    partial Run: the operator must never get a Report over a model that failed to load.
    """
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
    """One resolution attempt, cache-only or not — the two differ by this flag and nothing else."""
    processor = WhisperProcessor.from_pretrained(
        REPO_ID, revision=REVISION, local_files_only=local_files_only
    )
    model = WhisperForConditionalGeneration.from_pretrained(
        REPO_ID, revision=REVISION, dtype=DTYPE, local_files_only=local_files_only
    )
    # Checked rather than moved, and that is the decision: no `device_map` and no `.to(...)` means
    # there is no line here that could ever name an accelerator, so ADR-0016's "no MPS path exists"
    # is a fact about the file. `from_pretrained` loads on CPU and returns the model already in
    # evaluation mode, which it documents; this asserts the half we depend on.
    if model.device.type != DEVICE:
        raise HardError(f"the checkpoint loaded onto {model.device.type}, not {DEVICE}")
    return Whisper(
        processor=processor, model=model, license=_license(local_files_only=local_files_only)
    )


def _license(*, local_files_only: bool) -> str | None:
    """The licence the fetched checkpoint declares, or `None` if its card does not say (ADR-0016).

    Fetched at the pinned revision like every other file, so it describes the weights actually
    loaded. A card that will not resolve is recorded as an absent licence rather than aborting a Run
    whose weights are already in hand.
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
    """The `license` key of a model card's YAML front matter, read without a YAML parser.

    One scalar off the top of the file, and no dependency added to read it: anything the front
    matter can hold that this cannot parse is a card that does not declare a plain licence.
    """
    lines = card.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return None
    for line in lines[1:]:
        if line.strip() == _FENCE:
            return None
        key, separator, value = line.partition(":")
        if separator and key.strip() == _LICENSE_KEY:
            return value.strip().strip("\"'") or None
    return None


def _provenance(*, license: str | None, attn_implementation: str) -> BackendProvenance:
    """The three `run.json` blocks only the backend can answer for (ADR-0016, ADR-0020).

    Takes the two resolved facts rather than the model, so what this repo *records* is checkable
    without a checkpoint — which is the only way it could be checked at all, since no test may
    resolve a weight (ADR-0025).
    """
    return BackendProvenance(
        model={"repo_id": REPO_ID, "revision": REVISION, _LICENSE_KEY: license},
        decode=dict(DECODE),
        runtime={
            "name": RUNTIME_NAME,
            "transformers_version": transformers.__version__,
            "torch_version": torch.__version__,
            "device": DEVICE,
            "dtype": DTYPE_NAME,
            # Recorded, not pinned, and both for one reason: each is a numerics input with no
            # correct value to pin it to. Thread count changes floating-point reduction order, so
            # two machines with different core counts produce different Hypotheses from identical
            # inputs — a fact a future comparison needs and a naive record would omit (ADR-0016).
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

    @property
    def provenance(self) -> BackendProvenance:
        """This checkpoint's blocks — the resolved kernel read off the config it was loaded with.

        The attribute is private because `transformers` exposes the resolved `attn_implementation`
        nowhere else, and recording the request rather than the resolution would record a preference
        instead of a numerics input.
        """
        return _provenance(
            license=self.license,
            attn_implementation=str(self.model.config._attn_implementation),
        )

    def transcribe(self, waveform: npt.NDArray[np.float32], language: Language) -> str:
        """The Hypothesis for one Sample, raw and unnormalized — Text Normalization is `score`'s.

        The `float32` array goes in directly. Passing a *path* would route through FFmpeg and undo
        ADR-0005's zero-FFmpeg property, which is why the explicit API is the decision rather than
        an implementation detail (ADR-0016).

        An over-length Sample is fed through Whisper's long-form path, which `transformers` refuses
        unless timestamps are returned. ADR-0016 fixes `return_timestamps=False` in **both** regimes
        and adds no guards, so such a Sample raises here and is recorded as a failed Sample beside
        its `long_form` flag rather than being silently decoded under different constants
        (ADR-0016/ADR-0017). Every default-configured Dataset Version is inside the short-form
        window; only a `duration_max_s` above 30 s reaches this.
        """
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
        # `batch_decode` carries no annotations upstream, so `--strict` refuses the call rather than
        # the types; one Sample per call, so the batch is always the one Hypothesis.
        decoded = self.processor.batch_decode(  # type: ignore[no-untyped-call]
            tokens, skip_special_tokens=True
        )
        return str(decoded[0])
