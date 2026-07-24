"""Build the consumer-facing dataset from the split Recordings (#28, ADR-0006).

The sixth pipeline stage. :func:`build_dataset` is pure — it returns the bytes-to-be of every file,
opening no path on disk — so ``dataset_version`` (#29) hashes exactly what a consumer receives and
#30 owns the atomic commit. Each kept Recording becomes one :class:`Sample`, rendered into both the
canonical and HF views from one place so they cannot drift. The Manifest carries no quality fields;
those are the operator's and live in ``reports/`` (#32, ADR-0007).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import PurePosixPath
from typing import Any

from sdw.config import Config
from sdw.ingest import Recording
from sdw.normalize import TARGET_SAMPLE_RATE
from sdw.quality import SECONDS_DP
from sdw.serialization import render_jsonl
from sdw.split import SPLIT_ORDER, SplitResult

# Mono by construction (ADR-0005); no upstream constant to borrow, so the value is named here.
NUM_CHANNELS = 1

# The one place the layout `audio/<split>/<recording_id>.wav` is spelled.
AUDIO_DIR = "audio"

# The HF `audiofolder` convention: one metadata file per folder of audio, keyed by `file_name`.
HF_METADATA_NAME = "metadata.jsonl"

# ADR-0010 hashes the emitted bytes, so if #30 encoded with anything else `dataset_version` would
# stand for a file no consumer receives — UTF-8 by contract, not by default.
ENCODING = "utf-8"


@dataclass(frozen=True)
class Sample:
    """One Manifest line, with the fields in ADR-0006's fixed key order.

    Field order here *is* the emitted key order — :func:`_line` reads it off the dataclass — so the
    two cannot drift. One Sample per kept Recording; ingest already deduped (ADR-0001).
    """

    id: str
    audio_filepath: str
    duration: float
    text: str
    # `None`, not `str | None`: v0.1 cannot carry a Perceived text, so populating the slot early
    # fails type-checking. Widening to `str | None` is v0.2's first move (ADR-0006).
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
    """The finished dataset: the Samples, and the text of every file they make.

    ``files`` maps a POSIX path (relative to the ``--data-out`` root) to that file's contents, to be
    written verbatim and encoded as :data:`ENCODING`. ``dataset.json`` is not here — it is #29's
    identity/provenance (ADR-0010) and the completeness sentinel the commit writes last (#30).
    ``samples`` is every Sample across every Split, in emission order.
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

    ``durations`` maps ``recording_id`` to the Normalized length in seconds, measured upstream from
    the frame count — a float comparison could yield a host-dependent ``duration``, and so a
    different ``dataset_version`` (ADR-0010). Every kept Recording must be present; a gap is a
    caller bug, not a Sample to skip.
    """
    samples = tuple(
        _sample(recording, result.split_of(recording), durations[recording.recording_id], config)
        for recording in _emission_order(recordings)
    )
    return Dataset(samples=samples, files=_files(samples))


def audio_path(split: str, recording_id: str) -> str:
    """Where a Recording's Normalized WAV goes: ``audio/<split>/<recording_id>.wav``.

    Relative, POSIX, and bucketed by Split (ADR-0003/0006). Exported so the stage that writes the
    WAVs agrees with the path this stage put in the Sample.
    """
    return f"{AUDIO_DIR}/{split}/{recording_id}.wav"


def _emission_order(recordings: Sequence[Recording]) -> list[Recording]:
    """Every Recording, ordered by ``recording_id``.

    A total order over content-derived ids, so reordering ``recordings.csv`` cannot change a byte of
    output or mint a new ``dataset_version`` (ADR-0006, amended by #28). :func:`_files` preserves
    this order within each Split.
    """
    return sorted(recordings, key=lambda recording: recording.recording_id)


def _sample(recording: Recording, split: str, duration: float, config: Config) -> Sample:
    """One Recording plus its Split and duration as a Sample.

    ``text`` is the Prompt text *verbatim* — ``prompt_id``'s normalization must never reach the
    transcript a model trains on (ADR-0006). ``sample_rate``/``num_channels`` describe the
    Normalized WAV, not the Original (recoverable through ``content_hash``). ``duration`` rounds to
    :data:`~sdw.quality.SECONDS_DP` — the same constant `quality.jsonl` uses, so a build cannot ship
    a Manifest and report that disagree on a Recording's length (#54).
    """
    return Sample(
        id=recording.recording_id,
        audio_filepath=audio_path(split, recording.recording_id),
        duration=round(duration, SECONDS_DP),
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

    All three ``<split>.jsonl`` are always emitted, empty ones included; the HF view only where
    audio sits beside it — a ``metadata.jsonl`` for an absent folder would point at nothing. The
    asymmetry is pinned by ADR-0006 (amended by #28). No Split is renamed — HF reads ``val`` as a
    validation split (ADR-0003/0006).
    """
    per_split = {name: [s for s in samples if s.split == name] for name in SPLIT_ORDER}
    files = {
        f"{name}.jsonl": render_jsonl(_line(s) for s in held) for name, held in per_split.items()
    }
    files.update(
        {
            f"{AUDIO_DIR}/{name}/{HF_METADATA_NAME}": render_jsonl(_hf_line(s) for s in held)
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

    ``file_name`` keeps ``audio_filepath``'s position, so the two views read as one Sample seen
    twice rather than two schemas that happen to overlap.
    """
    return dict(_hf_field(name, value) for name, value in _line(sample).items() if name != "split")


def _hf_field(name: str, value: Any) -> tuple[str, Any]:
    """One canonical field as its HF counterpart — the whole rename, key and value together.

    The key rename and the value rewrite are one transform, not two: the metadata file sits *beside*
    the audio, which is why the key is ``file_name`` and why the value loses its directories. Kept
    together so the two halves can never be changed apart.
    """
    if name != "audio_filepath":
        return name, value
    return "file_name", PurePosixPath(value).name
