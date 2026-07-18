"""Read ``recordings.csv``, resolve the Originals, and derive content identity (#24).

The first pipeline stage after preflight. The operator hand-authors one ``recordings.csv`` at the
``--data-in`` root and arranges the Originals in any subdirectory layout they like; this module
reads that index, resolves each declared path, and turns every row into a :class:`Recording`
carrying the content-derived ids ADR-0001 fixes. Structural problems raise :class:`HardError`
(non-zero exit, no durable output — ADR-0002/0003); a clean input returns the Recordings.

Three facts pin the shape:

- **Identity is content, not the row.** ``recording_id``/``content_hash`` hash the Original file
  *bytes* and ``prompt_id`` hashes the normalized Prompt *text* (ADR-0001), so byte-identical
  Originals collapse to one Recording and the same sentence deduplicates across Sessions. Nothing
  here decodes the audio — decodability is the normalization stage's gate (ADR-0005), a later
  ticket; this stage only reads bytes.

- **``--data-in`` is the operator's drop, not something the tool polices.** Files present under
  ``--data-in`` but absent from the CSV are silently ignored — the CSV is the authority on what is
  in the corpus, so there is nothing to warn about (#24).

- **Byte-identical Originals with conflicting metadata abort.** Two rows whose Originals hash the
  same collapse to one ``recording_id`` and one audio path; if they disagree on any manifest-bearing
  field they would imply two conflicting Manifest rows, so the run aborts rather than silently pick
  one (ADR-0013). Byte-identical rows that *agree* collapse to one Recording, as ADR-0001 requires.
"""

import csv
import hashlib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sdw.errors import HardError

# Fixed name at the --data-in root — not configurable (#24). The operator authors exactly this.
RECORDINGS_CSV = "recordings.csv"

# The exact column set (#24, ADR-0006). Order in the file is free (RFC-4180 does not fix it); the
# set must match — a missing column, or an unexpected one, is a structural error.
COLUMNS = ("path", "speaker_id", "session_id", "prompt_text", "device", "environment")

# The manifest-bearing fields that must agree when two rows share one Original. ``path`` is
# excluded on purpose: two *different* paths pointing at byte-identical bytes is the collapse case,
# not a conflict (ADR-0001/0013).
_IDENTITY_FIELDS = ("speaker_id", "session_id", "prompt_text", "device", "environment")


@dataclass(frozen=True)
class Recording:
    """One resolved Recording: its content-derived ids plus the metadata carried from the CSV.

    ``path`` is the POSIX-relative path as declared, kept relative so a ``--data-in`` set stays
    portable; a later stage joins it under ``--data-in`` to read the Original. ``recording_id`` and
    ``content_hash`` are two views of the same ``sha256`` over the Original bytes; ``prompt_id`` is
    the ``sha256`` over the normalized Prompt text (ADR-0001).
    """

    recording_id: str
    content_hash: str
    prompt_id: str
    path: str
    speaker_id: str
    session_id: str
    prompt_text: str
    device: str
    environment: str


