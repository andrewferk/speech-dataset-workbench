# Architecture

Orientation for someone about to change the code: the shape of the system, the seam the pipeline is
built on, and where each concern lives.

It explains no mechanism. Every module in `src/sdw/` opens with a docstring that states its stage,
its role, and the facts that pin its shape — that is the description of how a thing works, and it is
the one that cannot drift from the code. This doc describes only what holds *between* modules.

## The shape

`sdw` is a stateless transform: one `--data-in` directory in, one `--data-out` directory out, and
nothing retained between runs — no managed workbench directory, no registry, no database
([ADR-0002](adr/0002-stateless-data-in-data-out.md)). A Dataset is exactly the contents of one
`--data-in`; rebuilding after an edit produces a new Dataset Version rather than mutating an old
one. There are two commands: `build` reads `--data-in` and replaces `--data-out` wholesale,
`validate` reads `--data-in` and writes nothing, anywhere, and both accept an optional `--config`
TOML. That is the entire surface — everything else is a consequence of the seam below. The
vocabulary throughout — Recording, Sample, Split, Dataset Version, Quality flag — is defined in
[`CONTEXT.md`](../CONTEXT.md), and this doc uses it as defined.

## The pipeline seam

The spine, as built:

```
                _preflight          config + ingest
                    │
                _measured           normalize → quality, one Recording at a time
                    │
        ┌───────────┴───────────┐
     analyze                 staging            build only
   (metrics only)          add / finish
                               │
                            commit               the only writer of --data-out
```

**Stages 1–3 have one implementation, not two.** `pipeline._preflight` (config, then ingest) and
`pipeline._measured` (normalize, then quality) are called by `build` and by `validate` alike.
`validate` cannot disagree with `build` about whether an input is well-formed, because there is no
second code path to disagree with — the property is structural rather than a promise two
implementations keep in step. Its reach is bounded by where the shared code stops, and the boundary
is clean: `HardError` is raised in six modules, and the four the shared stages run — `pipeline`,
`config`, `ingest`, `normalize` — are exactly the ones whose errors are about `--data-in` or
`--config`. The two outside are about neither: `commit` rejects a `--data-out` that is not a
directory, and `images` fails on a render. So a green `validate` settles every hard error derivable
from the input, and only those.

**`validate` writes nothing because it has nowhere to write.** `pipeline.analyze` is `validate`'s
whole body, and it is never handed an output path. Not a flag that could be set wrong, not a branch
that could be taken by mistake: writing is unreachable from the function `validate` calls.

**The decode loop is a generator, and that is why `build` is shaped the way it is.** `_measured`
yields one Recording with its Normalized audio and its metrics at a time, because a Dataset's worth
of decoded float64 does not fit in memory. `build` therefore cannot receive a finished list and hand
it onward — it must consume each Recording while its audio is still in hand. That is why
`staging.StagedTree.add` takes one Recording rather than a collection, and why the Images and the
Normalized WAV are produced inside the loop.

**Rendering precedes splitting.** `images` runs inside the decode loop, while `split` runs only
after every Recording has been collected — so an Image exists before its Recording has a Split, and
`images` can depend on nothing the splitter decides. Note that the module docstrings number
splitting as the fourth stage and image rendering as the fifth: that ordering is logical, not
temporal. [ADR-0011](adr/0011-visualization-output.md) states the pipeline order as
`normalize → validate → split → manifest → images → report` and describes `validate` as stages 1–4;
as built, `validate` is stages 1–3 and images precede both splitting and the Manifest. The code is
the authority here and the ADR's ordering is stale, which is noted rather than silently adopted.

**`staging` owns *what* goes into the tree; `commit` owns *when* it becomes a Dataset.** They are
separate modules because a placement bug and a swap bug have different tests and different fixes.
`staging` is `commit`'s only caller.

**`commit` is the only module that touches `--data-out`.** Every stage writes into a sibling staging
tree instead, by one of two routes: `images` and `reports` write their own artifacts into the tree
directly, while `manifest` and `provenance` stay pure and return `{path: text}` maps that `commit`
renders. That is why `dataset_version` can hash exactly the bytes a consumer receives: `provenance`
hashes what `manifest` returned, not what was later found on disk
([ADR-0010](adr/0010-dataset-version-and-provenance.md)).

**`dataset.json` is the completeness sentinel, and `commit` writes it last.** Not by a caller's
discipline but by structure: no other module can write it, and the swap follows immediately
([ADR-0003](adr/0003-storage-layout-naming-retention.md)).

