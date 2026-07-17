"""The CLI argument surface: what `build` and `validate` accept, and what they exit with.

The pipeline behind them is a stub in this ticket, so these tests pin the parse and the
exit-code contract only — never what a build produces.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from sdw.cli import main


@pytest.fixture
def data_in(tmp_path: Path) -> Path:
    d = tmp_path / "data-in"
    d.mkdir()
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
