"""The effective config: defaults, validation, and the one canonical serialization.

This module is the single seam through which config reaches the rest of the tool. It bakes a
default for every knob, folds in an optional ``--config`` TOML override, and hands back an
immutable :class:`Config`. Two facts about it are load-bearing:

- **Ratio validation lives here, not in the splitter.** ADR-0007 stops ``validate`` at the
  quality stage, while splitting is later; if an illegal ratio were only caught in the splitter,
  ``validate`` could never catch it and the spec's guarantee — a green preflight means ``build``
  will not hard-error — would be false. So :func:`load_config` runs on both commands and rejects
  a bad ratio up front.
- **The config serializes exactly once**, via :meth:`Config.canonical_json`. Those bytes feed
  both the ``dataset_version`` preimage (ADR-0010) and ``dataset.json``'s ``config`` block, so
  the two cannot drift. :meth:`Config.canonical_dict` exposes the same structure for a consumer
  that embeds it in a larger document, serialized with :data:`JSON_SEPARATORS` +
  ``sort_keys`` so the embedded subtree stays byte-identical to the standalone form.

It is also where the tool's canonical JSON *byte format* is stated, for every artifact and not
just for the config. That format had to be decided here first — the preimage needs it — and every
other JSON writer in the tool must make the identical choice, because ADR-0008 compares artifacts
as exact goldens. Stating it once and importing it is what makes "the Manifest and the quality
report agree" a property of the code rather than of three modules holding matching literals (#54).

Three sections only — ``[manifest]`` (ADR-0006), ``[quality]`` (ADR-0007), ``[split]``
(ADR-0004). There is deliberately no ``[normalize]`` and no ``[images]`` (ADR-0005/0011): either
would fold into the preimage and mint new Dataset identities for byte-identical Manifests.
"""

import json
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from sdw.errors import HardError

# Ratios must sum to 1.0; binary floats make 0.8 + 0.1 + 0.1 land a hair off, so compare with a
# small absolute tolerance rather than for exact equality.
RATIO_SUM_TOLERANCE = 1e-9

# The canonical JSON byte format, for every artifact the tool writes (#54).
#
# `json.dumps` defaults to `", "` and `": "`; every artifact here is compact. The byte format is
# load-bearing rather than cosmetic — the files are compared as exact goldens (ADR-0008) and the
# Manifest bytes are what `dataset_version` hashes (ADR-0010).
JSON_SEPARATORS = (",", ":")

# UTF-8 throughout, so a non-ASCII character is emitted as itself rather than as a `\uXXXX` escape.
# The choice is deliberate and it is the *text* that forces it: `text` carries Prompt text verbatim
# (ADR-0006), so escaping would make a Manifest of accented or non-Latin prompts unreadable to the
# operator who has to check it, and would inflate the bytes a consumer decodes for no gain. Every
# file is written as UTF-8 already, so there is nothing an escape would protect against. No v0.1
# artifact contains a non-ASCII character today — every field is either hash-derived or drawn from
# a fixed ASCII vocabulary — which is why unifying on this value changes no emitted byte.
JSON_ENSURE_ASCII = False


