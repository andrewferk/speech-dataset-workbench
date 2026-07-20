"""Atomicity through `main`: a build commits everything or nothing, and never a partial tree.

ADR-0003 promises "no partial build is ever visible as finished." This drives that promise through
whole `build` runs on the reference tree and asserts the three observable guarantees ADR-0008 puts
in scope for v0.1:

- a pre-existing `--data-out` is **byte-preserved** when a later build aborts;
- stale `.tmp`/`.old` siblings a crash left behind are **cleaned on the next start**;
- `dataset.json` is the **last artifact written** — the completeness sentinel, so a `--data-out`
  without it is by definition incomplete.
"""

from __future__ import annotations

from pathlib import Path

from sdw.cli import main
from tests import synth


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` as relative-POSIX-path → raw bytes, WAVs and PNGs included."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _build_reference(data_in: Path, data_out: Path) -> int:
    synth.write_reference_tree(data_in)
    return main(["build", "--data-in", str(data_in), "--data-out", str(data_out)])


class TestPreservation:
    """A hard error destroys nothing: the last good Dataset survives byte for byte."""

    def test_a_pre_existing_data_out_is_byte_preserved_across_an_abort(
        self, tmp_path: Path
    ) -> None:
        data_in = tmp_path / "in"
        data_out = tmp_path / "out"
        assert _build_reference(data_in, data_out) == 0
        good = _tree_bytes(data_out)

        # Break one listed Original so the next build hits the decode gate and aborts (ADR-0005).
        synth.write_non_wav(data_in / "passthrough_16k_mono.wav")
        assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) != 0

        # Not a byte moved, and no staging or superseded sibling leaked from the failed run.
        assert _tree_bytes(data_out) == good
        assert not (tmp_path / "out.tmp").exists()
        assert not (tmp_path / "out.old").exists()


class TestStaleSiblingRecovery:
    """A crashed run's debris is cleaned at the next start, so recovery is just re-running."""

    def test_stale_tmp_and_old_are_cleaned_and_absent_from_the_result(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_out = tmp_path / "out"

        # Debris a crash could strand: a half-written staging tree and a superseded `.old` left
        # mid-swap. Neither is a backup to keep, and neither must leak into the committed output.
        (tmp_path / "out.tmp" / "reports").mkdir(parents=True)
        (tmp_path / "out.tmp" / "reports" / "leftover.txt").write_text(
            "half a build", encoding="utf-8"
        )
        (tmp_path / "out.old").mkdir()
        (tmp_path / "out.old" / "dataset.json").write_text("{}", encoding="utf-8")

        assert _build_reference(data_in, data_out) == 0
        assert not (tmp_path / "out.tmp").exists()
        assert not (tmp_path / "out.old").exists()
        assert "reports/leftover.txt" not in _tree_bytes(data_out)


class TestSentinel:
    """`dataset.json` is written last, so its presence means the build finished (ADR-0003)."""

    def test_dataset_json_is_the_newest_file_in_the_tree(self, tmp_path: Path) -> None:
        # "Written last" is enforced structurally in `commit.commit` and proven directly by
        # `test_commit.py::test_the_sentinel_is_written_by_commit_and_not_before`. This is the
        # *observable* half at e2e altitude: the sentinel lands after every staged artifact and the
        # swap is a rename that preserves mtimes, so on a completed build `dataset.json` is the
        # newest file in `--data-out`. A coarse-resolution filesystem could tie the mtimes, which is
        # why the assertion is "is the newest" (ties allowed), never a false failure.
        data_in = tmp_path / "in"
        data_out = tmp_path / "out"
        assert _build_reference(data_in, data_out) == 0

        mtimes = {
            path.relative_to(data_out).as_posix(): path.stat().st_mtime_ns
            for path in data_out.rglob("*")
            if path.is_file()
        }
        assert mtimes["dataset.json"] == max(mtimes.values())
