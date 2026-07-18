"""`python -m sdw` is the entry point (ADR-0012: no build backend, no installed console script).

Nothing installs the package, so the entry point only resolves with src/ on the path — which
mise.toml provides locally and the CI workflow provides in the gate. These tests set it
explicitly rather than inheriting it, so they fail when the package itself is unreachable
rather than when the caller's shell happens to be unconfigured.
"""

import os
import subprocess
import sys
from pathlib import Path

from tests import synth

REPO_ROOT = Path(__file__).parents[2]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sdw", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )


def _minimal_data_in(tmp_path: Path) -> Path:
    return synth.write_minimal_data_in(tmp_path / "in")


def test_build_exits_zero(tmp_path: Path) -> None:
    data_in = _minimal_data_in(tmp_path)
    result = run("build", "--data-in", str(data_in), "--data-out", str(tmp_path / "out"))
    assert result.returncode == 0, result.stderr


def test_validate_exits_zero(tmp_path: Path) -> None:
    data_in = _minimal_data_in(tmp_path)
    result = run("validate", "--data-in", str(data_in))
    assert result.returncode == 0, result.stderr


def test_undecodable_original_exits_non_zero_with_no_data_out(tmp_path: Path) -> None:
    # The decode gate as a real process outcome: an Original that is not a decodable WAV aborts
    # `build` with a non-zero exit and leaves no --data-out behind (#25, ADR-0005/ADR-0003).
    data_in = _minimal_data_in(tmp_path)
    synth.write_non_wav(data_in / "a.wav")
    data_out = tmp_path / "out"
    result = run("build", "--data-in", str(data_in), "--data-out", str(data_out))
    assert result.returncode != 0
    assert result.stderr
    assert not data_out.exists()


def test_hard_error_exits_non_zero(tmp_path: Path) -> None:
    result = run("validate", "--data-in", str(tmp_path / "absent"))
    assert result.returncode != 0
    assert result.stderr
