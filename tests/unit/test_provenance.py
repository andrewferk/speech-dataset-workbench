"""`dataset_version` and the `dataset.json` descriptor (#29, ADR-0010).

The preimage is asserted against bytes assembled by hand rather than against a golden digest: a
golden would pin the *answer* while leaving the *recipe* unstated, so a framing bug that changed
both would still pass. Recomputing the sequence here is the same fifteen-line recipe ADR-0010
documents for an auditor, so the test is the audit.
"""

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from sdw import __version__
from sdw.config import Config, load_config
from sdw.manifest import Dataset, build_dataset
from sdw.normalize import TARGET_SAMPLE_RATE
from sdw.provenance import (
    DESCRIPTOR_NAME,
    DOMAIN_SEPARATOR,
    MANIFEST_VERSION,
    build_provenance,
    dataset_version,
)
from sdw.split import split_sessions
from tests.unit.test_manifest import _recording  # #28's Recording factory


def _files(train: str = "", val: str = "", test: str = "") -> dict[str, str]:
    return {"train.jsonl": train, "val.jsonl": val, "test.jsonl": test}


def _expected(config: Config, files: dict[str, str], tool: str = __version__) -> str:
    """The preimage, reassembled from ADR-0010's recipe."""
    preimage = b"sdw-dataset-version/1\n"
    preimage += b"tool_version\n" + tool.encode() + b"\n"
    preimage += b"config\n" + config.canonical_json().encode() + b"\n"
    for name in ("train", "val", "test"):
        raw = files[f"{name}.jsonl"].encode()
        preimage += f"{name}.jsonl {len(raw)}\n".encode() + raw
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


class TestPreimage:
    def test_matches_the_documented_recipe(self) -> None:
        config = load_config(None)
        files = _files(train='{"id":"rec_a"}\n', val='{"id":"rec_b"}\n')
        assert dataset_version(config, files) == _expected(config, files)

    def test_domain_separator_is_the_versioned_scheme(self) -> None:
        assert DOMAIN_SEPARATOR == "sdw-dataset-version/1"

    def test_is_a_full_untruncated_sha256(self) -> None:
        version = dataset_version(load_config(None), _files())
        scheme, _, digest = version.partition(":")
        assert scheme == "sha256"
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_is_stable_across_calls(self) -> None:
        config, files = load_config(None), _files(train="a\n")
        assert dataset_version(config, files) == dataset_version(config, files)


class TestFraming:
    def test_empty_splits_frame_at_length_zero_rather_than_being_omitted(self) -> None:
        # An empty val/test is ADR-0004's produce-and-flag case, not an absent input.
        config = load_config(None)
        assert dataset_version(config, _files(train="a\n")) == _expected(
            config, _files(train="a\n")
        )

    def test_moving_a_line_between_splits_changes_the_version(self) -> None:
        # The reason framing exists: `train=[a,b], val=[]` and `train=[a], val=[b]` concatenate to
        # identical bytes. Length framing is what makes them distinguishable, independently of the
        # per-line `split` field, which the hash must not depend on.
        config = load_config(None)
        together = dataset_version(config, _files(train="a\nb\n"))
        apart = dataset_version(config, _files(train="a\n", val="b\n"))
        assert together != apart

    def test_split_order_is_fixed(self) -> None:
        # Same bytes, different splits: order is train/val/test, not insertion or alphabetical.
        config = load_config(None)
        assert dataset_version(config, _files(val="a\n")) != dataset_version(
            config, _files(test="a\n")
        )


