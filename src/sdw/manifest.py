"""Turn the split Recordings into the dataset a consumer receives (#28, ADR-0006).

The sixth pipeline stage, and the first one whose output is the deliverable rather than a means to
it. Everything upstream — ingest, normalize, quality, split — exists to feed this: the per-Split
JSONL that NeMo reads with no transformation, and the ``audiofolder`` view that Hugging Face loads
with no user code. Both are emitted by the one atomic ``build``; there is no ``export`` command
(ADR-0006).

Three facts pin the shape:

- **This is a pure function and it returns bytes-to-be, not files.** :func:`build_dataset` takes
  Recordings, their Split assignments, their Normalized durations, and the effective config, and
  returns a :class:`Dataset` carrying the finished text of every file. Nothing here opens, creates,
  or names a path on disk — the commit is #30's, and ``dataset_version`` (#29) hashes exactly the
  bytes this returns, so the identity is over what a consumer actually receives.

- **Two views, one Sample.** The HF line is the canonical line with two mechanical transforms —
  ``audio_filepath`` becomes a bare ``file_name`` because the metadata sits beside the audio, and
  ``split`` is dropped because the folder *is* the split. Both are derived from one
  :class:`Sample`, in one place, so the views cannot drift into disagreeing about a Recording.

- **The Manifest carries no quality fields.** Flags are the operator's diagnostics and they live in
  ``reports/`` (#32, ADR-0007). Folding them into a Sample would entangle the consumer's
  dataset with the operator's workflow — a downstream model would train on a schema that changes
  shape whenever the tool's advisory vocabulary does.

``perceived_text`` is emitted as ``null`` on every Sample rather than omitted: the dual-annotation
model is then literal in the data, and v0.2 populates the slot in place with no schema change.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import PurePosixPath
from typing import Any

from sdw.config import Config
from sdw.ingest import Recording
from sdw.normalize import TARGET_SAMPLE_RATE
from sdw.split import SPLIT_ORDER, SplitResult

# The Normalized audio is mono by construction (ADR-0005). Unlike the sample rate there is no
# upstream constant to borrow — mono is the shape `samples` always has, not a parameter — so the
# emitted value is named here.
NUM_CHANNELS = 1

# Seconds, rounded to milliseconds: finer digits are noise from a float division, and an unrounded
# duration would put a host-independent-but-ugly repr into a byte-compared artifact (ADR-0006).
DURATION_DECIMALS = 3

# The audio subtree, and the one place the layout `audio/<split>/<recording_id>.wav` is spelled.
AUDIO_DIR = "audio"

# The HF `audiofolder` convention: one metadata file per folder of audio, keyed by `file_name`.
HF_METADATA_NAME = "metadata.jsonl"

# Canonical JSON for one Sample line: compact, UTF-8 (no \uXXXX escaping), and *not* key-sorted —
# the key order is the ADR's fixed table, carried by `Sample`'s field order, not alphabetical.
_JSON_SEPARATORS = (",", ":")

# How `Dataset.files` becomes bytes. Named here rather than left to the writer because ADR-0010
# hashes the emitted bytes: if #30 encoded with anything else, `dataset_version` would stand for a
# file no consumer receives. The text this module returns is UTF-8 by contract, not by default.
ENCODING = "utf-8"


@dataclass(frozen=True)
class Sample:
    """One Sample: one Manifest line, with the fields in ADR-0006's fixed key order.

    Field order here *is* the emitted key order — :func:`_line` reads it off the dataclass — so the
    two cannot drift and reordering a field is visibly a manifest change.

    A Sample is 1:1 with a kept Recording. Byte-identical Originals collapsed to one Recording back
    in ingest (ADR-0001), so nothing here has to dedupe: what arrives is already the kept set.
    """

    id: str
    audio_filepath: str
    duration: float
    text: str
    # `None`, not `str | None`: the type states that v0.1 *cannot* carry a Perceived text, so a
    # stage that tried to populate the slot early would fail type-checking rather than quietly ship
    # a half-annotated Dataset. Widening it to `str | None` is v0.2's first move (ADR-0006).
    perceived_text: None
    prompt_id: str
    speaker_id: str
    session_id: str
    device: str
    environment: str
    sample_rate: int
    num_channels: int
    content_hash: str
    lang: str | None
    split: str


@dataclass(frozen=True)
class Dataset:
    """The finished consumer-facing dataset: the Samples, and the text of every file they make.

    ``files`` maps a POSIX path relative to the ``--data-out`` root to that file's complete
    contents, ready to be written verbatim and encoded as :data:`ENCODING`. Handing back text
    rather than writing it is what keeps this stage pure and what lets #29 hash the emitted bytes
    and #30 own the atomic commit, without either of them re-deriving a Sample.

    ``dataset.json`` is deliberately not here: it records the Dataset's identity and provenance,
    which is #29's (ADR-0010), and it is the completeness sentinel the commit writes last (#30).

    ``samples`` is every Sample across every Split, in emission order, for the stages that want the
    Samples as data rather than as text.
    """

    samples: tuple[Sample, ...]
    files: dict[str, str]


def build_dataset(
    recordings: Sequence[Recording],
    result: SplitResult,
    durations: Mapping[str, float],
    config: Config,
) -> Dataset:
    """Build every Manifest and HF view from the split Recordings. Pure; touches no filesystem.

    ``durations`` maps ``recording_id`` to the Normalized audio's length in seconds — measured
    upstream where the decoded audio is in hand, since this stage never reads a file. It must be
    derived from the frame count, not from a float comparison, or the same Original could yield a
    different ``duration`` — and so a different ``dataset_version`` — on another machine
    (ADR-0010). Every kept Recording must be present: a gap is a caller bug, not a Sample to skip.
    """
    samples = tuple(
        _sample(recording, result.split_of(recording), durations[recording.recording_id], config)
        for recording in _emission_order(recordings)
    )
    return Dataset(samples=samples, files=_files(samples))


def audio_path(split: str, recording_id: str) -> str:
    """Where a Recording's Normalized WAV goes: ``audio/<split>/<recording_id>.wav``.

    Relative and POSIX so a ``--data-out`` tree stays portable, and bucketed by Split so
    ``ls audio/test/`` answers what is in test without parsing a manifest (ADR-0003/0006). Exported
    because the stage that writes the WAVs must agree with the path this stage put in the Sample.
    """
    return f"{AUDIO_DIR}/{split}/{recording_id}.wav"


def _emission_order(recordings: Sequence[Recording]) -> list[Recording]:
    """Every Recording, ordered by ``recording_id``.

    A total order over content-derived ids, so reordering the rows of ``recordings.csv`` — which
    changes nothing about the Dataset — cannot change a single byte of the output, and so cannot
    mint a new ``dataset_version``. The Samples are then grouped into their Splits by
    :func:`_files`, which preserves this order within each Split.
    """
    return sorted(recordings, key=lambda recording: recording.recording_id)


def _sample(recording: Recording, split: str, duration: float, config: Config) -> Sample:
    """One Recording plus its Split and duration as a Sample.

    ``text`` is the Prompt text *verbatim*: ``prompt_id``'s normalization defines only when two
    Prompts are the same and must never reach the transcript a model trains on (ADR-0006). The
    sample rate and channel count describe the Normalized WAV on disk, not the Original — whose
    native format stays recoverable through ``content_hash``.
    """
    return Sample(
        id=recording.recording_id,
        audio_filepath=audio_path(split, recording.recording_id),
        duration=round(duration, DURATION_DECIMALS),
        text=recording.prompt_text,
        perceived_text=None,
        prompt_id=recording.prompt_id,
        speaker_id=recording.speaker_id,
        session_id=recording.session_id,
        device=recording.device,
        environment=recording.environment,
        sample_rate=TARGET_SAMPLE_RATE,
        num_channels=NUM_CHANNELS,
        content_hash=recording.content_hash,
        lang=config.manifest.lang,
        split=split,
    )


def _files(samples: Sequence[Sample]) -> dict[str, str]:
    """The canonical Manifests and the HF views, keyed by path relative to ``--data-out``.

    All three ``<split>.jsonl`` are always emitted, empty ones included: a consumer that opens
    ``test.jsonl`` on a Dataset too small to fill test should read zero Samples, not crash on a
    missing file. The HF view is emitted only where there is audio beside it — ``audio/test/`` does
    not exist when test is empty, and a ``metadata.jsonl`` describing an absent folder would be a
    file pointing at nothing. HF reads ``val`` as a validation split already, so no Split is
    renamed (ADR-0003/0006).
    """
    per_split = {name: [s for s in samples if s.split == name] for name in SPLIT_ORDER}
    files = {f"{name}.jsonl": _jsonl(_line(s) for s in held) for name, held in per_split.items()}
    files.update(
        {
            f"{AUDIO_DIR}/{name}/{HF_METADATA_NAME}": _jsonl(_hf_line(s) for s in held)
            for name, held in per_split.items()
            if held
        }
    )
    return files


def _line(sample: Sample) -> dict[str, Any]:
    """The canonical Sample line: every field, in :class:`Sample`'s declared order."""
    return {field.name: getattr(sample, field.name) for field in fields(sample)}