def render_jsonl(lines: Iterable[Mapping[str, Any]]) -> str:
    """Objects as JSON Lines: one compact object per line, LF-terminated, no trailing whitespace.

    The one JSONL writer, used by the Manifest, the HF view, and the quality report alike (#54).
    A shared pair of constants would still let a writer import them and forget to pass one; a
    shared join makes the byte format something a writer cannot express an opinion about.

    Every line is terminated, so an empty sequence yields an empty file rather than a lone newline,
    and appending one is always a whole-line change. Key order is the caller's insertion order —
    ``sort_keys`` is deliberately off, because both ADR-0006's Manifest and ADR-0007's quality line
    fix an order that is not alphabetical. The config's own preimage is the one JSON in the tool
    that *is* key-sorted, and it is a single object rather than a line-per-record file, so it
    serializes through :meth:`Config.canonical_json` instead of through here.
    """
    return "".join(
        json.dumps(line, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"
        for line in lines
    )


@dataclass(frozen=True)
class ManifestConfig:
    """``[manifest]`` (ADR-0006). ``lang`` is an optional ISO 639-1 code; unset resolves to null."""

    lang: str | None = None


@dataclass(frozen=True)
class QualityConfig:
    """``[quality]`` (ADR-0007) — the four quality knobs; all fold into the preimage.

    Three of the four gate an advisory flag (``low_volume``, and duration min/max →
    ``duration_out_of_range``); ``silence_threshold_dbfs`` gates the silence *measurement*, which
    is report-only and raises no flag. The v0.1 flag vocabulary is exactly three (ADR-0007).
    """

    silence_threshold_dbfs: float = -40.0
    low_volume_rms_dbfs: float = -30.0
    duration_min_s: float = 0.5
    duration_max_s: float = 20.0


@dataclass(frozen=True)
class SplitConfig:
    """``[split]`` (ADR-0004). ``group_by`` is fixed to Session in v0.1 and is not a knob."""

    seed: int = 0
    train: float = 0.8
    val: float = 0.1
    test: float = 0.1


@dataclass(frozen=True)
class Config:
    """The fully-materialized effective config: every knob resolved, nothing left implicit."""

    manifest: ManifestConfig
    quality: QualityConfig
    split: SplitConfig

    def canonical_json(self) -> str:
        """The one canonical serialization: keys sorted, defaults materialized, UTF-8, compact.

        These exact bytes are what the ``dataset_version`` preimage hashes and what
        ``dataset.json`` records, so the identity and its record cannot disagree.
        """
        return json.dumps(
            {
                "manifest": vars(self.manifest),
                "quality": vars(self.quality),
                "split": vars(self.split),
            },
            sort_keys=True,
            ensure_ascii=JSON_ENSURE_ASCII,
            separators=JSON_SEPARATORS,
        )

    def canonical_dict(self) -> dict[str, Any]:
        """The config as a nested dict for embedding in ``dataset.json``'s ``config`` block.

        Derived from :meth:`canonical_json` rather than from the dataclass directly, so its keys
        iterate in the same sorted order as the canonical bytes. Serializing this dict with
        :data:`JSON_SEPARATORS` + ``sort_keys`` therefore reproduces the preimage's
        ``config`` bytes exactly — the two records cannot drift.
        """
        result: dict[str, Any] = json.loads(self.canonical_json())
        return result


# Which keys each section owns, derived straight from the dataclass fields so the allowlist can
# never drift from the knobs themselves. A key outside its section's set — or a section outside
# this map — is a structural config error, so a typo or a would-be [normalize]/[images] knob
# aborts loudly rather than being silently ignored (and silently absent from the preimage).
_SECTION_KEYS: dict[str, frozenset[str]] = {
    "manifest": frozenset(f.name for f in fields(ManifestConfig)),
    "quality": frozenset(f.name for f in fields(QualityConfig)),
    "split": frozenset(f.name for f in fields(SplitConfig)),
}


def load_config(path: Path | None) -> Config:
    """Materialize the effective config from tool defaults plus an optional ``--config`` override.

    Raises :class:`HardError` on any structural config problem — an unknown section or key, a
    mistyped value, a malformed ``lang``, or an illegal split ratio — so that both ``build`` and
    ``validate`` abort before doing any work.
    """
    raw = _read_toml(path)
    _reject_unknown_sections(raw)

    manifest = _load_manifest(_section(raw, "manifest"))
    quality = _load_quality(_section(raw, "quality"))
    split = _load_split(_section(raw, "split"))

    return Config(manifest=manifest, quality=quality, split=split)


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise HardError(f"--config is not valid TOML: {error}") from error


def _reject_unknown_sections(raw: dict[str, Any]) -> None:
    for key, value in raw.items():
        if key not in _SECTION_KEYS:
            if not isinstance(value, dict):
                raise HardError(f"config key {key!r} does not belong to any section")
            raise HardError(
                f"unknown config section [{key}]; only [manifest], [quality], [split] are allowed"
            )


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    table = raw.get(name, {})
    if not isinstance(table, dict):
        raise HardError(f"config section [{name}] must be a table")
    unknown = set(table) - _SECTION_KEYS[name]
    if unknown:
        raise HardError(f"unknown key(s) in [{name}]: {', '.join(sorted(unknown))}")
    return table


def _load_manifest(table: dict[str, Any]) -> ManifestConfig:
    if "lang" not in table:
        return ManifestConfig()
    lang = table["lang"]
    if not isinstance(lang, str) or not _is_iso_639_1(lang):
        raise HardError(f"[manifest].lang must be a two-letter ISO 639-1 code, got {lang!r}")
    return ManifestConfig(lang=lang)


def _is_iso_639_1(code: str) -> bool:
    # Format check only: exactly two lowercase ASCII letters. This rejects "EN", "eng", and
    # "english" without dragging in the full 184-code registry, which v0.1 does not need.
    return len(code) == 2 and code.isascii() and code.islower() and code.isalpha()


def _load_quality(table: dict[str, Any]) -> QualityConfig:
    d = QualityConfig()
    return QualityConfig(
        silence_threshold_dbfs=_as_float(
            table, "silence_threshold_dbfs", d.silence_threshold_dbfs, "quality"
        ),
        low_volume_rms_dbfs=_as_float(
            table, "low_volume_rms_dbfs", d.low_volume_rms_dbfs, "quality"
        ),
        duration_min_s=_as_float(table, "duration_min_s", d.duration_min_s, "quality"),
        duration_max_s=_as_float(table, "duration_max_s", d.duration_max_s, "quality"),
    )


def _load_split(table: dict[str, Any]) -> SplitConfig:
    d = SplitConfig()
    seed = table.get("seed", d.seed)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise HardError(f"[split].seed must be an integer, got {seed!r}")
    split = SplitConfig(
        seed=seed,
        train=_as_float(table, "train", d.train, "split"),
        val=_as_float(table, "val", d.val, "split"),
        test=_as_float(table, "test", d.test, "split"),
    )
    _validate_ratios(split)
    return split


def _validate_ratios(split: SplitConfig) -> None:
    ratios = {"train": split.train, "val": split.val, "test": split.test}
    for name, value in ratios.items():
        if value <= 0:
            raise HardError(
                f"[split].{name} must be > 0 (no two-way / test = 0 mode in v0.1), got {value}"
            )
    total = split.train + split.val + split.test
    if abs(total - 1.0) > RATIO_SUM_TOLERANCE:
        raise HardError(
            f"[split] ratios must sum to 1.0, got train + val + test = {total} "
            f"(train={split.train}, val={split.val}, test={split.test})"
        )


def _as_float(table: dict[str, Any], key: str, default: float, section: str) -> float:
    if key not in table:
        return default
    value = table[key]
    # bool is an int subclass; a stray `true` must not read as 1.0.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HardError(f"[{section}].{key} must be a number, got {value!r}")
    return float(value)