**An abort anywhere leaves the last good Dataset untouched.** No stage can damage `--data-out`,
because no stage can reach it — the staging tree absorbs every failure, and an interrupt is no
different from a hard error. No build is ever visible half-finished.

**The splitter always sees the fixed surviving set.** [ADR-0004](adr/0004-session-aware-splitting.md)
requires that every Recording has survived `normalize` and `quality` before any Session is placed;
`staging` guarantees it by construction rather than by ordering its calls carefully, so no caller can
reintroduce the bug.

## Where things live

One line per module. Mechanism is in the docstring; the choices behind it are in the linked ADRs.

| Module | Concern |
| --- | --- |
| `cli.py` | Argument parsing and the `sdw` entry point ([ADR-0014](adr/0014-build-backend-and-installed-entry-point.md)); the mapping from an outcome to an exit code ([ADR-0003](adr/0003-storage-layout-naming-retention.md), [ADR-0007](adr/0007-audio-validation-quality-checks.md)). |
| `__main__.py` | The `python -m sdw` door onto the same `main` ([ADR-0014](adr/0014-build-backend-and-installed-entry-point.md)). |
| `pipeline.py` | The two commands' bodies: the shared preflight and the decode loop ([ADR-0002](adr/0002-stateless-data-in-data-out.md), [ADR-0005](adr/0005-input-formats-and-normalization-target.md)). |
| `config.py` | Defaults, the `--config` override, validation, and the one canonical config serialization ([ADR-0004](adr/0004-session-aware-splitting.md), [ADR-0006](adr/0006-output-manifest-format.md), [ADR-0007](adr/0007-audio-validation-quality-checks.md)). |
| `ingest.py` | Reads `recordings.csv`, resolves the Originals, derives the content-based ids ([ADR-0001](adr/0001-identifier-scheme.md), [ADR-0013](adr/0013-recordings-csv-ingest-and-duplicate-resolution.md)). |
| `normalize.py` | Turns an Original into its Normalized audio ([ADR-0005](adr/0005-input-formats-and-normalization-target.md)). |
| `quality.py` | The metrics, the three Quality flags, and the digest ([ADR-0007](adr/0007-audio-validation-quality-checks.md)). |
| `split.py` | The session-aware partition into train/val/test, returned as data ([ADR-0004](adr/0004-session-aware-splitting.md)). |
| `images.py` | A waveform and a spectrogram PNG per Recording ([ADR-0011](adr/0011-visualization-output.md)). |
| `manifest.py` | The deliverable: the per-Split JSONL and the `audiofolder` view ([ADR-0006](adr/0006-output-manifest-format.md)). |
| `provenance.py` | `dataset_version` and the `dataset.json` descriptor ([ADR-0010](adr/0010-dataset-version-and-provenance.md)). |
| `reports.py` | `reports/quality.jsonl` and `reports/summary.txt` ([ADR-0007](adr/0007-audio-validation-quality-checks.md), [ADR-0004](adr/0004-session-aware-splitting.md)). |
| `serialization.py` | The canonical JSON byte format, imported by every writer ([ADR-0006](adr/0006-output-manifest-format.md), [ADR-0008](adr/0008-testing-strategy-and-synthetic-fixtures.md), [ADR-0010](adr/0010-dataset-version-and-provenance.md)). |
| `staging.py` | What goes into the `--data-out` tree, and where ([ADR-0003](adr/0003-storage-layout-naming-retention.md)). |
| `commit.py` | The only writer of `--data-out`, and when a tree becomes a Dataset ([ADR-0003](adr/0003-storage-layout-naming-retention.md)). |
| `errors.py` | `HardError` — the abort, as distinct from a Quality flag ([ADR-0003](adr/0003-storage-layout-naming-retention.md), [ADR-0007](adr/0007-audio-validation-quality-checks.md)). |
| `__init__.py` | `__version__`, the single declaration, and one of `dataset_version`'s inputs ([ADR-0010](adr/0010-dataset-version-and-provenance.md)). |

## What this doc does not cover

A fact earns a place in this doc's prose **only if stating it requires two modules**: order,
direction of dependency, where a boundary sits, and what each side is denied. Everything else is
delegated, by destination:

- a fact true of **one module alone** → that module's docstring
- a **choice with rejected alternatives** → an ADR under [`adr/`](adr/)
- a **term** → [`CONTEXT.md`](../CONTEXT.md)

The rule is testable on every edit: for each sentence, ask *does this need two modules to state?* If
not, cut it and link.

The one carve-out is *Where things live*, which is an **index** and may echo the docstrings — but
each entry is capped at one line and may not explain mechanism. That exception is written down here
so that it is bounded, and it does not widen by precedent.
