"""Read a built Dataset Version the way a stranger would (#164, ADR-0017).

Every name this module needs from v0.1's output — the descriptor's keys, the three Manifest
filenames, the per-Sample field list — is spelled here rather than imported from `sdw.manifest` or
`sdw.provenance`. That duplication *is* the dogfood: if the Manifest is under-specified, this is the
code that finds out, and a field drifting upstream turns the transcribe suite red instead of
silently agreeing with itself.

The canonical per-Split JSONL is read, never the Hugging Face view under `audio/<split>/` — that
view exists and would half-work, which is why the choice is on the record (ADR-0017).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdw.errors import HardError

# The descriptor at the `--dataset` root; its absence is "not a Dataset Version" (ADR-0017).
DESCRIPTOR_NAME = "dataset.json"

# ADR-0006's three canonical Manifests. Reimplemented, not imported: a total order over `id` means
# nothing here has to agree with `SPLIT_ORDER` about which Split comes first (ADR-0019).
MANIFEST_NAMES = ("train.jsonl", "val.jsonl", "test.jsonl")

# ADR-0006 emits UTF-8 by contract; a stranger reading it states the encoding rather than inheriting
# the platform default.
ENCODING = "utf-8"


@dataclass(frozen=True)
class Sample:
    """One Manifest line, narrowed to what Transcription and the Record need.

    `reference` is v0.1's `text` renamed to the evaluation **role** it plays here (ADR-0015,
    ADR-0019); `duration` is carried verbatim so the Record reproduces the Manifest's rounding
    rather than recomputing it.
    """

    id: str
    reference: str
    split: str
    session_id: str
    speaker_id: str
    prompt_id: str
    device: str
    environment: str
    duration: float
    audio_filepath: str


@dataclass(frozen=True)
class Descriptor:
    """`dataset.json`, narrowed to the provenance `run.json` quotes (ADR-0020).

    `tool_version` is the tool that **built** the dataset — one of three occurrences, none assumed
    equal to another. `lang` is `[manifest].lang` as the build recorded it, read once because it is
    uniform across the Run (ADR-0016).
    """

    dataset_version: str
    tool_version: str
    manifest_version: str
    lang: str | None


@dataclass(frozen=True)
class DatasetVersion:
    """A built Dataset Version, read read-only: its descriptor and every Sample it holds.

    `samples` is ordered by `id` ascending, globally across all Splits — which is also the order
    Transcription processes them in, and therefore the Record's line order (ADR-0019).
    """

    root: Path
    descriptor: Descriptor
    samples: tuple[Sample, ...]

    def audio_path(self, sample: Sample) -> Path:
        """Where a Sample's Normalized audio sits, resolved under the dataset root."""
        return self.root / sample.audio_filepath


def read_descriptor(root: Path) -> Descriptor:
    """Parse `<root>/dataset.json`, or abort naming what is missing.

    `lang` is read from the descriptor's effective `config`, which is where ADR-0016 points
    (`[manifest].lang`) — not off a Manifest line, where the same fact appears per Sample and could
    disagree with itself.
    """
    document = _read_json(root / DESCRIPTOR_NAME, missing="--dataset is not a Dataset Version")
    if not isinstance(document, dict):
        raise HardError(f"{DESCRIPTOR_NAME} is not a JSON object: {root / DESCRIPTOR_NAME}")
    lang = document.get("config", {}).get("manifest", {}).get("lang")
    if lang is not None and not isinstance(lang, str):
        raise HardError(f"{DESCRIPTOR_NAME} has a non-string config.manifest.lang: {lang!r}")
    return Descriptor(
        dataset_version=_string(document, "dataset_version", DESCRIPTOR_NAME),
        tool_version=_string(document, "tool_version", DESCRIPTOR_NAME),
        manifest_version=_string(document, "manifest_version", DESCRIPTOR_NAME),
        lang=lang,
    )


def read_samples(root: Path) -> tuple[Sample, ...]:
    """Every Sample of every Split, ordered by `id` ascending (ADR-0019).

    Each Manifest is already `recording_id`-sorted (ADR-0006), but the three are merged into one
    total order here rather than concatenated in a Split order this package deliberately does not
    know.
    """
    samples = [
        _sample(line, path)
        for name in MANIFEST_NAMES
        for path, line in _manifest_lines(root / name)
    ]
    return tuple(sorted(samples, key=lambda sample: sample.id))


def _manifest_lines(path: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every line of one Manifest as a JSON object, or abort naming the file and line."""
    if not path.is_file():
        raise HardError(f"Manifest is missing: {path}")
    lines = []
    for number, raw in enumerate(path.read_text(encoding=ENCODING).splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError as error:
            raise HardError(f"Manifest will not parse: {path} line {number} ({error})") from error
        if not isinstance(line, dict):
            raise HardError(f"Manifest line is not a JSON object: {path} line {number}")
        lines.append((path, line))
    return lines


def _sample(line: dict[str, Any], path: Path) -> Sample:
    """One Manifest line as a :class:`Sample`, or abort naming the field that is wrong."""
    duration = line.get("duration")
    if not isinstance(duration, int | float) or isinstance(duration, bool):
        raise HardError(f"Manifest line has no numeric duration: {path} ({line.get('id')!r})")
    return Sample(
        id=_string(line, "id", path),
        reference=_string(line, "text", path),
        split=_string(line, "split", path),
        session_id=_string(line, "session_id", path),
        speaker_id=_string(line, "speaker_id", path),
        prompt_id=_string(line, "prompt_id", path),
        device=_string(line, "device", path),
        environment=_string(line, "environment", path),
        duration=float(duration),
        audio_filepath=_string(line, "audio_filepath", path),
    )


def _string(document: dict[str, Any], key: str, source: Path | str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise HardError(f"missing or non-string {key!r}: {source}")
    return value


def _read_json(path: Path, *, missing: str) -> Any:
    if not path.is_file():
        raise HardError(f"{missing}: no {path.name} at {path.parent}")
    try:
        return json.loads(path.read_text(encoding=ENCODING))
    except json.JSONDecodeError as error:
        raise HardError(f"{path.name} will not parse: {path} ({error})") from error