def _hf_line(sample: Sample) -> dict[str, Any]:
    """The HF line: ``audio_filepath`` becomes a bare ``file_name``, ``split`` is dropped.

    Everything else is at parity, and ``file_name`` keeps ``audio_filepath``'s position, so the two
    views read as one Sample seen twice rather than as two schemas that happen to overlap.
    """
    return dict(_hf_field(name, value) for name, value in _line(sample).items() if name != "split")


def _hf_field(name: str, value: Any) -> tuple[str, Any]:
    """One canonical field as its HF counterpart — the whole rename, key and value together.

    Split out of the comprehension because renaming the key and rewriting the value are one
    transform, not two: the metadata file sits *beside* the audio, which is simultaneously why the
    key is ``file_name`` and why the value loses its directories. Testing that condition once keeps
    the two halves from ever being changed apart.
    """
    if name != "audio_filepath":
        return name, value
    return "file_name", PurePosixPath(value).name


def _jsonl(lines: Iterable[Mapping[str, Any]]) -> str:
    """Sample lines as JSON Lines: LF-terminated, compact separators, no trailing whitespace.

    Every line is terminated, so an empty Split yields an empty file rather than a lone newline,
    and appending a Sample is always a whole-line change. Key order is the caller's insertion order
    — ``sort_keys`` is deliberately off, since ADR-0006 fixes an order that is not alphabetical.
    """
    return "".join(
        json.dumps(line, ensure_ascii=False, separators=_JSON_SEPARATORS) + "\n" for line in lines
    )
