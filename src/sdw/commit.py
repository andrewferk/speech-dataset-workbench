"""The only writer of `--data-out`: staging, the sentinel, and the atomic swap (#30, ADR-0003, #64).

`--data-out` is touched here and nowhere else — the whole of ADR-0003's atomicity guarantee. The
stages write into the sibling staging tree; only this module promotes it, and :mod:`sdw.staging` is
its sole caller (rendering the `manifest`/`provenance` text maps that :func:`write_files` writes).

The protocol: clear stale `.tmp`/`.old` siblings (debris from a crashed run), stage the tree into
`<data-out>.tmp`, write `dataset.json` — the completeness sentinel — last, then swap
(`--data-out`→`.old`, `.tmp`→`--data-out`, delete `.old`). The sentinel is written last *by this
module*, so ordering is structural, not caller discipline. The swap is the only cleanup; there is no
delete command and Originals under `--data-in` are never read for writing here (ADR-0003).
"""

import shutil
from collections.abc import Mapping
from pathlib import Path

from sdw.errors import HardError
from sdw.manifest import ENCODING

# Both siblings of `--data-out`, so every move is a same-filesystem rename. `.tmp` is the tree under
# construction; `.old` is the superseded tree during the swap.
STAGING_SUFFIX = ".tmp"
PREVIOUS_SUFFIX = ".old"


def prepare(data_out: Path) -> Path:
    """Clear stale siblings and return the staging path to build into (ADR-0003).

    A `<data-out>.tmp` or `<data-out>.old` found here is debris from a crashed run, so recovery is
    nothing more than re-running. `--data-out` itself is not touched — it is the last good Dataset
    until the swap succeeds.
    """
    staging = _sibling(data_out, STAGING_SUFFIX)
    _rmtree(staging)
    _rmtree(_sibling(data_out, PREVIOUS_SUFFIX))
    return staging


def write_files(directory: Path, files: Mapping[str, str]) -> None:
    """Write ``files`` — path-relative-to-``directory`` → text — creating parent directories.

    Encoded as :data:`~sdw.manifest.ENCODING` because `dataset_version` hashes exactly these bytes
    (ADR-0010): the encoding is the manifest's contract, not the host locale's default.
    """
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=ENCODING)


def commit(staging: Path, data_out: Path, sentinel: Mapping[str, str]) -> None:
    """Write the sentinel into ``staging`` last, then swap it into ``data_out`` (ADR-0003).

    ``sentinel`` is `dataset.json`'s `{name: text}`, passed in rather than pre-written so "the
    completeness sentinel is written last" is enforced here, not trusted to the caller. Raises
    :class:`~sdw.errors.HardError` if `data_out` exists as a regular file rather than a directory,
    leaving the pre-existing `data_out` as it was rather than half-swapped.
    """
    if data_out.exists() and not data_out.is_dir():
        raise HardError(f"--data-out is not a directory: {data_out}")
    write_files(staging, sentinel)
    previous = _sibling(data_out, PREVIOUS_SUFFIX)
    _rmtree(previous)
    if data_out.exists():
        data_out.rename(previous)
    staging.rename(data_out)
    _rmtree(previous)


def discard(staging: Path) -> None:
    """Delete the staging tree on abort; nothing else is touched (ADR-0003).

    Absent staging is not an error — an abort before the first write leaves none, and this runs from
    a `finally` either way.
    """
    _rmtree(staging)


def _sibling(data_out: Path, suffix: str) -> Path:
    """`<data-out>`'s sibling with ``suffix`` on its name — same parent, so same filesystem."""
    return data_out.with_name(data_out.name + suffix)


def _rmtree(path: Path) -> None:
    """Remove ``path`` and everything under it if it exists; a no-op when it does not."""
    shutil.rmtree(path, ignore_errors=True)
