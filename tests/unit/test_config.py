"""Config loading, ratio validation, and the effective-config seam (#23).

The module owns three jobs the spec keeps deliberately close together:

- **Materialize** the effective config — tool-baked defaults for every knob, an optional
  ``--config`` TOML override, exactly the three sections ADR-0006/0007/0004 own.
- **Validate** the split ratios here, not in the splitter, so ``validate`` (which stops at
  ADR-0007's stage) can still catch an illegal ratio and keep the preflight guarantee honest
  (the issue's central point).
- **Serialize once** to canonical JSON, so the ``dataset_version`` preimage (ADR-0010) and
  ``dataset.json``'s ``config`` block consume byte-identical bytes and cannot drift.
"""

import json
from pathlib import Path

import pytest

from sdw.config import load_config, render_jsonl
from sdw.errors import HardError


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


class TestDefaults:
    """Every knob resolves to its tool-baked default when nothing overrides it."""

    def test_no_config_path_is_all_defaults(self) -> None:
        config = load_config(None)
        assert config.quality.silence_threshold_dbfs == -40.0
        assert config.quality.low_volume_rms_dbfs == -30.0
        assert config.quality.duration_min_s == 0.5
        assert config.quality.duration_max_s == 20.0
        assert config.split.seed == 0
        assert config.split.train == 0.8
        assert config.split.val == 0.1
        assert config.split.test == 0.1

    def test_empty_config_file_is_all_defaults(self, tmp_path: Path) -> None:
        assert load_config(_write(tmp_path, "")) == load_config(None)

    def test_lang_defaults_to_none(self) -> None:
        assert load_config(None).manifest.lang is None

    def test_partial_override_keeps_other_defaults(self, tmp_path: Path) -> None:
        config = load_config(_write(tmp_path, "[quality]\nduration_max_s = 30.0\n"))
        assert config.quality.duration_max_s == 30.0
        assert config.quality.duration_min_s == 0.5  # untouched
        assert config.split.train == 0.8  # untouched


class TestManifestLang:
    def test_valid_iso_639_1_is_kept(self, tmp_path: Path) -> None:
        assert load_config(_write(tmp_path, '[manifest]\nlang = "en"\n')).manifest.lang == "en"

    @pytest.mark.parametrize("bad", ["english", "EN", "e", "e1", "eng", ""])
    def test_malformed_lang_is_a_hard_error(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(HardError):
            load_config(_write(tmp_path, f'[manifest]\nlang = "{bad}"\n'))

    def test_non_string_lang_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[manifest]\nlang = 5\n"))


class TestSectionAllowlist:
    def test_the_three_sections_are_accepted(self, tmp_path: Path) -> None:
        body = '[manifest]\nlang = "en"\n[quality]\nduration_min_s = 0.6\n[split]\nseed = 3\n'
        config = load_config(_write(tmp_path, body))
        assert (config.manifest.lang, config.quality.duration_min_s, config.split.seed) == (
            "en",
            0.6,
            3,
        )

    def test_unknown_section_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError, match="frobnicate"):
            load_config(_write(tmp_path, "[frobnicate]\nx = 1\n"))

    def test_normalize_section_is_a_hard_error(self, tmp_path: Path) -> None:
        # ADR-0005/0011: a [normalize] key would fold into the preimage and mint new identities.
        with pytest.raises(HardError, match="normalize"):
            load_config(_write(tmp_path, "[normalize]\nsample_rate = 16000\n"))

    def test_images_section_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError, match="images"):
            load_config(_write(tmp_path, "[images]\ndpi = 100\n"))

    def test_unknown_key_in_a_valid_section_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError, match="bogus"):
            load_config(_write(tmp_path, "[quality]\nbogus = 1\n"))

    def test_top_level_key_outside_any_section_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError):
            load_config(_write(tmp_path, 'lang = "en"\n'))

    def test_section_declared_as_a_scalar_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError, match="table"):
            load_config(_write(tmp_path, "manifest = 5\n"))

    def test_malformed_toml_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError, match="TOML"):
            load_config(_write(tmp_path, "[quality\nnot = valid = toml\n"))


class TestRatioValidation:
    """Each ratio > 0 and the three sum to 1.0 within a small tolerance — else abort."""

    def test_defaults_are_valid(self) -> None:
        load_config(None)  # 0.8 / 0.1 / 0.1 does not raise

    def test_custom_valid_ratios(self, tmp_path: Path) -> None:
        config = load_config(_write(tmp_path, "[split]\ntrain = 0.2\nval = 0.4\ntest = 0.4\n"))
        assert (config.split.train, config.split.val, config.split.test) == (0.2, 0.4, 0.4)

    def test_wrong_sum_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[split]\ntrain = 0.5\nval = 0.1\ntest = 0.1\n"))

    def test_zero_ratio_is_a_hard_error(self, tmp_path: Path) -> None:
        # No two-way / test = 0 mode in v0.1 (ADR-0004).
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[split]\ntrain = 0.9\nval = 0.1\ntest = 0.0\n"))

    def test_negative_ratio_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[split]\ntrain = 1.1\nval = 0.0\ntest = -0.1\n"))

    def test_missing_ratio_key_falls_back_and_breaks_the_sum(self, tmp_path: Path) -> None:
        # Overriding train alone leaves val/test at 0.1 each → sum 0.6 ≠ 1.0 → abort.
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[split]\ntrain = 0.4\n"))

    def test_tiny_float_error_is_within_tolerance(self, tmp_path: Path) -> None:
        # 0.3 + 0.3 + 0.4 does not sum to exactly 1.0 in binary float.
        load_config(_write(tmp_path, "[split]\ntrain = 0.3\nval = 0.3\ntest = 0.4\n"))


