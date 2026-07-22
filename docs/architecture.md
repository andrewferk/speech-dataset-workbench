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
one. The vocabulary those sentences use — Recording, Sample, Split, Dataset Version — is defined in
[`CONTEXT.md`](../CONTEXT.md), and this doc uses it as defined.

There are two commands. `build` reads `--data-in` and replaces `--data-out` wholesale. `validate`
reads `--data-in` and writes nothing, anywhere. Both accept an optional `--config` TOML. That is the
entire surface: everything else is a consequence of the seam below.

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
implementations keep in step. The reach of that guarantee is bounded by where the shared code stops:
the stages `build` alone runs — staging, image rendering, and the commit — are outside a read-only
preflight, so a failure there is not something `validate` can have ruled out.

**`validate` writes nothing because it has nowhere to write.** `pipeline.analyze` is `validate`'s
whole body, and it is never handed an output path. Not a flag that could be set wrong, not a branch
that could be taken by mistake: writing is unreachable from the function `validate` calls.

**The decode loop is a generator, and that is why `build` is shaped the way it is.** `_measured`
yields one Recording with its Normalized audio and its metrics at a time, because a Dataset's worth
of decoded float64 does not fit in memory. `build` therefore cannot receive a finished list and hand
it onward — it must consume each Recording while its audio is still in hand. That is why
`staging.StagedTree.add` takes one Recording rather than a collection, and why the Images and the
Normalized WAV are produced inside the loop.

**Placement precedes splitting, so the WAV moves.** `add` runs during the decode loop, before any
Session has a Split, so it writes the WAV flat under `audio/`; `finish` is the only thing that runs
the splitter, and it moves each WAV into `audio/<split>/` afterwards by rename within the staging
tree. The module docstrings number splitting as the fourth stage and image rendering as the fifth —
that ordering is logical, not temporal.

**`staging` owns *what* goes into the tree; `commit` owns *when* it becomes a Dataset.** They are
separate modules because a placement bug and a swap bug have different tests and different fixes.
`staging` is `commit`'s only caller.

**`commit` is the only module that touches `--data-out`.** Every stage writes into a sibling staging
tree instead, by one of two routes: `images` and `reports` write their PNGs and JSONL into the tree
directly, while `manifest` and `provenance` stay pure and return `{path: text}` maps that `commit`
renders. `manifest.build_dataset` is a pure function, not a phase of the run — it returns the
finished text of every file and names no path on disk, which is what lets `dataset_version` hash
exactly the bytes a consumer receives ([ADR-0010](adr/0010-dataset-version-and-provenance.md)).

**`dataset.json` is the completeness sentinel, and `commit` writes it last.** Not by a caller's
discipline but by structure: no other module can write it, and the swap follows immediately
([ADR-0003](adr/0003-storage-layout-naming-retention.md)).

**An abort discards the staging.** `staging.open` is a context manager whose exit discards the tree
on any `BaseException`, and `finish` runs inside that scope — so a failure during the swap discards
too. An interrupt is no different from a hard error: the last good `--data-out` is untouched, and no
build is ever visible half-finished.

**The splitter always sees the fixed surviving set.** Every Recording is handed to `add`, and
`finish` is the only thing that splits, so splitting before normalization and validation have
finished is not an ordering mistake a reader has to notice — it is not expressible
([ADR-0004](adr/0004-session-aware-splitting.md)).

## Where things live

One line per module. Mechanism is in the docstring; the choices behind it are in the linked ADRs.

| Module | Concern |
| --- | --- |
| `cli.py` | Argument parsing, and the mapping from an outcome to an exit code ([ADR-0014](adr/0014-build-backend-and-installed-entry-point.md)). |
| `__main__.py` | The `python -m sdw` door onto the same `main` ([ADR-0014](adr/0014-build-backend-and-installed-entry-point.md)). |
| `pipeline.py` | The two commands' bodies: the shared preflight and the decode loop. |
| `config.py` | Defaults, the `--config` override, validation, and the one canonical config serialization ([ADR-0004](adr/0004-session-aware-splitting.md), [ADR-0006](adr/0006-output-manifest-format.md), [ADR-0007](adr/0007-audio-validation-quality-checks.md)). |
| `ingest.py` | Reads `recordings.csv`, resolves the Originals, derives the content-based ids ([ADR-0001](adr/0001-identifier-scheme.md), [ADR-0013](adr/0013-recordings-csv-ingest-and-duplicate-resolution.md)). |
| `normalize.py` | Decodes an Original into mono 16 kHz 16-bit PCM ([ADR-0005](adr/0005-input-formats-and-normalization-target.md)). |
| `quality.py` | The metrics, the three advisory flags, and the digest ([ADR-0007](adr/0007-audio-validation-quality-checks.md)). |
| `split.py` | The session-aware partition into train/val/test, returned as data ([ADR-0004](adr/0004-session-aware-splitting.md)). |
| `images.py` | A waveform and a spectrogram PNG per Recording ([ADR-0011](adr/0011-visualization-output.md)). |
| `manifest.py` | The deliverable: the per-Split JSONL and the `audiofolder` view ([ADR-0006](adr/0006-output-manifest-format.md)). |
| `provenance.py` | `dataset_version` and the `dataset.json` descriptor ([ADR-0010](adr/0010-dataset-version-and-provenance.md)). |
| `reports.py` | `reports/quality.jsonl` and `reports/summary.txt` ([ADR-0007](adr/0007-audio-validation-quality-checks.md), [ADR-0004](adr/0004-session-aware-splitting.md)). |
| `serialization.py` | The canonical JSON byte format, imported by every writer. |
| `staging.py` | What goes into the `--data-out` tree, and where ([ADR-0003](adr/0003-storage-layout-naming-retention.md)). |
| `commit.py` | The only writer of `--data-out`: the staging protocol, the sentinel, the atomic swap ([ADR-0003](adr/0003-storage-layout-naming-retention.md)). |
| `errors.py` | `HardError` — the abort, as distinct from an advisory flag. |
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
