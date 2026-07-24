"""The effective config: defaults, validation, and the one canonical serialization.

The single seam through which config reaches the rest of the tool: bake a default for every knob,
fold in an optional ``--config`` TOML override, hand back an immutable :class:`Config`. Two facts
are load-bearing. Ratio validation lives here, not in the splitter: :func:`load_config` runs on both
commands, so ``validate`` catches a bad ratio even though splitting is later — without it the
green-preflight guarantee (ADR-0007) would be false. And the config serializes exactly once, via
:meth:`Config.canonical_json`, whose bytes feed both the ``dataset_version`` preimage (ADR-0010) and
``dataset.json``'s ``config`` block, so the two cannot drift. The byte format is
:mod:`sdw.serialization`'s, imported like any other writer imports it (#54).

Three sections only — ``[manifest]`` (ADR-0006), ``[quality]`` (ADR-0007), ``[split]`` (ADR-0004).
No ``[normalize]`` or ``[images]``: either would fold into the preimage and mint new Dataset
identities for byte-identical Manifests (ADR-0005/0011).
"""

import json
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from sdw.errors import HardError
from sdw.serialization import JSON_ENSURE_ASCII, JSON_SEPARATORS

# Ratios must sum to 1.0; binary floats land 0.8 + 0.1 + 0.1 a hair off, so compare with tolerance.
RATIO_SUM_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ManifestConfig:
    """``[manifest]`` (ADR-0006). ``lang`` is an optional ISO 639-1 code; unset resolves to null."""

    lang: str | None = None


@dataclass(frozen=True)
class QualityConfig:
    """``[quality]`` (ADR-0007) — the four quality knobs; all fold into the preimage.

    Three gate a flag; ``silence_threshold_dbfs`` gates the report-only silence measurement, which
    raises none (ADR-0007).
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

        These exact bytes feed both the ``dataset_version`` preimage and ``dataset.json``
        (ADR-0010), so the identity and its record cannot disagree.
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

        Derived from :meth:`canonical_json`, not the dataclass, so re-serializing it with
        ``sort_keys`` reproduces the preimage's ``config`` bytes exactly — the two cannot drift.
        """
        result: dict[str, Any] = json.loads(self.canonical_json())
        return result


# Each section's keys, from the dataclass fields so the allowlist can't drift from the knobs.
# An unknown key or section aborts loudly rather than being silently absent from the preimage.
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
    # Format check only: two lowercase ASCII letters, not the full 184-code registry.
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
