"""`dataset_version` and the `dataset.json` descriptor (#29, ADR-0010).

The identity of a built Dataset, and the record that explains it. This is the whole of the
project's substitute for DVC-style data versioning: ADR-0001 chose a content-derived id so that
reproducibility would be intrinsic, needing no registry and no bookkeeping. That promise is only
as good as the byte-exact recipe behind the hash, which ADR-0010 pins and this module implements.

Four facts pin the shape:

- **The Manifest is hashed as emitted, not as a hand-listed set of fields.** The Sample lines
  already carry `content_hash`, `text`, `prompt_id`, `speaker_id`, `session_id`, `device`,
  `environment`, `lang` and `split`, so hashing the bytes covers every one — and keeps covering
  fields added later with no parallel list to maintain. This closes the hole in ADR-0001's
  formulation, which hashed only the sorted `content_hash`es: fixing a typo in a `prompt_text` or
  relabelling a `session_id` leaves every audio file untouched, so two materially different
  Datasets would have claimed the same id. Here that is unrepresentable.

- **The effective config is hashed alongside**, because not every output-affecting input reaches a
  line. ADR-0007's four `[quality]` thresholds move `reports/quality.jsonl` and appear in no
  Manifest field; without config in the preimage a threshold change would silently reuse the id.

- **Each Split file is framed by name and byte length.** Framing is structural, not decorative:
  plain concatenation is ambiguous, since `train=[a,b], val=[]` and `train=[a], val=[b]` produce
  identical bytes despite being different assignments. The per-line `split` field happens to
  disambiguate them today, but that is a coincidence of ADR-0006's schema and the hash must not
  depend on it.

- **`normalization` and `hashing` in the descriptor are self-description only.** ADR-0010 corrects
  ADR-0006's claim that they are "literally what feeds `dataset_version`" — they are not, and never
  were under any workable scheme. They are kept so a Dataset explains its own reproducibility
  inputs standalone; the `config` block is what feeds the id.

What the preimage deliberately excludes is as load-bearing as what it covers. `dataset.json`
itself is circular — it carries the id. The Normalized WAVs, `reports/quality.jsonl` and
`reports/summary.txt` all derive from resampled audio floats, which ADR-0005 establishes are not
cross-arch bit-exact (soxr FFT ULPs); hashing them would make the id vary by machine and break the
exact-`dataset_version` golden ADR-0008 requires. The Manifest is safe by contrast — its
`duration` comes from a frame count, not a float comparison.

Because the id covers the Manifest as emitted, it is **recomputable from `--data-out` alone**:
read `config` and `tool_version` out of `dataset.json`, reframe the three `.jsonl`, hash, compare.
That recipe is roughly fifteen lines, which is why ADR-0010 declined a third `verify` command and
kept issue #8's two-command spine.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from sdw import __version__
from sdw.config import CANONICAL_JSON_SEPARATORS, Config
from sdw.manifest import ENCODING, NUM_CHANNELS, Dataset, Sample
from sdw.normalize import RESAMPLE_QUALITY, TARGET_SAMPLE_RATE, TARGET_SUBTYPE
from sdw.split import SPLIT_ORDER

# The domain separator, whose trailing `/1` versions *the scheme*. A future change to the preimage
# increments it, so an id computed under a new recipe can never be mistaken for a stale one
# silently recomputed under the old.
DOMAIN_SEPARATOR = "sdw-dataset-version/1"

# `sha256:` + the full 64 hex digits, matching `content_hash`. ADR-0010 keeps two id shapes and the
# distinction is deliberate: a truncated `rec_`/`prm_` + 16 hex handle for ids that become
# filenames and join keys, and this full digest for provenance values. `dataset_version` is never a
# filename — ADR-0003 keeps a single current build with no version-named directories — so it takes
# the provenance form and keeps its full collision margin.
HASH_ALGORITHM = "sha256"
HASH_PREFIX = f"{HASH_ALGORITHM}:"

# The descriptor, written at the `--data-out` root. #30 writes it last, as the completeness
# sentinel: a tree without it is a build that did not finish.
DESCRIPTOR_NAME = "dataset.json"

# The schema version of the emitted artifacts (ADR-0006). Distinct from `tool_version`: the tool
# can bump without the manifest schema changing shape.
MANIFEST_VERSION = "0.1"

# Fixed constants, not config — ADR-0005 gives normalization no config section precisely so it
# cannot mint new Dataset identities for byte-identical Manifests. They ride into the id through
# `tool_version`, and appear here only so the descriptor is self-explaining.
_NORMALIZATION = {
    "sample_rate": TARGET_SAMPLE_RATE,
    "num_channels": NUM_CHANNELS,
    "encoding": TARGET_SUBTYPE,
    "downmix": "mean",
    # Imported rather than spelled `"soxr_hq"`, so a change to the resampler band cannot leave the
    # descriptor describing a normalization the tool no longer performs. `downmix` has no upstream
    # constant to borrow — averaging channels is what the code does, not a parameter it reads.
    "resampler": f"soxr_{RESAMPLE_QUALITY.lower()}",
}

# The recipe, in the artifact that is its own audit trail. Prose rather than a machine format
# because ADR-0010 made recomputation a documented recipe, not a command.
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

    ``files`` mirrors :attr:`~sdw.manifest.Dataset.files` — a path relative to the ``--data-out``
    root mapped to that file's complete contents — so #30 commits both with one writer and neither
    stage has to know the other's shape. ``dataset_version`` is surfaced beside it because the
    build reports the id to stdout as well as writing it, and re-parsing the descriptor to recover
    a value this module just computed would be a second source of truth for one fact.
    """

    dataset_version: str
    files: dict[str, str]