def read_recordings(data_in: Path) -> list[Recording]:
    """Parse ``recordings.csv`` under ``data_in`` into resolved, deduplicated Recordings.

    Raises :class:`HardError` on any structural problem — a missing ``recordings.csv``, a missing
    or malformed column, a path that escapes ``--data-in``, an Original that is not on disk, or two
    byte-identical Originals with conflicting metadata — so both ``build`` and ``validate`` abort
    before doing any work.
    """
    rows = _read_rows(data_in / RECORDINGS_CSV)
    recordings = [_resolve_row(data_in, row) for row in rows]
    return _collapse(recordings)


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.is_file():
        raise HardError(f"no {RECORDINGS_CSV} at the --data-in root: {csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _check_columns(reader.fieldnames)
        rows = [_check_row(row, line) for line, row in enumerate(reader, start=2)]
    if not rows:
        raise HardError(f"{RECORDINGS_CSV} has a header but no rows; at least one is required")
    return rows


def _check_columns(fieldnames: Sequence[str] | None) -> None:
    if not fieldnames:
        raise HardError(f"{RECORDINGS_CSV} is empty; a header row is required")
    present = set(fieldnames)
    missing = [c for c in COLUMNS if c not in present]
    if missing:
        raise HardError(f"{RECORDINGS_CSV} is missing column(s): {', '.join(missing)}")
    unexpected = sorted(present - set(COLUMNS))
    if unexpected:
        raise HardError(f"{RECORDINGS_CSV} has unexpected column(s): {', '.join(unexpected)}")


def _check_row(row: dict[str, str | None], line: int) -> dict[str, str]:
    # A ragged row: DictReader pads a short row with None and collects a long row's overflow under
    # the None key. Either way the row does not match the header — a malformed CSV, so abort.
    if None in row:
        raise HardError(f"{RECORDINGS_CSV} line {line}: more fields than the header declares")
    for column in COLUMNS:
        if row[column] is None:
            raise HardError(f"{RECORDINGS_CSV} line {line}: fewer fields than the header declares")
    return {column: row[column] for column in COLUMNS}  # type: ignore[misc]


def _resolve_row(data_in: Path, row: dict[str, str]) -> Recording:
    relative = _check_path(row["path"])
    original = data_in / relative
    if not original.is_file():
        raise HardError(f"{RECORDINGS_CSV}: listed Original does not exist: {row['path']}")

    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    return Recording(
        recording_id=f"rec_{digest[:16]}",
        content_hash=f"sha256:{digest}",
        prompt_id=_prompt_id(row["prompt_text"]),
        path=row["path"],
        speaker_id=row["speaker_id"],
        session_id=row["session_id"],
        prompt_text=row["prompt_text"],
        device=row["device"],
        environment=row["environment"],
    )


def _check_path(raw: str) -> PurePosixPath:
    """Validate a declared ``path``: non-empty, POSIX, relative, and within ``--data-in``.

    An absolute path or a ``..`` component would let a ``--data-in`` set reach outside itself,
    breaking the self-contained portability the layout promises (#24), so either aborts. A
    backslash is rejected too: on POSIX it is a literal filename character, so a Windows-style
    separator would not resolve as intended and is not portable.
    """
    if not raw:
        raise HardError(f"{RECORDINGS_CSV}: empty path")
    if "\\" in raw:
        raise HardError(f"{RECORDINGS_CSV}: path is not POSIX (contains a backslash): {raw}")
    pure = PurePosixPath(raw)
    if pure.is_absolute():
        raise HardError(f"{RECORDINGS_CSV}: path must be relative, not absolute: {raw}")
    if ".." in pure.parts:
        raise HardError(f"{RECORDINGS_CSV}: path escapes --data-in with '..': {raw}")
    return pure


def _prompt_id(prompt_text: str) -> str:
    """``prm_`` + first 16 hex of ``sha256`` over the prompt text NFC-normalized, trimmed, and
    whitespace-collapsed (ADR-0001) — no case or punctuation folding, so ``"Hello."`` and
    ``"hello"`` are distinct Prompts. ``str.split()`` does the trim-and-collapse in one pass.
    """
    normalized = " ".join(unicodedata.normalize("NFC", prompt_text).split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"prm_{digest[:16]}"


def _collapse(recordings: list[Recording]) -> list[Recording]:
    """Collapse byte-identical Originals to one Recording; abort if their metadata conflicts.

    Rows are grouped by ``content_hash`` (the full hash, not the truncated ``recording_id``). Within
    a group every manifest-bearing field must agree: agreement means one true Recording seen twice
    (ADR-0001), disagreement means two conflicting Manifest rows hiding behind one audio path
    (ADR-0013) — ambiguous input, so abort. First-occurrence order is preserved.
    """
    by_hash: dict[str, Recording] = {}
    for recording in recordings:
        seen = by_hash.get(recording.content_hash)
        if seen is None:
            by_hash[recording.content_hash] = recording
            continue
        conflict = next(
            (f for f in _IDENTITY_FIELDS if getattr(seen, f) != getattr(recording, f)), None
        )
        if conflict is not None:
            raise HardError(
                f"{RECORDINGS_CSV}: {seen.path!r} and {recording.path!r} are byte-identical "
                f"Originals ({recording.recording_id}) but disagree on {conflict!r} "
                f"({getattr(seen, conflict)!r} vs {getattr(recording, conflict)!r})"
            )
    return list(by_hash.values())
