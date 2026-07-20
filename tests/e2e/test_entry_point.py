"""`sdw` is the entry point, with `python -m sdw` as an equivalent second door (ADR-0014).

`uv sync` installs the package, so both doors resolve with nothing on `PYTHONPATH`. These tests
scrub that variable rather than setting it, and run from a temp directory rather than the repo
root: the tool's purpose is to be pointed at data living somewhere else, and CWD-independence is
the property ADR-0014 cited to rule out a flat layout. Every case runs through both doors, so
the console script and `__main__` cannot silently diverge.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import synth

# The console script lands beside the interpreter running the suite (both live in `.venv/bin`).
CONSOLE_SCRIPT = Path(sys.executable).parent / "sdw"
DOORS = pytest.mark.parametrize(
    "argv0",
    [
        pytest.param([str(CONSOLE_SCRIPT)], id="sdw"),
        pytest.param([sys.executable, "-m", "sdw"], id="python-m-sdw"),
    ],
)


def run(argv0: list[str], *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [*argv0, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def _minimal_data_in(tmp_path: Path) -> Path:
    return synth.write_minimal_data_in(tmp_path / "in")


@DOORS
def test_build_exits_zero(tmp_path: Path, argv0: list[str]) -> None:
    data_in = _minimal_data_in(tmp_path)
    result = run(
        argv0, "build", "--data-in", str(data_in), "--data-out", str(tmp_path / "out"), cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr


@DOORS
def test_validate_exits_zero(tmp_path: Path, argv0: list[str]) -> None:
    data_in = _minimal_data_in(tmp_path)
    result = run(argv0, "validate", "--data-in", str(data_in), cwd=tmp_path)
    assert result.returncode == 0, result.stderr


@DOORS
def test_undecodable_original_exits_non_zero_with_no_data_out(
    tmp_path: Path, argv0: list[str]
) -> None:
    # The decode gate as a real process outcome: an Original that is not a decodable WAV aborts
    # `build` with a non-zero exit and leaves no --data-out behind (#25, ADR-0005/ADR-0003).
    data_in = _minimal_data_in(tmp_path)
    synth.write_non_wav(data_in / "a.wav")
    data_out = tmp_path / "out"
    result = run(
        argv0, "build", "--data-in", str(data_in), "--data-out", str(data_out), cwd=tmp_path
    )
    assert result.returncode != 0
    assert result.stderr
    assert not data_out.exists()


@DOORS
def test_hard_error_exits_non_zero(tmp_path: Path, argv0: list[str]) -> None:
    result = run(argv0, "validate", "--data-in", str(tmp_path / "absent"), cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr


@DOORS
def test_both_doors_report_the_same_program_name(tmp_path: Path, argv0: list[str]) -> None:
    # A README saying `sdw build` beside a --help saying `python -m sdw` is the doc/behavior
    # drift ADR-0014 exists to remove, so the name is pinned rather than derived from argv[0].
    result = run(argv0, "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: sdw ")
