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

REPO_ROOT = Path(__file__).parents[2]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sdw", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )


def test_build_exits_zero(tmp_path: Path) -> None:
    data_in = tmp_path / "in"
    data_in.mkdir()
    result = run("build", "--data-in", str(data_in), "--data-out", str(tmp_path / "out"))
    assert result.returncode == 0, result.stderr


def test_validate_exits_zero(tmp_path: Path) -> None:
    data_in = tmp_path / "in"
    data_in.mkdir()
    result = run("validate", "--data-in", str(data_in))
    assert result.returncode == 0, result.stderr


def test_hard_error_exits_non_zero(tmp_path: Path) -> None:
    result = run("validate", "--data-in", str(tmp_path / "absent"))
    assert result.returncode != 0
    assert result.stderr
