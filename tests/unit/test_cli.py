"""The CLI argument surface: what `build` and `validate` accept, and what they exit with.

These tests pin the parse and the exit-code contract — never what a build produces. The one
pipeline behavior asserted here is the mapping from a stage's hard error to an exit code, which
is a property of this surface: `TestDecodeGate` and `TestConfigContract` check that both commands
abort on the same input, since a green `validate` is a promise about `build`.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sdw.cli import main
from tests import synth


@pytest.fixture
def data_in(tmp_path: Path) -> Path:
    # A minimally-valid input, so these tests stay about the arg surface and exit codes. The
    # abort-case tests below overwrite `a.wav` to make it fail.
    return synth.write_minimal_data_in(tmp_path / "data-in")


@pytest.fixture
def data_out(tmp_path: Path) -> Path:
    return tmp_path / "data-out"


@pytest.fixture
def config(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "config.toml"
    path.write_text("")
    yield path


class TestBuild:
    def test_accepts_data_in_and_data_out(self, data_in: Path, data_out: Path) -> None:
        assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) == 0

    def test_accepts_config(self, data_in: Path, data_out: Path, config: Path) -> None:
        argv = ["build", "--data-in", str(data_in), "--data-out", str(data_out)]
        assert main([*argv, "--config", str(config)]) == 0

    def test_requires_data_out(self, data_in: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["build", "--data-in", str(data_in)])
        assert exc.value.code != 0

    def test_requires_data_in(self, data_out: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["build", "--data-out", str(data_out)])
        assert exc.value.code != 0

    def test_missing_data_in_is_a_hard_error(self, tmp_path: Path, data_out: Path) -> None:
        absent = tmp_path / "nope"
        assert main(["build", "--data-in", str(absent), "--data-out", str(data_out)]) != 0

    def test_missing_config_is_a_hard_error(
        self, data_in: Path, data_out: Path, tmp_path: Path
    ) -> None:
        argv = ["build", "--data-in", str(data_in), "--data-out", str(data_out)]
        assert main([*argv, "--config", str(tmp_path / "nope.toml")]) != 0


class TestValidate:
    def test_accepts_data_in(self, data_in: Path) -> None:
        assert main(["validate", "--data-in", str(data_in)]) == 0

    def test_accepts_config(self, data_in: Path, config: Path) -> None:
        assert main(["validate", "--data-in", str(data_in), "--config", str(config)]) == 0

    def test_rejects_data_out(self, data_in: Path, data_out: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["validate", "--data-in", str(data_in), "--data-out", str(data_out)])
        assert exc.value.code != 0

    def test_requires_data_in(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["validate"])
        assert exc.value.code != 0

    def test_missing_data_in_is_a_hard_error(self, tmp_path: Path) -> None:
        assert main(["validate", "--data-in", str(tmp_path / "nope")]) != 0

    def test_writes_nothing(self, data_in: Path, tmp_path: Path) -> None:
        before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
        assert main(["validate", "--data-in", str(data_in)]) == 0
        assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


class TestValidateDigest:
    """`validate`'s output contract: the digest goes to stdout, and a flag is never an error.

    The metrics themselves are `test_quality.py`'s subject; what is asserted here is the surface —
    that the digest reaches stdout at all, and that a flagged Recording still exits 0. That second
    one is the whole point of the advisory model: `validate` is non-zero only on a structural or
    split failure, so a corpus full of quiet takes is a report, not a broken CI gate.
    """

    def test_digest_goes_to_stdout(self, data_in: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["validate", "--data-in", str(data_in)]) == 0
        assert "Quality: 1 recordings — 1 clean, 0 flagged" in capsys.readouterr().out

    def test_a_flagged_recording_still_exits_zero(
        self, data_in: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A 0.1 s blip: `duration_out_of_range`, and still a Sample. Nothing is dropped.
        synth.write_wav(
            data_in / "a.wav",
            freq_hz=400.0,
            amp_dbfs=-18.0,
            duration_s=0.1,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        assert main(["validate", "--data-in", str(data_in)]) == 0
        out = capsys.readouterr().out
        assert "0 clean, 1 flagged" in out
        assert "duration_out_of_range" in out

    def test_build_prints_no_digest(
        self, data_in: Path, data_out: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `build`'s digest belongs in `reports/summary.txt` (#27), not on stdout.
        assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) == 0
        assert capsys.readouterr().out == ""


class TestDecodeGate:
    """An undecodable Original aborts *both* commands (#25, ADR-0005).

    Normalization is where ADR-0005's ingest gate actually fires, and it runs in `validate` too:
    a green `validate` promises `build` will not hit a hard error on anything derivable from
    `--data-in` or `--config`, so both must abort on the same input. The abort leaves no durable
    output — a Dataset Version always stands for the whole intended input, never a silent subset.
    """

    # Every input ADR-0005 names as a structural failure, against both commands.
    BAD_ORIGINALS = [
        pytest.param(synth.write_non_wav, id="non-wav"),
        pytest.param(synth.write_wrong_container, id="decodable-but-not-wav"),
        pytest.param(synth.write_truncated_wav, id="truncated"),
        pytest.param(synth.write_zero_frame_wav, id="zero-frame"),
    ]

    @pytest.mark.parametrize("write", BAD_ORIGINALS)
    def test_build_aborts_with_no_durable_output(
        self, data_in: Path, data_out: Path, write: Callable[[Path], None]
    ) -> None:
        write(data_in / "a.wav")
        assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) != 0
        assert not data_out.exists()

    @pytest.mark.parametrize("write", BAD_ORIGINALS)
    def test_validate_aborts_on_the_same_inputs(
        self, data_in: Path, tmp_path: Path, write: Callable[[Path], None]
    ) -> None:
        write(data_in / "a.wav")
        before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
        assert main(["validate", "--data-in", str(data_in)]) != 0
        # Aborting is still writing nothing, anywhere (ADR-0002) — not even a partial artifact.
        assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


class TestConfigContract:
    """An illegal split ratio is a hard error on *both* commands (#23, ADR-0004/0007).

    The point of moving ratio validation into config loading is that `validate` — which never
    reaches the splitter — still catches it, so a green preflight promises a `build` that will
    not hard-error on config.
    """

    @pytest.fixture
    def bad_ratio(self, tmp_path: Path) -> Path:
        path = tmp_path / "bad.toml"
        path.write_text("[split]\ntrain = 0.5\nval = 0.1\ntest = 0.1\n")
        return path

    def test_validate_rejects_an_illegal_ratio(self, data_in: Path, bad_ratio: Path) -> None:
        assert main(["validate", "--data-in", str(data_in), "--config", str(bad_ratio)]) != 0

    def test_build_rejects_an_illegal_ratio(
        self, data_in: Path, data_out: Path, bad_ratio: Path
    ) -> None:
        argv = ["build", "--data-in", str(data_in), "--data-out", str(data_out)]
        assert main([*argv, "--config", str(bad_ratio)]) != 0

    def test_validate_writes_nothing_on_a_bad_config(
        self, data_in: Path, bad_ratio: Path, tmp_path: Path
    ) -> None:
        before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
        assert main(["validate", "--data-in", str(data_in), "--config", str(bad_ratio)]) != 0
        assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


class TestUsage:
    def test_no_subcommand_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code != 0

    def test_unknown_subcommand_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["frobnicate"])
        assert exc.value.code != 0


def test_hard_error_names_the_cause(
    data_out: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    absent = tmp_path / "nope"
    assert main(["build", "--data-in", str(absent), "--data-out", str(data_out)]) != 0
    assert str(absent) in capsys.readouterr().err
