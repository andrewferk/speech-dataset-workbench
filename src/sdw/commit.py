"""The only writer of `--data-out`: staging, the sentinel, and the atomic swap (#30, ADR-0003).

`--data-out` is touched in exactly one place — here. That is the whole of ADR-0003's atomicity
guarantee ("Nothing touches `<data-out>` during the run"): the stages write their artifacts into the
sibling staging tree, never the live output, and only this module promotes that tree into
`--data-out`. The stages reach the staging tree by two routes — `images` and `reports` write their
PNGs and JSONL into it directly (a PNG is not text to hand back), while `manifest` and `provenance`
stay pure and return `{path: text}` maps that :func:`write_files` renders. Either way there is one
place that knows the `.tmp`/`.old` protocol, and one place that decides when a build is finished.

The protocol is three moves and a cleanup:

- **Prepare.** Before anything is written, clear the sibling `<data-out>.tmp` and `<data-out>.old`.
  Either surviving into a fresh run means the previous one crashed mid-build or mid-swap; neither is
  a backup to keep (ADR-0003 deletes `.old` after a successful swap, so a durable one is debris).

- **Stage.** The stages write the whole tree into `<data-out>.tmp`. Nothing touches `--data-out`
  yet, so an abort here leaves the last good Dataset untouched — that is what :func:`discard` is.

- **Commit.** `dataset.json` — the completeness sentinel — is written into the staging tree *last*,
  by this module and only by this module, so "written last" is structural rather than a caller's
  discipline. Then the swap: `--data-out` → `.old` (if present), `.tmp` → `--data-out`, delete
  `.old`. The only window without a live `--data-out` is the sub-millisecond gap between the two
  renames, and re-running recovers it because the build is deterministic and idempotent.

There is no deletion command and no per-file pruning anywhere: the swap is the only cleanup, and a
build that wants to drop a Recording does so by the operator editing `recordings.csv` and rebuilding
(ADR-0003). Originals under `--data-in` are never read for writing here at all.
"""

import shutil
from collections.abc import Mapping
from pathlib import Path

from sdw.errors import HardError
from sdw.manifest import ENCODING

# The two siblings the protocol uses, both beside `--data-out` so every move is a same-filesystem
# rename. `.tmp` is the tree under construction; `.old` is the superseded tree during the swap.
STAGING_SUFFIX = ".tmp"
PREVIOUS_SUFFIX = ".old"


def prepare(data_out: Path) -> Path:
    """Clear stale siblings and return the staging path to build into.

    Runs before the first write of every build: a `<data-out>.tmp` or `<data-out>.old` found here
    is debris from a crashed run, cleared so recovery is nothing more than re-running (ADR-0003).
    `--data-out` itself is not touched — it is the last good Dataset until the swap succeeds.
    """
    staging = _sibling(data_out, STAGING_SUFFIX)
    _rmtree(staging)
    _rmtree(_sibling(data_out, PREVIOUS_SUFFIX))
    return staging


def write_files(directory: Path, files: Mapping[str, str]) -> None:
    """Write ``files`` — path-relative-to-``directory`` → text — creating parent directories.

    The one place a `Dataset.files`/`Provenance.files` mapping becomes bytes, encoded as
    :data:`~sdw.manifest.ENCODING` because `dataset_version` hashes exactly these bytes (ADR-0010):
    the encoding is the manifest's contract, not the host locale's default.
    """
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=ENCODING)


def commit(staging: Path, data_out: Path, sentinel: Mapping[str, str]) -> None:
    """Write the sentinel into ``staging`` last, then swap it into ``data_out`` (ADR-0003).

    ``sentinel`` is `dataset.json`'s `{name: text}` — passed in rather than pre-written so that
    "the completeness sentinel is written last" is enforced here, not trusted to the caller. After
    it lands, the swap: `data_out` → `.old` if it exists, `staging` → `data_out`, delete `.old`.

    Raises :class:`~sdw.errors.HardError` if `data_out` is a regular file rather than a directory
    or absent — an operator mistake that must surface as the tool's abort, with the pre-existing
    `data_out` left as it was, not as a half-completed rename.
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

    Absent staging is not an error — an abort before the first write leaves none, and this runs
    from a `finally` either way.
    """
    _rmtree(staging)


def _sibling(data_out: Path, suffix: str) -> Path:
    """`<data-out>`'s sibling with ``suffix`` on its name — same parent, so same filesystem."""
    return data_out.with_name(data_out.name + suffix)


def _rmtree(path: Path) -> None:
    """Remove ``path`` and everything under it if it exists; a no-op when it does not."""
    shutil.rmtree(path, ignore_errors=True)
