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


def _minimal_data_in(tmp_path: Path) -> Path:
    # A minimally-valid --data-in: one recordings.csv row pointing at one Original. Ingest hashes
    # the bytes without decoding (#24), so the file contents are unconstrained here.
    data_in = tmp_path / "in"
    data_in.mkdir()
    (data_in / "a.wav").write_bytes(b"an original's bytes")
    (data_in / "recordings.csv").write_text(
        "path,speaker_id,session_id,prompt_text,device,environment\n"
        "a.wav,spk_a,sess_1,Hello there.,mic,quiet room\n",
        encoding="utf-8",
    )
    return data_in


def test_build_exits_zero(tmp_path: Path) -> None:
    data_in = _minimal_data_in(tmp_path)
    result = run("build", "--data-in", str(data_in), "--data-out", str(tmp_path / "out"))
    assert result.returncode == 0, result.stderr


def test_validate_exits_zero(tmp_path: Path) -> None:
    data_in = _minimal_data_in(tmp_path)
    result = run("validate", "--data-in", str(data_in))
    assert result.returncode == 0, result.stderr


def test_hard_error_exits_non_zero(tmp_path: Path) -> None:
    result = run("validate", "--data-in", str(tmp_path / "absent"))
    assert result.returncode != 0
    assert result.stderr
