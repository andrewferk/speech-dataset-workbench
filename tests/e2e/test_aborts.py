"""The abort table: every structural failure exits non-zero and leaves no durable `--data-out`.

ADR-0008's headline abort coverage, one synthesized case per failure class, all asserting the same
two-part contract through `main(argv)`: a non-zero exit **and** no `--data-out` on disk. A hard
error is not a partial build — a Dataset Version always stands for the whole intended input, so a
run that cannot honor that must commit nothing at all (ADR-0003/0005/0007).

Each case starts from one valid baseline — the committed reference `--data-in` — and breaks it a
single way, so the table reads as "the same good input, made bad five different ways." The classes
are the ones ADR-0008 enumerates: an undecodable Original, a zero-frame WAV, a malformed
`recordings.csv`, a `path` that escapes `--data-in`, and an illegal split ratio.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sdw.cli import main
from tests import synth

# A case breaks the baseline `--data-in` in place and returns any extra argv the break needs
# (only the config-driven ratio case uses it); everything else returns no extra flags.
Break = Callable[[Path], list[str]]

# One listed Original in the reference tree, overwritten to trigger the decode-gate cases.
_LISTED_WAV = "passthrough_16k_mono.wav"


def _undecodable(data_in: Path) -> list[str]:
    synth.write_non_wav(data_in / _LISTED_WAV)
    return []


def _zero_frame(data_in: Path) -> list[str]:
    synth.write_zero_frame_wav(data_in / _LISTED_WAV)
    return []


def _malformed_csv(data_in: Path) -> list[str]:
    # A header missing the required metadata columns: `recordings.csv` is rejected before any audio
    # is read (#24, ADR-0006), so the break need not touch a WAV.
    (data_in / "recordings.csv").write_text("path,speaker_id\na.wav,spk_a\n", encoding="utf-8")
    return []


def _path_is_absolute(data_in: Path) -> list[str]:
    # An absolute `path` reaches outside the read-only `--data-in`; the parser rejects it as
    # non-relative before opening anything (#24, ADR-0006/ADR-0003's "within --data-in" rule).
    synth.write_recordings_csv(data_in, [{"path": "/etc/passwd"}])
    return []


def _path_traverses_out_of_data_in(data_in: Path) -> list[str]:
    # A relative `path` that climbs out with `..` — the second escape mechanism ADR-0006 names,
    # a different code path from the absolute case, and rejected before any file is opened.
    synth.write_recordings_csv(data_in, [{"path": "../evil.wav"}])
    return []


def _illegal_ratio(data_in: Path) -> list[str]:
    # Ratios that do not sum to 1.0 are a structural config error caught in preflight (ADR-0004),
    # not a soft flag — the one case carried by `--config` rather than a broken input.
    config = data_in / "bad.toml"
    config.write_text("[split]\ntrain = 0.5\nval = 0.1\ntest = 0.1\n", encoding="utf-8")
    return ["--config", str(config)]


ABORT_CASES = [
    pytest.param(_undecodable, id="non-wav"),
    pytest.param(_zero_frame, id="zero-frame-wav"),
    pytest.param(_malformed_csv, id="malformed-csv"),
    pytest.param(_path_is_absolute, id="path-absolute"),
    pytest.param(_path_traverses_out_of_data_in, id="path-traverses-out"),
    pytest.param(_illegal_ratio, id="illegal-ratio"),
]


@pytest.mark.parametrize("break_input", ABORT_CASES)
def test_build_aborts_with_no_durable_data_out(tmp_path: Path, break_input: Break) -> None:
    data_in = tmp_path / "in"
    synth.write_reference_tree(data_in)
    extra = break_input(data_in)
    data_out = tmp_path / "out"

    exit_code = main(["build", "--data-in", str(data_in), "--data-out", str(data_out), *extra])

    assert exit_code != 0
    assert not data_out.exists()
    # Not even a staging sibling survives: the abort is invisible on disk (ADR-0003).
    assert not (tmp_path / "out.tmp").exists()


@pytest.mark.parametrize("break_input", ABORT_CASES)
def test_the_break_names_the_cause_on_stderr(
    tmp_path: Path, break_input: Break, capsys: pytest.CaptureFixture[str]
) -> None:
    # The abort is legible, not a bare non-zero: `cli.main` prints `error: ...` to stderr for every
    # HardError, so an operator sees *why* the build refused (cli.py).
    data_in = tmp_path / "in"
    synth.write_reference_tree(data_in)
    extra = break_input(data_in)

    assert (
        main(["build", "--data-in", str(data_in), "--data-out", str(tmp_path / "out"), *extra]) != 0
    )
    assert capsys.readouterr().err.strip()
