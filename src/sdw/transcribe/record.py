"""The Hypothesis Record: `hypotheses.jsonl`, appended as Transcription proceeds (ADR-0019).

One file for the entire Dataset Version — Splits are a field, not a directory — with lines ordered
by `id` ascending, which is also the order they are transcribed in. Append order *is* final order,
so an interrupted Record is a valid prefix rather than an unordered fragment, and each line is
flushed as it is written so the minutes already spent survive a crash (ADR-0017, ADR-0021).
"""

from dataclasses import dataclass, fields
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from sdw.serialization import render_jsonl
from sdw.transcribe.dataset import ENCODING, Sample

RECORD_NAME = "hypotheses.jsonl"

# The per-line schema's version, an opaque counter deliberately decoupled from the release cadence
# (ADR-0019). It rides in `run.json`, which is where a reader of the Record looks for it.
RECORD_VERSION = "1"

# The closed vocabulary `error` draws from — exactly one member in v0.2, because ADR-0017 moved
# every other failure into the preflight. Never free text: an exception's `str()` carries absolute
# paths, which would make two Records of the same corpus undiffable (ADR-0019).
DECODE_FAILED = "decode_failed"


@dataclass(frozen=True)
class RecordLine:
    """One line of the Hypothesis Record, with the fields in ADR-0019's fixed key order.

    Not named `Hypothesis`: the glossary reserves that for the text a model emits, which here is one
    field of the line rather than the line itself.

    Field order here *is* the emitted key order — :func:`_line` reads it off the dataclass — so the
    two cannot drift. `hypothesis` is `null` **iff** Transcription failed; `""` is the model saying
    nothing, which is a different fact and is preserved as one.
    """

    id: str
    reference: str
    hypothesis: str | None
    error: str | None
    split: str
    session_id: str
    speaker_id: str
    prompt_id: str
    device: str
    environment: str
    duration: float
    long_form: bool


def transcribed(sample: Sample, *, hypothesis: str, long_form: bool) -> RecordLine:
    """The line for a Sample the model answered for, empty answer included."""
    return _line_of(sample, hypothesis=hypothesis, error=None, long_form=long_form)


def failed(sample: Sample, *, long_form: bool) -> RecordLine:
    """The line for a Sample whose decode raised.

    Present, not absent, and carrying every other field: a Report that cannot say *which* Sessions
    and Devices lost Samples has disclosed a count and hidden the pattern (ADR-0019).
    """
    return _line_of(sample, hypothesis=None, error=DECODE_FAILED, long_form=long_form)


class RecordWriter:
    """Append-only writer for one Run's `hypotheses.jsonl`, flushed line by line.

    Counts what it wrote, which is what `run.json`'s `record_line_count` states — the only integrity
    check the Record carries, and the one thing standing between a Record truncated after the Run
    and a Report that silently scores a subset (ADR-0019, ADR-0020).
    """

    def __init__(self, path: Path) -> None:
        # A plain handle, not `build`'s atomic staging — see :mod:`sdw.transcribe.pipeline`
        # (ADR-0021).
        self._handle = path.open("w", encoding=ENCODING, newline="\n")
        self.line_count = 0

    def append(self, line: RecordLine) -> None:
        self._handle.write(render_jsonl([_line(line)]))
        # Per line, not per Run: a crash must leave a valid prefix, not a buffer (ADR-0019).
        self._handle.flush()
        self.line_count += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._handle.close()


def _line_of(
    sample: Sample, *, hypothesis: str | None, error: str | None, long_form: bool
) -> RecordLine:
    return RecordLine(
        id=sample.id,
        reference=sample.reference,
        hypothesis=hypothesis,
        error=error,
        split=sample.split,
        session_id=sample.session_id,
        speaker_id=sample.speaker_id,
        prompt_id=sample.prompt_id,
        device=sample.device,
        environment=sample.environment,
        duration=sample.duration,
        long_form=long_form,
    )


def _line(line: RecordLine) -> dict[str, Any]:
    """Every field, in :class:`RecordLine`'s declared order."""
    return {field.name: getattr(line, field.name) for field in fields(line)}