class TestSensitivity:
    """Every documented input moves the id; nothing else does."""

    def test_a_manifest_edit_changes_the_version(self) -> None:
        # The hole ADR-0010 closes: a prompt typo leaves every audio byte — and so every
        # content_hash — untouched, but the Dataset is materially different.
        config = load_config(None)
        before = dataset_version(config, _files(train='{"text":"hello"}\n'))
        after = dataset_version(config, _files(train='{"text":"helo"}\n'))
        assert before != after

    @pytest.mark.parametrize(
        "override",
        [
            "[quality]\nsilence_threshold_dbfs = -41\n",
            "[quality]\nduration_max_s = 19\n",
            "[split]\nseed = 1\n",
            '[manifest]\nlang = "en"\n',
        ],
    )
    def test_a_config_change_changes_the_version(self, tmp_path: Path, override: str) -> None:
        # Quality thresholds reach no manifest field at all; without config in the preimage a
        # threshold change would silently reuse the id.
        path = tmp_path / "sdw.toml"
        path.write_text(override, encoding="utf-8")
        files = _files(train="a\n")
        assert dataset_version(load_config(path), files) != dataset_version(
            load_config(None), files
        )

    def test_the_tool_version_changes_the_version(self) -> None:
        config, files = load_config(None), _files(train="a\n")
        assert dataset_version(config, files, tool_version="9.9.9") == _expected(
            config, files, tool="9.9.9"
        )
        assert dataset_version(config, files, tool_version="9.9.9") != dataset_version(
            config, files
        )

    def test_materialized_defaults_and_an_explicit_default_agree(self, tmp_path: Path) -> None:
        # Omitting [quality] and writing out its four defaults describe the same build.
        path = tmp_path / "sdw.toml"
        path.write_text(
            "[quality]\nsilence_threshold_dbfs = -40.0\nlow_volume_rms_dbfs = -30.0\n"
            "duration_min_s = 0.5\nduration_max_s = 20.0\n",
            encoding="utf-8",
        )
        files = _files(train="a\n")
        assert dataset_version(load_config(path), files) == dataset_version(
            load_config(None), files
        )

    def test_only_the_three_manifests_are_hashed(self) -> None:
        # The WAVs, quality.jsonl and summary.txt derive from resampled floats, which ADR-0005 says
        # are not cross-arch bit-exact; hashing them would make the id vary by machine.
        config = load_config(None)
        bare = _files(train="a\n")
        noisy = bare | {
            "audio/train/rec_a.wav": "RIFF...",
            "reports/quality.jsonl": '{"id":"rec_a"}\n',
            "reports/summary.txt": "Kept: 1\n",
            "audio/train/metadata.jsonl": '{"file_name":"rec_a.wav"}\n',
            DESCRIPTOR_NAME: "{}",
        }
        assert dataset_version(config, noisy) == dataset_version(config, bare)


class TestToolVersion:
    def test_matches_the_declared_project_version(self) -> None:
        # The tool is never installed (`package = false`), so there is no distribution metadata to
        # read; `__version__` is the source and this is what stops it drifting from pyproject.
        root = Path(__file__).resolve().parents[2]
        with (root / "pyproject.toml").open("rb") as handle:
            assert tomllib.load(handle)["project"]["version"] == __version__


def _dataset(config: Config, sizes: dict[str, int] | None = None) -> Dataset:
    """A Dataset built through the real splitter, so the descriptor sees realized assignments.

    Sizes differ per Session so a count that silently came from the wrong Session is visible.
    """
    recordings = [
        _recording(session_id, index)
        for session_id, count in (sizes or {"sess_01": 3, "sess_02": 2, "sess_03": 1}).items()
        for index in range(count)
    ]
    result = split_sessions(recordings, config.split)
    durations = {r.recording_id: 1.0 for r in recordings}
    return build_dataset(recordings, result, durations, config)


def _text(config: Config) -> str:
    return build_provenance(config, _dataset(config)).files[DESCRIPTOR_NAME]


def _descriptor(config: Config | None = None) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(_text(config or load_config(None)))
    return parsed


