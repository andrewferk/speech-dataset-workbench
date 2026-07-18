"""The CLI argument surface: what `build` and `validate` accept, and what they exit with.

The pipeline behind them is a stub in this ticket, so these tests pin the parse and the
exit-code contract only — never what a build produces.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sdw.cli import main
from tests import synth


@pytest.fixture
def data_in(tmp_path: Path) -> Path:
    # A minimally-valid input: one recordings.csv row pointing at one Original. The Original is a
    # real decodable WAV because normalization now decodes every listed file and a decode failure
    # aborts (#25, ADR-0005). These tests still pin only the arg surface and exit codes.
    d = tmp_path / "data-in"
    d.mkdir()
    synth.write_wav(
        d / "a.wav",
        freq_hz=400.0,
        amp_dbfs=-18.0,
        duration_s=0.5,
        sample_rate=16000,
        bit_depth=16,
        channels=1,
    )
    (d / "recordings.csv").write_text(
        "path,speaker_id,session_id,prompt_text,device,environment\n"
        "a.wav,spk_a,sess_1,Hello there.,mic,quiet room\n",
        encoding="utf-8",
    )
    return d


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


class TestDecodeGate:
    """An undecodable Original aborts *both* commands (#25, ADR-0005).

    Normalization is where ADR-0005's ingest gate actually fires, and it runs in `validate` too:
    a green `validate` promises `build` will not hit a hard error, so both must abort on the same
    input. The abort leaves no durable output — a Dataset Version always stands for the whole
    intended input, never a silent subset.
    """

    @pytest.fixture
    def undecodable(self, data_in: Path) -> Path:
        synth.write_non_wav(data_in / "a.wav")
        return data_in

    def test_build_aborts(self, undecodable: Path, data_out: Path) -> None:
        assert main(["build", "--data-in", str(undecodable), "--data-out", str(data_out)]) != 0
        assert not data_out.exists()

    def test_validate_aborts(self, undecodable: Path) -> None:
        assert main(["validate", "--data-in", str(undecodable)]) != 0

    @pytest.mark.parametrize("write", [synth.write_truncated_wav, synth.write_zero_frame_wav])
    def test_corrupt_and_empty_originals_abort_too(
        self, data_in: Path, data_out: Path, write: Callable[[Path], None]
    ) -> None:
        write(data_in / "a.wav")
        assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) != 0
        assert not data_out.exists()


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
