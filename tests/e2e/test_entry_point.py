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
    # A minimally-valid --data-in: one recordings.csv row pointing at one real WAV. It has to
    # decode — normalization runs in both commands and a decode failure aborts (#25, ADR-0005).
    data_in = tmp_path / "in"
    data_in.mkdir()
    synth.write_wav(
        data_in / "a.wav",
        freq_hz=400.0,
        amp_dbfs=-18.0,
        duration_s=0.5,
        sample_rate=16000,
        bit_depth=16,
        channels=1,
    )
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
