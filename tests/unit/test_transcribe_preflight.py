"""The transcribe preflight: everything wrong, reported at once, before anything expensive (#164).

Each case starts from one valid baseline — the committed reference `--data-in`, built for real —
and breaks it a single way, so the table reads as "the same good dataset, made bad" (ADR-0008's
shape). The last case breaks it two ways at once, because *reporting everything at once* is a
decision (ADR-0017) and a suite that only ever breaks one thing cannot tell it from first-contact
abort.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sdw.cli import main
from sdw.errors import HardError
from sdw.transcribe.dataset import DESCRIPTOR_NAME
from sdw.transcribe.preflight import preflight
from tests import synth


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The reference `--data-in` built once for the module; every test copies before breaking it."""
    root = tmp_path_factory.mktemp("reference")
    data_in = root / "in"
    synth.write_reference_tree(data_in)
    data_out = root / "dataset"
    assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) == 0
    return data_out


@pytest.fixture
def dataset(built: Path, tmp_path: Path) -> Path:
    """A private copy of the built Dataset Version, safe to break."""
    copy = tmp_path / "dataset"
    shutil.copytree(built, copy)
    return copy


def _preflight(dataset: Path, tmp_path: Path) -> str:
    """Run the preflight against a free Run name and return the message it aborted with."""
    with pytest.raises(HardError) as raised:
        preflight(root=dataset, run_dir=tmp_path / "eval" / "run-20260803T142205Z")
    return str(raised.value)


class TestGreen:
    """What a green preflight promises: the whole Dataset Version, read and decodable."""

    def test_it_returns_every_sample_in_id_order(self, dataset: Path, tmp_path: Path) -> None:
        version = preflight(root=dataset, run_dir=tmp_path / "eval" / "run-20260803T142205Z")
        ids = [sample.id for sample in version.samples]
        assert ids == sorted(ids)
        assert len(ids) == 4
        assert {sample.split for sample in version.samples} == {"train", "val", "test"}

    def test_it_reads_the_descriptor_the_run_will_quote(
        self, dataset: Path, tmp_path: Path
    ) -> None:
        version = preflight(root=dataset, run_dir=tmp_path / "eval" / "run-20260803T142205Z")
        assert version.descriptor.dataset_version.startswith("sha256:")
        assert version.descriptor.manifest_version == "0.1"
        # v0.1 declares no language; ADR-0016's default is applied at the Run, not invented here.
        assert version.descriptor.lang is None


class TestAborts:
    """One break per class, each naming its own cause (ADR-0017's preflight list)."""

    def test_not_a_dataset_version(self, dataset: Path, tmp_path: Path) -> None:
        (dataset / DESCRIPTOR_NAME).unlink()
        assert "--dataset is not a Dataset Version" in _preflight(dataset, tmp_path)

    def test_an_unparseable_descriptor(self, dataset: Path, tmp_path: Path) -> None:
        (dataset / DESCRIPTOR_NAME).write_text("{not json", encoding="utf-8")
        assert "dataset.json will not parse" in _preflight(dataset, tmp_path)

    def test_an_unparseable_manifest(self, dataset: Path, tmp_path: Path) -> None:
        (dataset / "train.jsonl").write_text('{"id":"rec_a"}\n{oops\n', encoding="utf-8")
        assert "Manifest will not parse" in _preflight(dataset, tmp_path)

    def test_a_manifest_line_missing_a_field(self, dataset: Path, tmp_path: Path) -> None:
        # The stranger-consumer dogfood: a field this package needs and the Manifest stops emitting
        # is caught by the code reading it, not by a second copy of the contract (ADR-0017).
        (dataset / "train.jsonl").write_text('{"id":"rec_a","duration":1.0}\n', encoding="utf-8")
        assert "missing or non-string 'text'" in _preflight(dataset, tmp_path)

    def test_a_missing_manifest(self, dataset: Path, tmp_path: Path) -> None:
        (dataset / "val.jsonl").unlink()
        assert "Manifest is missing" in _preflight(dataset, tmp_path)

    def test_missing_audio(self, dataset: Path, tmp_path: Path) -> None:
        for wav in sorted(dataset.glob("audio/*/*.wav"))[:2]:
            wav.unlink()
        message = _preflight(dataset, tmp_path)
        # Every missing file, not the first: naming three costs the same seconds as naming one.
        assert message.count("Normalized audio is missing or will not decode") == 2

    def test_undecodable_audio(self, dataset: Path, tmp_path: Path) -> None:
        synth.write_non_wav(sorted(dataset.glob("audio/*/*.wav"))[0])
        assert "will not decode" in _preflight(dataset, tmp_path)

    def test_zero_samples(self, dataset: Path, tmp_path: Path) -> None:
        for name in ("train.jsonl", "val.jsonl", "test.jsonl"):
            (dataset / name).write_text("", encoding="utf-8")
        assert "holds zero Samples" in _preflight(dataset, tmp_path)

    def test_a_run_directory_name_collision(self, dataset: Path, tmp_path: Path) -> None:
        # A hard error, not a `-2` suffix: two directories whose names imply an ordering
        # relationship they do not have is worse than a loud refusal (ADR-0021).
        collision = tmp_path / "eval" / "run-20260803T142205Z"
        collision.mkdir(parents=True)
        with pytest.raises(HardError) as raised:
            preflight(root=dataset, run_dir=collision)
        assert "the Run directory already exists" in str(raised.value)


class TestReportsEverythingAtOnce:
    """Two independent breaks, one abort, both named — the decision, not an incidental."""

    def test_both_problems_are_named(self, dataset: Path, tmp_path: Path) -> None:
        (dataset / DESCRIPTOR_NAME).unlink()
        synth.write_non_wav(sorted(dataset.glob("audio/*/*.wav"))[0])
        collision = tmp_path / "eval" / "run-20260803T142205Z"
        collision.mkdir(parents=True)

        with pytest.raises(HardError) as raised:
            preflight(root=dataset, run_dir=collision)

        message = str(raised.value)
        assert "found 3 problems" in message
        assert "--dataset is not a Dataset Version" in message
        assert "will not decode" in message
        assert "the Run directory already exists" in message

    def test_nothing_is_created_by_a_failed_preflight(self, dataset: Path, tmp_path: Path) -> None:
        (dataset / DESCRIPTOR_NAME).unlink()
        _preflight(dataset, tmp_path)
        assert not (tmp_path / "eval").exists()
