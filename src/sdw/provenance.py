"""`dataset_version` and the `dataset.json` descriptor (#29, ADR-0010).

The content-derived identity of a built Dataset (ADR-0001) and the record that explains it. The id
is a sha256 over ADR-0010's preimage: domain separator, tool version, canonical effective config —
so an output-affecting input that reaches no Manifest line, like ADR-0007's quality thresholds,
still moves the id — and each `<split>.jsonl` framed by name and byte length.

What the preimage deliberately **excludes** is as load-bearing as what it covers (ADR-0010):
`dataset.json` itself (circular — it carries the id), and the Normalized WAVs,
`reports/quality.jsonl` and `reports/summary.txt`, which derive from resampled floats that are not
cross-arch bit-exact (soxr FFT ULPs, ADR-0005) and would make the id vary by machine, breaking
ADR-0008's exact-`dataset_version` golden. The Manifest is safe — its `duration` is a frame count,
not a float comparison.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from sdw import __version__
from sdw.config import Config
from sdw.manifest import ENCODING, NUM_CHANNELS, Dataset, Sample
from sdw.normalize import RESAMPLE_QUALITY, TARGET_SAMPLE_RATE, TARGET_SUBTYPE
from sdw.serialization import JSON_ENSURE_ASCII, JSON_SEPARATORS
from sdw.split import SPLIT_ORDER

# The domain separator; the trailing `/1` versions the scheme, so an id computed under a new
# preimage recipe can never be mistaken for a stale one recomputed under the old (ADR-0010).
DOMAIN_SEPARATOR = "sdw-dataset-version/1"

# Full `sha256:` + 64 hex — the provenance id shape, distinct from the truncated `rec_`/`prm_` + 16
# hex handles used as filenames and join keys. `dataset_version` is never a filename (ADR-0003), so
# it takes the provenance form and keeps its full collision margin (ADR-0010).
HASH_ALGORITHM = "sha256"
HASH_PREFIX = f"{HASH_ALGORITHM}:"

# The descriptor, written at the `--data-out` root; #30 writes it last as the completeness sentinel.
DESCRIPTOR_NAME = "dataset.json"

# The emitted-artifact schema version, distinct from `tool_version` (ADR-0006).
MANIFEST_VERSION = "0.1"

# Self-description for the descriptor only; these constants ride into the id through `tool_version`,
# not directly (ADR-0005 gives normalization no config section).
_NORMALIZATION = {
    "sample_rate": TARGET_SAMPLE_RATE,
    "num_channels": NUM_CHANNELS,
    "encoding": TARGET_SUBTYPE,
    "downmix": "mean",
    # Imported, not spelled `"soxr_hq"`, so a resampler-band change cannot leave this describing a
    # normalization the tool no longer performs.
    "resampler": f"soxr_{RESAMPLE_QUALITY.lower()}",
}

# The recipe as prose — ADR-0010 made recomputation a documented recipe, not a command.
_HASHING = {
    "algorithm": HASH_ALGORITHM,
    "recording_id": "rec_ + first 16 hex of sha256(Original file bytes)",
    "content_hash": f"{HASH_PREFIX}<full 64 hex>",
    "dataset_version": (
        "sha256 over: domain separator + tool_version + canonical effective config "
        "+ each of train/val/test.jsonl framed by name and byte length"
    ),
}


@dataclass(frozen=True)
class Provenance:
    """A built Dataset's identity, and the descriptor that records it.

    ``files`` mirrors :attr:`~sdw.manifest.Dataset.files` (a path under the ``--data-out`` root
    → that file's contents) so #30 commits both with one writer. ``dataset_version`` is surfaced
    beside it because the build reports the id to stdout as well as writing it, and re-parsing the
    descriptor to recover a value this module just computed would be a second source of truth.
    """

    dataset_version: str
    files: dict[str, str]


def build_provenance(config: Config, dataset: Dataset) -> Provenance:
    """Compute the id and render the descriptor for a built Dataset. Pure; touches no filesystem.

    The config is serialized **once**, into ``canonical`` below, and that one string feeds both the
    preimage and the descriptor's ``config`` block, so identity and record cannot disagree — what
    makes the id recomputable from ``--data-out`` alone (ADR-0010, #8).
    """
    canonical = config.canonical_json()
    version = _version_of(canonical, dataset.files, __version__)
    document = {
        "manifest_version": MANIFEST_VERSION,
        "tool_version": __version__,
        "dataset_version": version,
        "config": json.loads(canonical),
        "normalization": _NORMALIZATION,
        "hashing": _HASHING,
        "split": {"counts": _counts(dataset.samples)},
        "sessions": _sessions(dataset.samples),
    }
    return Provenance(dataset_version=version, files={DESCRIPTOR_NAME: _render(document)})


def dataset_version(
    config: Config, files: Mapping[str, str], tool_version: str = __version__
) -> str:
    """The id of the Dataset those ``files`` make, as ``sha256:`` + 64 hex (ADR-0010).

    ``files`` is :attr:`~sdw.manifest.Dataset.files` — the whole emitted tree — but only the three
    ``<split>.jsonl`` are read; passing the full mapping is safe, and a filtered one would be a
    second place that has to know the exclusion rule. ``tool_version`` is a parameter rather than an
    inlined constant so a test can vary it directly.
    """
    return _version_of(config.canonical_json(), files, tool_version)


def _version_of(canonical_config: str, files: Mapping[str, str], tool_version: str) -> str:
    """ADR-0010's preimage over an already-serialized config, hashed — the one recipe.

    Split from :func:`dataset_version` so the serialize-once path has somewhere to hand its string,
    keeping exactly one copy of the framing.
    """
    hasher = hashlib.sha256()
    hasher.update(f"{DOMAIN_SEPARATOR}\n".encode(ENCODING))
    hasher.update(f"tool_version\n{tool_version}\n".encode(ENCODING))
    hasher.update(f"config\n{canonical_config}\n".encode(ENCODING))
    for name in SPLIT_ORDER:
        # Default "" not `[]`: ADR-0004's produce-and-flag case yields an empty Split, which must
        # frame at length 0, not be skipped — a skipped frame would let a 2-Split build collide with
        # a 3-Split one.
        raw = files.get(f"{name}.jsonl", "").encode(ENCODING)
        hasher.update(f"{name}.jsonl {len(raw)}\n".encode(ENCODING))
        hasher.update(raw)
    return HASH_PREFIX + hasher.hexdigest()


def _counts(samples: tuple[Sample, ...]) -> dict[str, int]:
    """Realized Sample counts per Split, plus the total (ADR-0010).

    Realized, not configured — the seed and ratios live under ``config``. Every Split in
    :data:`~sdw.split.SPLIT_ORDER` is present even at zero, so an absent key reads as "not built"
    rather than "built and empty".
    """
    counts = {name: sum(1 for s in samples if s.split == name) for name in SPLIT_ORDER}
    return counts | {"total": len(samples)}


def _sessions(samples: tuple[Sample, ...]) -> list[dict[str, object]]:
    """The Session inventory, sorted by ``session_id`` so it stays diffable across builds.

    A Session's Split is well-defined because splitting is session-aware — every Sample of a Session
    lands in one Split (ADR-0004).
    """
    splits = {sample.session_id: sample.split for sample in samples}
    return [
        {
            "session_id": session_id,
            "split": split,
            "num_samples": sum(1 for s in samples if s.session_id == session_id),
        }
        for session_id, split in sorted(splits.items())
    ]


def _render(document: Mapping[str, object]) -> str:
    """The descriptor as text: compact, LF-terminated, top-level keys in insertion order.

    Takes its byte format from the same constants as the manifest (#54) so the embedded ``config``
    block stays byte-identical to the bytes the preimage hashed. ``sort_keys`` is off to keep
    ADR-0010's documented top-level order; the ``config`` subtree is already key-sorted by
    :meth:`~sdw.config.Config.canonical_dict`.
    """
    return (
        json.dumps(
            document,
            ensure_ascii=JSON_ENSURE_ASCII,
            separators=JSON_SEPARATORS,
        )
        + "\n"
    )