class TestTypeCoercion:
    def test_integer_valued_knob_coerces_to_float(self, tmp_path: Path) -> None:
        # -40 (TOML int) and -40.0 (default float) must be indistinguishable downstream.
        config = load_config(_write(tmp_path, "[quality]\nsilence_threshold_dbfs = -40\n"))
        assert config.quality.silence_threshold_dbfs == -40.0
        assert config == load_config(None)

    def test_boolean_ratio_is_a_hard_error(self, tmp_path: Path) -> None:
        # bool is an int subclass in Python; True must not sneak through as 1.0.
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[split]\ntrain = true\nval = 0.1\ntest = 0.1\n"))

    def test_non_integer_seed_is_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(HardError):
            load_config(_write(tmp_path, "[split]\nseed = 1.5\n"))


class TestCanonicalSerialization:
    def test_keys_are_sorted_and_defaults_materialized(self) -> None:
        text = load_config(None).canonical_json()
        parsed = json.loads(text)
        assert list(parsed) == ["manifest", "quality", "split"]
        assert list(parsed["quality"]) == sorted(parsed["quality"])
        assert list(parsed["split"]) == sorted(parsed["split"])
        # Every knob is present even though nothing was overridden.
        assert parsed["manifest"] == {"lang": None}
        assert parsed["split"] == {"seed": 0, "test": 0.1, "train": 0.8, "val": 0.1}
        assert parsed["quality"] == {
            "duration_max_s": 20.0,
            "duration_min_s": 0.5,
            "low_volume_rms_dbfs": -30.0,
            "silence_threshold_dbfs": -40.0,
        }

    def test_serialization_is_stable(self) -> None:
        assert load_config(None).canonical_json() == load_config(None).canonical_json()

    def test_canonical_dict_matches_canonical_json(self) -> None:
        config = load_config(None)
        assert json.loads(config.canonical_json()) == config.canonical_dict()

    def test_embedded_subtree_reproduces_the_canonical_bytes(self) -> None:
        # dataset.json embeds canonical_dict() and re-serializes the whole document; that subtree
        # must come out byte-identical to what the dataset_version preimage hashed, so the two
        # records cannot drift. Iteration order of canonical_dict() must therefore be the sorted
        # order canonical_json() emits — asdict()'s field order would not reproduce it.
        config = load_config(None)
        reserialized = json.dumps(
            config.canonical_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        assert reserialized == config.canonical_json()
        assert list(config.canonical_dict()["split"]) == ["seed", "test", "train", "val"]

    def test_json_uses_no_ascii_escaping(self, tmp_path: Path) -> None:
        # UTF-8, not \uXXXX — a two-letter ASCII code can't prove it, so exercise the path
        # through a lang that round-trips as-is.
        text = load_config(_write(tmp_path, '[manifest]\nlang = "zh"\n')).canonical_json()
        assert '"lang":"zh"' in text


class TestDriftFreedom:
    """The seam's whole point: two spellings of the same build hash identically."""

    def test_omitting_quality_equals_writing_its_defaults(self, tmp_path: Path) -> None:
        explicit = (
            "[quality]\n"
            "silence_threshold_dbfs = -40.0\n"
            "low_volume_rms_dbfs = -30.0\n"
            "duration_min_s = 0.5\n"
            "duration_max_s = 20.0\n"
        )
        assert (
            load_config(_write(tmp_path, explicit)).canonical_json()
            == load_config(None).canonical_json()
        )

    def test_a_changed_knob_changes_the_bytes(self, tmp_path: Path) -> None:
        changed = load_config(_write(tmp_path, "[quality]\nduration_max_s = 30.0\n"))
        assert changed.canonical_json() != load_config(None).canonical_json()


class TestRenderJsonl:
    """The one JSONL join every artifact writer goes through (#54).

    These are the byte-format promises the Manifest and the quality report both inherit, so they
    are asserted once here rather than re-asserted per writer. The point of the shared join is
    that a writer cannot hold an opinion about any of them.
    """

    def test_separators_are_compact(self) -> None:
        text = render_jsonl([{"a": 1, "b": "x"}])
        assert text == '{"a":1,"b":"x"}\n'

    def test_non_ascii_is_emitted_as_utf_8_not_escaped(self) -> None:
        # The deliberate choice, and the one the two writers previously disagreed about: `text`
        # carries Prompt text verbatim, so escaping would make a non-Latin Manifest unreadable.
        assert render_jsonl([{"text": "Café ☕"}]) == '{"text":"Café ☕"}\n'

    def test_key_order_is_the_callers_not_sorted(self) -> None:
        # ADR-0006's Manifest order and ADR-0007's quality order are both non-alphabetical, so
        # `sort_keys` must stay off here even though the config's own preimage sorts.
        assert render_jsonl([{"b": 1, "a": 2}]) == '{"b":1,"a":2}\n'

    def test_every_line_is_lf_terminated(self) -> None:
        text = render_jsonl([{"a": 1}, {"a": 2}])
        assert text == '{"a":1}\n{"a":2}\n'
        assert "\r" not in text

    def test_nothing_renders_an_empty_file_not_a_lone_newline(self) -> None:
        assert render_jsonl([]) == ""


def test_config_is_frozen() -> None:
    config = load_config(None)
    with pytest.raises((AttributeError, TypeError)):
        config.split.train = 0.5  # type: ignore[misc]
