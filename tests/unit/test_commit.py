"""The commit protocol in isolation: staging, the sentinel, and the swap (#30, ADR-0003).

These tests drive :mod:`sdw.commit` directly with hand-built trees, so they say what the protocol
guarantees without a Dataset's worth of audio in the way. What a real `build` puts *through* the
protocol is `test_pipeline_commit.py`; the exhaustive table of abort triggers is #11.
"""

from pathlib import Path

import pytest

from sdw import commit
from sdw.errors import HardError


def _tree(root: Path, files: dict[str, str]) -> Path:
    """A directory holding ``files``, keyed by path relative to ``root``."""
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _read(root: Path) -> dict[str, str]:
    """Every file under ``root`` as relative-POSIX-path → text, for whole-tree comparisons."""
    return {
        str(path.relative_to(root).as_posix()): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestPrepare:
    """The next run starts by clearing what a crashed one left behind."""

    def test_returns_a_sibling_staging_path(self, tmp_path: Path) -> None:
        # A sibling, not a child: same parent means same filesystem, which is what makes the
        # commit a rename rather than a copy (ADR-0003).
        staging = commit.prepare(tmp_path / "out")
        assert staging.parent == tmp_path
        assert staging.name == "out.tmp"

    def test_stale_staging_is_discarded(self, tmp_path: Path) -> None:
        data_out = tmp_path / "out"
        _tree(tmp_path / "out.tmp", {"images/leftover.png": "from a crashed run"})
        assert commit.prepare(data_out) == tmp_path / "out.tmp"
        assert not (tmp_path / "out.tmp").exists()

    def test_stale_previous_is_discarded(self, tmp_path: Path) -> None:
        # `.old` only ever exists mid-swap, so finding one means a crash landed between the two
        # renames. It is the superseded tree, never a backup to keep (ADR-0003).
        _tree(tmp_path / "out.old", {"dataset.json": "{}"})
        commit.prepare(tmp_path / "out")
        assert not (tmp_path / "out.old").exists()

    def test_a_pre_existing_data_out_is_left_alone(self, tmp_path: Path) -> None:
        data_out = _tree(tmp_path / "out", {"dataset.json": "the last good build"})
        commit.prepare(data_out)
        assert _read(data_out) == {"dataset.json": "the last good build"}


class TestWriteFiles:
    """Text in, files out — the one place a `Dataset.files` mapping becomes bytes."""

    def test_writes_every_file_creating_parents(self, tmp_path: Path) -> None:
        files = {"train.jsonl": '{"id":"a"}\n', "audio/train/metadata.jsonl": '{"x":1}\n'}
        commit.write_files(tmp_path, files)
        assert _read(tmp_path) == files

    def test_writes_utf8_regardless_of_locale(self, tmp_path: Path) -> None:
        # The encoding is a contract, not a platform default: `dataset_version` hashes these bytes
        # (ADR-0010), so a cp1252 host must not mint a different id for the same Dataset.
        commit.write_files(tmp_path, {"train.jsonl": '{"text":"café"}\n'})
        assert (tmp_path / "train.jsonl").read_bytes() == '{"text":"café"}\n'.encode()


class TestCommitSwap:
    """The two renames, and the sentinel that goes in immediately before them."""

    def test_staged_tree_becomes_data_out(self, tmp_path: Path) -> None:
        staging = _tree(tmp_path / "out.tmp", {"train.jsonl": "a\n"})
        commit.commit(staging, tmp_path / "out", {"dataset.json": "{}\n"})
        assert _read(tmp_path / "out") == {"dataset.json": "{}\n", "train.jsonl": "a\n"}

    def test_the_sentinel_is_written_by_commit_and_not_before(self, tmp_path: Path) -> None:
        # `dataset.json` is not something a caller can forget or write early: it reaches disk only
        # through this argument, so "written last" is structural rather than a matter of ordering
        # the calls correctly (ADR-0003).
        staging = _tree(tmp_path / "out.tmp", {"train.jsonl": "a\n"})
        assert not (staging / "dataset.json").exists()
        commit.commit(staging, tmp_path / "out", {"dataset.json": '{"v":1}\n'})
        assert (tmp_path / "out" / "dataset.json").read_text(encoding="utf-8") == '{"v":1}\n'

    def test_a_previous_tree_is_replaced_wholesale(self, tmp_path: Path) -> None:
        # Replaced, not merged: a file the new build does not emit must not survive from the old
        # one, or `--data-out` would accumulate artifacts no manifest points at (ADR-0003).
        _tree(tmp_path / "out", {"train.jsonl": "old\n", "images/gone.png": "stale"})
        staging = _tree(tmp_path / "out.tmp", {"train.jsonl": "new\n"})
        commit.commit(staging, tmp_path / "out", {"dataset.json": "{}\n"})
        assert _read(tmp_path / "out") == {"dataset.json": "{}\n", "train.jsonl": "new\n"}

    def test_no_siblings_survive_a_successful_commit(self, tmp_path: Path) -> None:
        _tree(tmp_path / "out", {"train.jsonl": "old\n"})
        staging = _tree(tmp_path / "out.tmp", {"train.jsonl": "new\n"})
        commit.commit(staging, tmp_path / "out", {"dataset.json": "{}\n"})
        assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]

    def test_committing_over_a_file_is_a_hard_error(self, tmp_path: Path) -> None:
        # `--data-out` naming a regular file is an operator mistake, and it has to surface as the
        # tool's own abort rather than as an `OSError` from the middle of a rename.
        (tmp_path / "out").write_text("not a directory", encoding="utf-8")
        staging = _tree(tmp_path / "out.tmp", {"train.jsonl": "a\n"})
        with pytest.raises(HardError):
            commit.commit(staging, tmp_path / "out", {"dataset.json": "{}\n"})
        assert (tmp_path / "out").read_text(encoding="utf-8") == "not a directory"


class TestDiscard:
    """Abort: the staging goes, and nothing else does."""

    def test_discards_staging_and_preserves_data_out(self, tmp_path: Path) -> None:
        data_out = _tree(tmp_path / "out", {"dataset.json": "the last good build"})
        staging = _tree(tmp_path / "out.tmp", {"train.jsonl": "half a build\n"})
        commit.discard(staging)
        assert not staging.exists()
        assert _read(data_out) == {"dataset.json": "the last good build"}

    def test_discarding_absent_staging_is_not_an_error(self, tmp_path: Path) -> None:
        # An abort before the first write leaves no staging at all, and the cleanup path runs the
        # same either way — it is a `finally`, not a conditional.
        commit.discard(tmp_path / "out.tmp")
