"""Reading a Run directory: the two files, the per-line schema, and the one integrity check.

Scoring's entire input (ADR-0017). The Record and the provenance are parsed *here*, by the eval
path, with nothing imported from :mod:`sdw.manifest` or :mod:`sdw.provenance` — that stranger
consumption is the dogfood, and a second copy of the contract inside the repo would go stale
silently (ADR-0017/ADR-0023). :mod:`sdw.serialization` is the one permitted exception, and this
module does not need it: it reads, it never writes.

Two refusals live here, and nothing else does. `run.json` is the completeness sentinel, so a Run
without one crashed and cannot be scored (ADR-0017/ADR-0021); `record_line_count` is the *only*
integrity check available to a stage forbidden to reach outside its Run directory, and it exists to
stop a Report silently scoring a subset (ADR-0019/ADR-0020). There is no whole-file hash.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdw.errors import HardError

RECORD_FILENAME = "hypotheses.jsonl"
PROVENANCE_FILENAME = "run.json"

# ADR-0004's order, reimplemented rather than imported: `SPLIT_ORDER` is named by ADR-0017 as the
# shortcut that looks harmless and ends the dogfood (ADR-0022).
SPLIT_ORDER = ("train", "val", "test")

# A sentinel distinct from `null`, so an *absent* nullable field is still a parse error — the
# Record's schema is fixed, and a line missing `error` is malformed rather than error-free.
_MISSING = object()


@dataclass(frozen=True)
class Sample:
    """One Hypothesis Record line, in ADR-0019's fixed key order.

    ``hypothesis`` is ``None`` iff Transcription failed — ``""`` is the model's output and ``None``
    is the absence of one, a distinction ADR-0017 requires and ADR-0019 encodes exactly once.
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

    @property
    def failed(self) -> bool:
        return self.hypothesis is None


@dataclass(frozen=True)
class Run:
    """A Run directory as read: the Record, and `run.json` verbatim.

    ``provenance`` is kept as parsed rather than projected onto a type, because ADR-0024 has the
    Report echo the file **whole** into the JSON rendering — a projection would be a second
    relevance decision that drifts from ADR-0020's tier table the first time a field is added.
    """

    record: tuple[Sample, ...]
    provenance: Mapping[str, Any]


def read(directory: Path) -> Run:
    """Read the Run at ``directory``. Opens nothing else, and writes nothing (ADR-0021).

    Raises :class:`~sdw.errors.HardError` for an absent directory, a missing sentinel, an
    unparseable Record, or a Record disagreeing with its own ``record_line_count``.
    """
    if not directory.is_dir():
        raise HardError(f"--run is not a directory: {directory}")

    # The sentinel is checked before the Record, so a Run that crashed mid-Transcription is named
    # incomplete rather than reported as some downstream parse failure (ADR-0017's write order).
    provenance = _read_provenance(directory / PROVENANCE_FILENAME)
    record = _read_record(directory / RECORD_FILENAME)
    _check_line_count(record, provenance, directory / PROVENANCE_FILENAME)
    return Run(record=record, provenance=provenance)


def _read_provenance(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise HardError(
            f"incomplete Run: {path.parent} has no {PROVENANCE_FILENAME}, so Transcription "
            "never finished and its Hypothesis Record is a partial prefix (ADR-0017)."
        )
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise HardError(f"cannot parse {path}: {error}") from error
    if not isinstance(provenance, dict):
        raise HardError(f"cannot parse {path}: expected a JSON object")
    return provenance


def _read_record(path: Path) -> tuple[Sample, ...]:
    if not path.is_file():
        raise HardError(f"Run has no Hypothesis Record: {path} is missing (ADR-0019).")
    text = path.read_text(encoding="utf-8")
    return tuple(
        _sample(line, path, number)
        for number, line in enumerate(text.splitlines(), start=1)
        if line
    )


def _check_line_count(
    record: tuple[Sample, ...], provenance: Mapping[str, Any], path: Path
) -> None:
    """The only integrity check that exists. Raises if the file disagrees with its own count.

    A Record truncated after the Run finished is otherwise indistinguishable from a shorter corpus
    (ADR-0019/ADR-0020).
    """
    expected = provenance.get("record_line_count")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise HardError(f"cannot parse {path}: record_line_count is missing or not an integer.")
    if len(record) != expected:
        raise HardError(
            f"truncated Hypothesis Record: {RECORD_FILENAME} holds {len(record)} line(s), but "
            f"{PROVENANCE_FILENAME} records record_line_count {expected} (ADR-0019)."
        )


def _sample(line: str, path: Path, number: int) -> Sample:
    try:
        fields = json.loads(line)
    except ValueError as error:
        raise HardError(f"cannot parse {path} line {number}: {error}") from error
    if not isinstance(fields, dict):
        raise HardError(f"cannot parse {path} line {number}: expected a JSON object")
    read = _Line(fields, f"{path} line {number}")
    return Sample(
        id=read.text("id"),
        reference=read.text("reference"),
        hypothesis=read.optional_text("hypothesis"),
        error=read.optional_text("error"),
        split=read.text("split"),
        session_id=read.text("session_id"),
        speaker_id=read.text("speaker_id"),
        prompt_id=read.text("prompt_id"),
        device=read.text("device"),
        environment=read.text("environment"),
        duration=read.number("duration"),
        long_form=read.flag("long_form"),
    )


@dataclass(frozen=True)
class _Line:
    """One Record line's fields, read by name against ADR-0019's frozen schema.

    Every reader refuses a missing key as well as a wrong type: the schema is fixed, so a line
    missing `error` is malformed rather than error-free.
    """

    fields: Mapping[str, Any]
    where: str

    def text(self, key: str) -> str:
        value = self.fields.get(key)
        if not isinstance(value, str):
            raise self._refuse(key, "a string")
        return value

    def optional_text(self, key: str) -> str | None:
        value = self.fields.get(key, _MISSING)
        if value is None or isinstance(value, str):
            return value
        raise self._refuse(key, "a string or null")

    def number(self, key: str) -> float:
        value = self.fields.get(key)
        # `bool` is an `int` in Python and is not a duration.
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise self._refuse(key, "a number")
        return float(value)

    def flag(self, key: str) -> bool:
        value = self.fields.get(key)
        if not isinstance(value, bool):
            raise self._refuse(key, "a boolean")
        return value

    def _refuse(self, key: str, expected: str) -> HardError:
        return HardError(f"cannot parse {self.where}: {key} is missing or not {expected}")