def build_provenance(config: Config, dataset: Dataset) -> Provenance:
    """Compute the id and render the descriptor for a built Dataset. Pure; touches no filesystem.

    The config is serialized **once** and used for both the preimage and the descriptor's ``config``
    block, so the identity and its record cannot disagree — which is what makes the id recomputable
    from ``--data-out`` alone. Serializing twice would be correct today and a latent divergence the
    moment either call site grew an option.
    """
    version = dataset_version(config, dataset.files)
    document = {
        "manifest_version": MANIFEST_VERSION,
        "tool_version": __version__,
        "dataset_version": version,
        "config": config.canonical_dict(),
        "normalization": _NORMALIZATION,
        "hashing": _HASHING,
        "split": {"counts": _counts(dataset.samples)},
        "sessions": _sessions(dataset.samples),
    }
    return Provenance(dataset_version=version, files={DESCRIPTOR_NAME: _render(document)})


def dataset_version(
    config: Config, files: Mapping[str, str], tool_version: str = __version__
) -> str:
    """The content-derived id of the Dataset those ``files`` make, as ``sha256:`` + 64 hex.

    ``files`` is :attr:`~sdw.manifest.Dataset.files` — the whole emitted tree. Only the three
    ``<split>.jsonl`` are read from it; the WAVs, the HF views, the reports and the descriptor are
    ignored, so passing the full mapping is safe and passing a filtered one would be a second place
    that has to know the exclusion rule.

    ``tool_version`` is a parameter rather than a constant read inline so a test can vary it
    without patching a module global — the id's sensitivity to it is a property worth asserting
    directly.
    """
    hasher = hashlib.sha256()
    hasher.update(f"{DOMAIN_SEPARATOR}\n".encode(ENCODING))
    hasher.update(f"tool_version\n{tool_version}\n".encode(ENCODING))
    hasher.update(f"config\n{config.canonical_json()}\n".encode(ENCODING))
    for name in SPLIT_ORDER:
        # `files` is indexed with a default of "" rather than `[]`: ADR-0004's produce-and-flag
        # case at fewer than three Sessions yields an empty Split, which must frame at length 0
        # rather than raise or be skipped. A skipped frame would let a two-Split build collide with
        # a three-Split one.
        raw = files.get(f"{name}.jsonl", "").encode(ENCODING)
        hasher.update(f"{name}.jsonl {len(raw)}\n".encode(ENCODING))
        hasher.update(raw)
    return HASH_PREFIX + hasher.hexdigest()


def _counts(samples: tuple[Sample, ...]) -> dict[str, int]:
    """Realized Sample counts per Split, plus the total.

    Realized, not configured: ADR-0010 moved the seed and the ratios under ``config`` and left
    ``split`` holding output only, so a reader is never unsure which copy fed the hash. Every Split
    in :data:`~sdw.split.SPLIT_ORDER` is present even at zero — an absent key would read as "not
    built" rather than "built and empty".
    """
    counts = {name: sum(1 for s in samples if s.split == name) for name in SPLIT_ORDER}
    return counts | {"total": len(samples)}


def _sessions(samples: tuple[Sample, ...]) -> list[dict[str, object]]:
    """The Session inventory, sorted by ``session_id``.

    Sorted by id rather than grouped by Split so the inventory is diffable across builds: a Session
    that moved Splits then shows as a changed line in place, instead of as a deletion and an
    insertion somewhere else in the list. A Session's Split is well-defined because splitting is
    session-aware — every Sample of a Session lands in one Split (ADR-0004).
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
    """The descriptor as text: compact, LF-terminated, insertion-ordered at the top level.

    ``sort_keys`` is off so the top-level keys keep ADR-0010's documented order, which is not
    alphabetical. The ``config`` subtree still comes out key-sorted because
    :meth:`~sdw.config.Config.canonical_dict` already iterates in sorted order — which is exactly
    what makes the block byte-identical to the bytes the preimage hashed, with the same separators
    used on both sides.
    """
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            separators=CANONICAL_JSON_SEPARATORS,
        )
        + "\n"
    )
