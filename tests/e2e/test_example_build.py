"""ADR-0012 Check 1 — the example builds, and teaches what ADR-0009 says it teaches (#36).

ADR-0009's example exists to teach; every element of its shape is justified by a claim it
demonstrates. Those claims break **quietly** when someone edits `examples/` — the demo still
builds, and teaches the wrong thing. Nothing else catches it: ADR-0008's golden runs against
`tests/fixtures/reference/`, a *different* corpus, so it says nothing about what `examples/` shows;
ADR-0009's own drift test regenerates the WAVs and never invokes `build`.

So CI builds `examples/data-in/` and asserts each teaching claim **by name**. Not a golden: a named
assertion's failure message *is* the documentation of what broke — a failing `low_volume` assertion
says ADR-0009's quiet take stopped tripping — while a golden diff says *line 7 differs* and invites
regeneration over reading. One assertion per test, built once, so a break names the claim it broke
rather than the first line that moved.

Two deliberate omissions, each load-bearing:

- **It asserts *that* a repair fired and the resulting 6/3/3 counts — never that `sess_a1`
  specifically moved.** Which Session moves is a function of hash ordering over Session ids; pinning
  it couples the test to a naming detail with no teaching value, and the counts already prove the
  repair did its job. The README may name `sess_a1` in prose.
- **It never asserts `dataset_version`.** The preimage includes `tool_version` (ADR-0010), so every
  version bump would break this for reasons unrelated to the example — churn that trains people to
  update goldens without reading them. The exact id is ADR-0008's golden's job, over its own tree.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sdw.cli import main

REPO_ROOT = Path(__file__).parents[2]
EXAMPLE_DATA_IN = REPO_ROOT / "examples" / "data-in"

# The three Manifests, in the order ADR-0004 fixes. Named once so the readers below don't each spell
# the tuple inline.
SPLIT_NAMES = ("train", "val", "test")

# ADR-0009's shape: 12 Recordings across 4 Sessions, realized as a 6/3/3 split (ADR-0004's worked
# example, as amended by #19). Named here so the numbers a break reports read against the claim.
EXPECTED_TOTAL = 12
EXPECTED_COUNTS = {"train": 6, "val": 3, "test": 3}
# 2 PNGs per Recording — a waveform and a spectrogram (ADR-0011: `images/` is a 1:1 mirror, 2×N).
EXPECTED_PNG_COUNT = 2 * EXPECTED_TOTAL

# The produce-and-flag warning (ADR-0004): the unmissable signal that a Dataset is too small to
# partition, so val/test are empty. The example has 4 Sessions precisely so it never appears; if it
# does, the example has stopped being the "a build that worked" object ADR-0009 designed.
PRODUCE_AND_FLAG_MARKER = "empty by arithmetic"


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, Path]:
    """Build the committed `examples/data-in/` once; return the exit code and the `--data-out`.

    The exit code is *returned*, not asserted here, so the named `test_build_exits_zero` owns that
    claim rather than a fixture failing before any test runs. Every other assertion reads the tree.
    """
    out = tmp_path_factory.mktemp("example-out")
    code = main(["build", "--data-in", str(EXAMPLE_DATA_IN), "--data-out", str(out)])
    return code, out


@pytest.fixture(scope="module")
def data_out(build: tuple[int, Path]) -> Path:
    """The `--data-out` of the single example build (see :func:`build`)."""
    return build[1]


def _summary(data_out: Path) -> str:
    return (data_out / "reports" / "summary.txt").read_text(encoding="utf-8")


def _jsonl_records(path: Path) -> Iterator[dict[str, object]]:
    """Each line of a JSONL file, parsed. The one place the read-and-decode shape is spelled."""
    for line in path.read_text(encoding="utf-8").splitlines():
        yield json.loads(line)


def _manifest_ids(data_out: Path) -> set[str]:
    return {
        str(record["id"])
        for split in SPLIT_NAMES
        for record in _jsonl_records(data_out / f"{split}.jsonl")
    }


def _counts(data_out: Path) -> dict[str, int]:
    return {
        split: sum(1 for _ in _jsonl_records(data_out / f"{split}.jsonl")) for split in SPLIT_NAMES
    }


def _low_volume_ids(data_out: Path) -> set[str]:
    ids: set[str] = set()
    for record in _jsonl_records(data_out / "reports" / "quality.jsonl"):
        flags = record["flags"]
        assert isinstance(flags, list)
        if "low_volume" in flags:
            ids.add(str(record["id"]))
    return ids


class TestExampleBuild:
    """Each of ADR-0009's teaching claims, asserted by name against one build of `examples/`."""

    def test_build_exits_zero(self, build: tuple[int, Path]) -> None:
        # The claim the name makes: `build` returns 0. A green build is the precondition the rest of
        # this class reads, so a total failure to build gets its own named line in the report.
        code, _ = build
        assert code == 0

    def test_no_produce_and_flag_warning(self, data_out: Path) -> None:
        # ADR-0009 chose 4 Sessions so the first run clears ADR-0004's ≥3-Session floor. If this
        # trips, the example has become the "unusable, splits empty" object it must never be.
        assert PRODUCE_AND_FLAG_MARKER not in _summary(data_out)

    def test_twelve_samples_total(self, data_out: Path) -> None:
        assert len(_manifest_ids(data_out)) == EXPECTED_TOTAL

    def test_realized_split_is_six_three_three(self, data_out: Path) -> None:
        # The counts — not which Session moved. The 6/3/3 is what proves the repair placed whole,
        # indivisible Sessions into every bucket; the identity of the mover carries no lesson.
        assert _counts(data_out) == EXPECTED_COUNTS

    def test_all_three_splits_non_empty(self, data_out: Path) -> None:
        # The promise the tool actually keeps (ADR-0004): ratios are best-effort, non-emptiness is
        # not. A stronger, separate claim than the exact counts above.
        assert all(count > 0 for count in _counts(data_out).values())

    def test_twenty_four_pngs(self, data_out: Path) -> None:
        # ADR-0011: `images/` is a 1:1 mirror of the manifest, two views per Recording.
        assert len(list((data_out / "images").glob("*.png"))) == EXPECTED_PNG_COUNT

    def test_exactly_one_low_volume_flag_present_in_a_manifest(self, data_out: Path) -> None:
        # ADR-0009's deliberate quiet take: one Recording at −36 dBFS, below the −30 dBFS knob.
        # ADR-0007's "included and flagged": the flagged Sample is still a line in some Manifest.
        low_volume = _low_volume_ids(data_out)
        assert len(low_volume) == 1
        assert low_volume <= _manifest_ids(data_out)

    def test_a_repair_line_appears(self, data_out: Path) -> None:
        # ADR-0004's non-emptiness repair fired — *that* it fired, by its report line, not which
        # Session it moved. The 6/3/3 counts above are the check that it did its job.
        assert "non-emptiness repair: moved session" in _summary(data_out)

    def test_speaker_overlap_note_appears(self, data_out: Path) -> None:
        # ADR-0004: disjointness is Session-level, not Speaker-level. Two Speakers across 4 Sessions
        # makes overlap unavoidable, which is why ADR-0009 has two speakers.
        assert "not speaker-independent" in _summary(data_out)
