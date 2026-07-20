"""The reference-tree golden and byte-identity contract — ADR-0008's headline e2e (#33).

ADR-0008 splits the reproducibility contract by testability, and this module holds both halves
against the single committed reference `--data-in` (`tests/fixtures/reference/`):

- **Golden-file exact equality** for the cross-machine-stable artifacts — the three Manifests,
  `dataset.json`, `quality.jsonl`, `summary.txt`, and the exact `dataset_version` string. These are
  Original-derived, structural, and config-derived (even a Manifest `duration` is `num_frames /
  16000`), so they carry no soxr ULP and no matplotlib byte; committing them pins the output format
  and doubles as readable documentation of it.
- **Build-twice-and-diff** for byte-identity of the *whole* `--data-out` — the Normalized WAVs and
  the PNGs included. Those are not cross-arch bit-exact (soxr FFT ULPs, ADR-0005) and matplotlib
  PNGs are not naturally byte-stable, so nothing binary is committed; instead two builds of one
  input into two dirs must agree to the byte. A diff there is a real determinism bug, not an
  exemption.

Idempotence ("re-running an identical build is safe") and determinism ("two builds are
byte-identical") are asserted as two separate tests below — both are claimed by ADR-0008 and they
are different properties.

Regenerate the committed goldens after an *intended* output-format change with::

    UPDATE_GOLDEN=1 pytest tests/e2e/test_reference_golden.py

which rewrites `tests/fixtures/reference/golden/` from a fresh build before asserting, so the diff
in that directory becomes a reviewable record of the format change.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from sdw.cli import main
from tests import synth

REPO_ROOT = Path(__file__).parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "reference" / "golden"

# The cross-machine-stable artifacts (ADR-0008): the only outputs safe to pin as committed bytes.
STABLE_ARTIFACTS = (
    "train.jsonl",
    "val.jsonl",
    "test.jsonl",
    "dataset.json",
    "reports/quality.jsonl",
    "reports/summary.txt",
)

# The reference tree is four Recordings across four Sessions (ADR-0008), so the build emits two
# PNGs — a waveform and a spectrogram — for each.
REFERENCE_RECORDING_COUNT = 4
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _build_reference(root: Path) -> Path:
    """Build the committed reference `--data-in` into ``root`` and return the `--data-out`.

    The input is written by the same `synth.write_reference_tree` that produced the committed
    `tests/fixtures/reference/` WAVs, so a golden mismatch is a change in the *pipeline*, never in
    the fixture.
    """
    data_in = root / "in"
    synth.write_reference_tree(data_in)
    data_out = root / "out"
    assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) == 0
    return data_out


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` as relative-POSIX-path → raw bytes, for whole-tree comparison."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rewrite_golden(data_out: Path) -> None:
    """Overwrite the committed goldens from a fresh build (the ``UPDATE_GOLDEN`` escape hatch)."""
    for name in STABLE_ARTIFACTS:
        target = GOLDEN_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(data_out / name, target)
    version = json.loads((data_out / "dataset.json").read_text(encoding="utf-8"))["dataset_version"]
    (GOLDEN_DIR / "dataset_version").write_text(version + "\n", encoding="utf-8")


class TestGolden:
    """The stable artifacts match their committed goldens, byte for byte."""

    def test_stable_artifacts_match_the_reference_golden(self, tmp_path: Path) -> None:
        data_out = _build_reference(tmp_path)
        if os.environ.get("UPDATE_GOLDEN"):
            _rewrite_golden(data_out)
        for name in STABLE_ARTIFACTS:
            assert (data_out / name).read_bytes() == (GOLDEN_DIR / name).read_bytes(), name

    def test_dataset_version_is_the_committed_string(self, tmp_path: Path) -> None:
        # The exact `dataset_version` string is its own committed golden (ADR-0010): a hash over the
        # three Manifests + config + tool version, so pinning it guards the whole preimage at once.
        data_out = _build_reference(tmp_path)
        if os.environ.get("UPDATE_GOLDEN"):
            _rewrite_golden(data_out)
        built = json.loads((data_out / "dataset.json").read_text(encoding="utf-8"))[
            "dataset_version"
        ]
        committed = (GOLDEN_DIR / "dataset_version").read_text(encoding="utf-8").strip()
        assert built == committed


class TestByteIdentity:
    """The whole `--data-out` — WAVs and PNGs included — is byte-identical across builds (#8)."""

    def test_two_builds_into_two_dirs_are_byte_identical(self, tmp_path: Path) -> None:
        # Determinism: the same input+config into two fresh `--data-out` must agree to the byte —
        # the binary half of the contract that no committed golden can hold cross-arch.
        source = tmp_path / "in"
        synth.write_reference_tree(source)
        assert main(["build", "--data-in", str(source), "--data-out", str(tmp_path / "a")]) == 0
        assert main(["build", "--data-in", str(source), "--data-out", str(tmp_path / "b")]) == 0
        assert _tree_bytes(tmp_path / "a") == _tree_bytes(tmp_path / "b")

    def test_rebuilding_over_a_prior_build_is_byte_identical(self, tmp_path: Path) -> None:
        # Idempotence: re-running onto a live `--data-out` is a byte-identical rewrite, not an error
        # and not a drift — the property that makes a rebuild safe to run at any time.
        source = tmp_path / "in"
        synth.write_reference_tree(source)
        data_out = tmp_path / "out"
        assert main(["build", "--data-in", str(source), "--data-out", str(data_out)]) == 0
        first = _tree_bytes(data_out)
        assert main(["build", "--data-in", str(source), "--data-out", str(data_out)]) == 0
        assert _tree_bytes(data_out) == first


class TestImages:
    """The PNGs are smoke-checked: valid PNGs, two per Recording (ADR-0008 defers pixel goldens)."""

    def test_images_are_valid_pngs_of_the_expected_count(self, tmp_path: Path) -> None:
        data_out = _build_reference(tmp_path)
        pngs = sorted((data_out / "images").glob("*.png"))
        assert len(pngs) == 2 * REFERENCE_RECORDING_COUNT
        for png in pngs:
            assert png.read_bytes().startswith(PNG_MAGIC), png.name
        # Both views for every Recording, named off the Sample id — the join back to the Manifest.
        stems = {png.name.rsplit(".", 2)[0] for png in pngs}
        for stem in stems:
            assert (data_out / "images" / f"{stem}.waveform.png") in pngs
            assert (data_out / "images" / f"{stem}.spectrogram.png") in pngs
