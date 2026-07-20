"""`build` as one atomic commit, end to end (#30, ADR-0003/0008).

`test_commit.py` drives the swap protocol with hand-built trees; this drives a *real* `build`
through it and asserts the guarantees a build makes as a whole: a complete `--data-out` on success,
byte-identity across two identical runs, and — the atomicity core — a pre-existing Dataset preserved
byte for byte when a run aborts, with the stale siblings a crash leaves cleaned on the next start.

The exhaustive table of abort *triggers* is #11's. Here one trigger (an undecodable Original) stands
in for the class, because what #30 owns is the commit's response to an abort, not the catalogue of
what can cause one.
"""

from pathlib import Path

from sdw.cli import main
from tests import synth


def _data_in(root: Path, count: int) -> Path:
    """A `--data-in` of ``count`` distinct Recordings, one Session each so all three Splits fill."""
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(count):
        name = f"r{index}.wav"
        synth.write_wav(
            root / name,
            freq_hz=300.0 + 50 * index,
            amp_dbfs=-18.0,
            duration_s=0.5 + 0.1 * index,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        rows.append({"path": name, "session_id": f"sess_{index}", "prompt_text": f"Line {index}."})
    synth.write_recordings_csv(root, rows)
    return root


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` as relative-POSIX-path → raw bytes, for whole-tree comparison.

    Bytes, not text, and every file including the WAVs and PNGs: ADR-0008's build-twice-and-diff is
    over the *whole* `--data-out`, so a rebuild that changed an audio sample or a pixel must fail
    here even though no `.jsonl` moved.
    """
    return {
        str(path.relative_to(root).as_posix()): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _build(data_in: Path, data_out: Path) -> int:
    return main(["build", "--data-in", str(data_in), "--data-out", str(data_out)])


class TestSuccessfulBuild:
    """A green `build` lands a complete tree and no debris."""

    def test_produces_a_complete_data_out_end_to_end(self, tmp_path: Path) -> None:
        data_out = tmp_path / "out"
        assert _build(_data_in(tmp_path / "in", 6), data_out) == 0
        names = set(_tree_bytes(data_out))
        # The sentinel, all three canonical Manifests, and at least one Sample's WAV and Images:
        # the tree is explicable and consumer-ready, not just present.
        assert "dataset.json" in names
        assert {"train.jsonl", "val.jsonl", "test.jsonl"} <= names
        assert any(n.startswith("audio/") and n.endswith(".wav") for n in names)
        assert any(n.startswith("images/") for n in names)
        assert "reports/quality.jsonl" in names

    def test_leaves_no_tmp_or_old_siblings(self, tmp_path: Path) -> None:
        assert _build(_data_in(tmp_path / "in", 6), tmp_path / "out") == 0
        assert sorted(p.name for p in tmp_path.iterdir()) == ["in", "out"]

    def test_two_identical_builds_are_byte_identical(self, tmp_path: Path) -> None:
        # ADR-0008's build-twice-and-diff over the whole tree: WAVs and PNGs included, no golden
        # committed. Two `--data-out` from one `--data-in` must agree to the byte, which is what
        # makes a rebuild a reproducible re-emission rather than a new artifact.
        data_in = _data_in(tmp_path / "in", 6)
        assert _build(data_in, tmp_path / "out_a") == 0
        assert _build(data_in, tmp_path / "out_b") == 0
        assert _tree_bytes(tmp_path / "out_a") == _tree_bytes(tmp_path / "out_b")

    def test_rebuilding_over_a_prior_build_is_byte_identical(self, tmp_path: Path) -> None:
        # The idempotent case that matters operationally: re-running onto a live `--data-out` is a
        # byte-identical rewrite, not an error and not a drift.
        data_in = _data_in(tmp_path / "in", 6)
        data_out = tmp_path / "out"
        assert _build(data_in, data_out) == 0
        first = _tree_bytes(data_out)
        assert _build(data_in, data_out) == 0
        assert _tree_bytes(data_out) == first


class TestAbort:
    """A hard error commits nothing and destroys nothing."""

    def test_a_pre_existing_data_out_is_byte_preserved_and_the_exit_is_non_zero(
        self, tmp_path: Path
    ) -> None:
        data_in = _data_in(tmp_path / "in", 6)
        data_out = tmp_path / "out"
        assert _build(data_in, data_out) == 0
        good = _tree_bytes(data_out)

        # Turn one Original undecodable: the next build hits the decode gate and aborts (ADR-0005).
        synth.write_non_wav(data_in / "r3.wav")
        assert _build(data_in, data_out) != 0

        # The last good Dataset is untouched — not a byte changed, not the sentinel rewritten — and
        # no staging or superseded sibling survives the abort.
        assert _tree_bytes(data_out) == good
        assert sorted(p.name for p in tmp_path.iterdir()) == ["in", "out"]

    def test_a_first_build_that_aborts_leaves_no_data_out_at_all(self, tmp_path: Path) -> None:
        data_in = _data_in(tmp_path / "in", 6)
        synth.write_non_wav(data_in / "r3.wav")
        data_out = tmp_path / "out"
        assert _build(data_in, data_out) != 0
        # No half-built tree and no sentinel: an incomplete build is invisible, never a `--data-out`
        # a consumer could mistake for finished.
        assert not data_out.exists()
        assert not (tmp_path / "out.tmp").exists()


class TestStaleSiblingRecovery:
    """A crashed run's leftovers are cleaned at the next start, so recovery is just re-running."""

    def test_stale_tmp_and_old_are_cleaned_and_the_build_is_correct(self, tmp_path: Path) -> None:
        data_in = _data_in(tmp_path / "in", 6)
        data_out = tmp_path / "out"

        # Debris a crash could leave: a half-written staging tree and a superseded `.old` stranded
        # mid-swap. Neither must leak into the committed output or block the run.
        (tmp_path / "out.tmp" / "images").mkdir(parents=True)
        (tmp_path / "out.tmp" / "images" / "leftover.png").write_bytes(b"half a build")
        (tmp_path / "out.old").mkdir()
        (tmp_path / "out.old" / "dataset.json").write_text("{}", encoding="utf-8")

        assert _build(data_in, data_out) == 0
        assert sorted(p.name for p in tmp_path.iterdir()) == ["in", "out"]
        assert "images/leftover.png" not in _tree_bytes(data_out)

        # The recovered build equals a clean one — the debris changed nothing about the result.
        assert _build(data_in, tmp_path / "clean") == 0
        assert _tree_bytes(data_out) == _tree_bytes(tmp_path / "clean")
