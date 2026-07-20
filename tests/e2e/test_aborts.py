"""The abort table: every structural failure exits non-zero and leaves no durable `--data-out`.

ADR-0008's headline abort coverage, one synthesized case per failure class, all asserting the same
two-part contract through `main(argv)`: a non-zero exit **and** no `--data-out` on disk. A hard
error is not a partial build — a Dataset Version always stands for the whole intended input, so a
run that cannot honor that must commit nothing at all (ADR-0003/0005/0007). And because the abort
must be legible, a second pass asserts each case names its own cause on stderr.

Each case starts from one valid baseline — the committed reference `--data-in` — and breaks it a
single way, so the table reads as "the same good input, made bad." The classes are the ones ADR-0008
enumerates: an undecodable Original, a zero-frame WAV, a malformed `recordings.csv`, a `path` that
escapes `--data-in` (absolute and `..`-traversal, the two mechanisms ADR-0006 names), and an illegal
split ratio (both a wrong sum and a non-positive ratio, the two ADR-0004 rejects).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from sdw.cli import main
from tests import synth

# A break mutates the baseline `--data-in` in place and returns any extra argv it needs (only the
# config-driven ratio cases use it); everything else returns no extra flags.
Break = Callable[[Path], list[str]]

# One listed Original in the reference tree, overwritten to trigger the decode-gate cases.
_LISTED_WAV = "passthrough_16k_mono.wav"


class AbortCase(NamedTuple):
    """A way to break the baseline input, paired with a fragment of the abort it must produce.

    ``error_fragment`` is a short, stable slice of the `HardError` message the break provokes — a
    named cause an operator can act on, not a bare non-zero exit (see `sdw.ingest`/`sdw.normalize`/
    `sdw.config` for the full text).
    """

    break_input: Break
    error_fragment: str


def _undecodable(data_in: Path) -> list[str]:
    synth.write_non_wav(data_in / _LISTED_WAV)
    return []


def _zero_frame(data_in: Path) -> list[str]:
    synth.write_zero_frame_wav(data_in / _LISTED_WAV)
    return []


def _malformed_csv(data_in: Path) -> list[str]:
    # A header missing the required metadata columns: `recordings.csv` is rejected before any audio
    # is read (#24, ADR-0006). Written inline like `test_ingest.py`'s CSV cases — synth owns audio
    # fixtures, not the degenerate text of a broken manifest.
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


def _ratio_sum_is_wrong(data_in: Path) -> list[str]:
    # Ratios that do not sum to 1.0 are a structural config error caught in preflight (ADR-0004),
    # not a soft flag — a case carried by `--config` rather than a broken input.
    config = data_in / "sum.toml"
    config.write_text("[split]\ntrain = 0.5\nval = 0.1\ntest = 0.1\n", encoding="utf-8")
    return ["--config", str(config)]


def _ratio_is_not_positive(data_in: Path) -> list[str]:
    # A zero (or negative) ratio is the *other* ADR-0004 rejection — there is no two-way / test = 0
    # mode — and a distinct code path from the wrong-sum case, so it earns its own row.
    config = data_in / "zero.toml"
    config.write_text("[split]\ntrain = 0.0\nval = 0.5\ntest = 0.5\n", encoding="utf-8")
    return ["--config", str(config)]


ABORT_CASES = [
    pytest.param(AbortCase(_undecodable, "cannot decode Original as WAV"), id="non-wav"),
    pytest.param(AbortCase(_zero_frame, "zero frames"), id="zero-frame-wav"),
    pytest.param(AbortCase(_malformed_csv, "missing column"), id="malformed-csv"),
    pytest.param(
        AbortCase(_path_is_absolute, "must be relative, not absolute"), id="path-absolute"
    ),
    pytest.param(
        AbortCase(_path_traverses_out_of_data_in, "escapes --data-in"), id="path-traverses"
    ),
    pytest.param(AbortCase(_ratio_sum_is_wrong, "must sum to 1.0"), id="ratio-wrong-sum"),
    pytest.param(AbortCase(_ratio_is_not_positive, "must be > 0"), id="ratio-not-positive"),
]


@pytest.mark.parametrize("case", ABORT_CASES)
def test_build_aborts_with_no_durable_data_out(tmp_path: Path, case: AbortCase) -> None:
    data_in = tmp_path / "in"
    synth.write_reference_tree(data_in)
    extra = case.break_input(data_in)
    data_out = tmp_path / "out"

    exit_code = main(["build", "--data-in", str(data_in), "--data-out", str(data_out), *extra])

    assert exit_code != 0
    assert not data_out.exists()
    # Not even a staging sibling survives: the abort is invisible on disk (ADR-0003).
    assert not (tmp_path / "out.tmp").exists()


@pytest.mark.parametrize("case", ABORT_CASES)
def test_the_abort_names_its_cause_on_stderr(
    tmp_path: Path, case: AbortCase, capsys: pytest.CaptureFixture[str]
) -> None:
    # The abort is legible, not a bare non-zero: `cli.main` prints `error: <cause>` to stderr for
    # every HardError, so an operator sees *why* the build refused — the case's own message, not
    # just some message (cli.py).
    data_in = tmp_path / "in"
    synth.write_reference_tree(data_in)
    extra = case.break_input(data_in)

    exit_code = main(
        ["build", "--data-in", str(data_in), "--data-out", str(tmp_path / "out"), *extra]
    )

    assert exit_code != 0
    assert case.error_fragment in capsys.readouterr().err