class TestDescriptor:
    def test_carries_every_preimage_input(self) -> None:
        doc = _descriptor()
        assert doc["manifest_version"] == MANIFEST_VERSION == "0.1"
        assert doc["tool_version"] == __version__
        assert doc["dataset_version"].startswith("sha256:")
        assert doc["config"] == load_config(None).canonical_dict()

    def test_the_config_block_is_byte_identical_to_the_preimage_input(self) -> None:
        # The reproducibility claim: an auditor with only --data-out reads this block, reframes the
        # three manifests, and recomputes the id. Any re-serialization drift breaks that.
        config = load_config(None)
        text = build_provenance(config, _dataset(config)).files[DESCRIPTOR_NAME]
        assert f'"config":{config.canonical_json()}' in text

    def test_the_version_is_recomputable_from_data_out_alone(self) -> None:
        config = load_config(None)
        dataset = _dataset(config)
        provenance = build_provenance(config, dataset)
        doc = json.loads(provenance.files[DESCRIPTOR_NAME])

        # Nothing below reaches for --data-in or for `config`: only the emitted artifacts.
        preimage = b"sdw-dataset-version/1\n"
        preimage += b"tool_version\n" + doc["tool_version"].encode() + b"\n"
        preimage += (
            b"config\n"
            + json.dumps(
                doc["config"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        for name in ("train", "val", "test"):
            raw = dataset.files[f"{name}.jsonl"].encode()
            preimage += f"{name}.jsonl {len(raw)}\n".encode() + raw

        assert doc["dataset_version"] == "sha256:" + hashlib.sha256(preimage).hexdigest()
        assert doc["dataset_version"] == provenance.dataset_version

    def test_split_is_realized_counts_only(self) -> None:
        doc = _descriptor()
        counts = doc["split"]["counts"]
        assert list(doc["split"]) == ["counts"]
        assert list(counts) == ["train", "val", "test", "total"]
        assert counts["total"] == 6 == counts["train"] + counts["val"] + counts["test"]
        # Configured ratios and the seed are config, not output, and live only under `config`.
        assert "seed" not in doc["split"]
        assert "ratios" not in doc["split"]

    def test_there_is_no_top_level_lang(self, tmp_path: Path) -> None:
        # ADR-0010 removed it; it lives under the config block and only there.
        path = tmp_path / "sdw.toml"
        path.write_text('[manifest]\nlang = "en"\n', encoding="utf-8")
        doc = _descriptor(load_config(path))
        assert "lang" not in doc
        assert doc["config"]["manifest"]["lang"] == "en"

    def test_seed_ratios_and_lang_appear_exactly_once(self) -> None:
        # ADR-0010 rejected keeping these in two places: a reader must not have to work out which
        # copy fed the hash.
        text = _text(load_config(None))
        for key in ('"seed"', '"lang"'):
            assert text.count(key) == 1, f"{key} appears more than once"

    def test_sessions_are_an_inventory_sorted_by_session_id(self) -> None:
        sessions = _descriptor()["sessions"]
        assert [s["session_id"] for s in sessions] == ["sess_01", "sess_02", "sess_03"]
        assert [list(s) for s in sessions] == [["session_id", "split", "num_samples"]] * 3
        assert {s["session_id"]: s["num_samples"] for s in sessions} == {
            "sess_01": 3,
            "sess_02": 2,
            "sess_03": 1,
        }

    def test_each_session_reports_the_split_its_samples_landed_in(self) -> None:
        doc, dataset = _descriptor(), _dataset(load_config(None))
        expected = {s.session_id: s.split for s in dataset.samples}
        assert {s["session_id"]: s["split"] for s in doc["sessions"]} == expected

    def test_sessions_sort_by_id_not_by_split(self) -> None:
        # Reverse-named Sessions: an inventory that inherited the manifest's split grouping, or the
        # splitter's hash order, would come out in a different order than this.
        doc = json.loads(
            build_provenance(
                load_config(None),
                _dataset(load_config(None), {"sess_zz": 2, "sess_aa": 2, "sess_mm": 2}),
            ).files[DESCRIPTOR_NAME]
        )
        assert [s["session_id"] for s in doc["sessions"]] == ["sess_aa", "sess_mm", "sess_zz"]

    def test_normalization_and_hashing_are_self_description(self) -> None:
        # ADR-0010 corrects ADR-0006: these blocks describe the build, they do not feed the id.
        # Proof, not prose: the id is computed without them.
        doc = _descriptor()
        assert doc["normalization"]["sample_rate"] == TARGET_SAMPLE_RATE
        assert doc["normalization"]["num_channels"] == 1
        # The two derived values are asserted as literals: the module builds them from
        # `normalize`'s constants so they cannot drift from the tool, and these pin them to the
        # strings ADR-0010's example publishes, so the tool cannot drift from the ADR either.
        assert doc["normalization"]["encoding"] == "PCM_16"
        assert doc["normalization"]["downmix"] == "mean"
        assert doc["normalization"]["resampler"] == "soxr_hq"
        assert doc["hashing"]["algorithm"] == "sha256"
        assert "domain separator" in doc["hashing"]["dataset_version"]
        assert (
            dataset_version(load_config(None), _dataset(load_config(None)).files)
            == doc["dataset_version"]
        )

    def test_key_order_is_the_documented_order(self) -> None:
        assert list(_descriptor()) == [
            "manifest_version",
            "tool_version",
            "dataset_version",
            "config",
            "normalization",
            "hashing",
            "split",
            "sessions",
        ]

    def test_carries_no_timestamp_wall_clock_or_outside_tree_path(self) -> None:
        text = _text(load_config(None))
        assert str(Path.cwd()) not in text
        for banned in ("/Users", "/home", "generated_at", "created", "timestamp", "hostname"):
            assert banned not in text

    def test_is_deterministic(self) -> None:
        config = load_config(None)
        first = build_provenance(config, _dataset(config))
        second = build_provenance(config, _dataset(config))
        assert first.files == second.files

    def test_an_empty_split_reports_zero_rather_than_dropping_out(self) -> None:
        # One Session cannot fill three Splits (ADR-0004's produce-and-flag case). A Split missing
        # from the counts would read as "not built" rather than as "built and empty".
        config = load_config(None)
        dataset = _dataset(config, {"sess_01": 1})
        doc = json.loads(build_provenance(config, dataset).files[DESCRIPTOR_NAME])
        assert set(doc["split"]["counts"]) == {"train", "val", "test", "total"}
        assert doc["split"]["counts"]["total"] == 1
        assert sorted(doc["split"]["counts"].values()) == [0, 0, 1, 1]


class TestDescriptorIsNotHashed:
    def test_the_descriptor_is_excluded_from_its_own_preimage(self) -> None:
        # Circular by construction: it carries the id.
        config = load_config(None)
        dataset = _dataset(config)
        provenance = build_provenance(config, dataset)
        assert DESCRIPTOR_NAME not in dataset.files
        with_descriptor = dataset.files | provenance.files
        assert dataset_version(config, with_descriptor) == provenance.dataset_version
