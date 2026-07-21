# Storage layout, file naming, and retention

We fix the on-disk shape of a build — the `--data-out` tree, how files are named from ids, the
`--data-in` input contract, how a build is committed atomically, and what is retained — because
these are referenced by the pipeline, the manifest (issue #12), the splitter (issue #10), and every
stage that reads input or emits output. This ADR builds directly on ADR-0001 (identifiers) and
ADR-0002 (stateless `--data-in` → `--data-out`); it does not reopen them, only makes their
storage consequences concrete.

## Decisions

### `--data-out` version model

- **Single current build.** `--data-out` holds exactly one build. A rebuild replaces its entire
  contents (via the atomic swap below); `dataset_version` (ADR-0001) is recorded *inside*
  `dataset.json` for identity, but prior versions are **not** accumulated on disk. On-disk version
  accumulation is deferred to a future dataset-versioning/provenance decision.
- **Accepted trade:** because `--data-in` evolves (Originals added/removed) and old builds aren't
  kept, an older `dataset_version` cannot be regenerated once its exact input set is gone. v0.1
  reproducibility is intrinsic (same `--data-in` + params → same version), so this is acceptable.

### `--data-out` directory tree

```
<data-out>/
  dataset.json                          # reproducibility descriptor: dataset_version, params, tool version
  train.jsonl                           # per-split manifests, NeMo-native, at root
  val.jsonl
  test.jsonl
  audio/                                # normalized WAVs, bucketed by split
    train/  <recording_id>.wav …
    val/    <recording_id>.wav …
    test/   <recording_id>.wav …
  images/                               # flat, keyed by recording_id
    <recording_id>.waveform.png
    <recording_id>.spectrogram.png
  reports/
    quality.jsonl                       # one line per Recording, keyed by recording_id
    summary.txt                         # human-readable build summary
```

- **`audio/` is bucketed by split.** `ls audio/test/` answers "what's in test?", and `train`/`val`/
  `test` subdirs are the zero-config layout HF `audiofolder` auto-detects — the physical tree is
  consumer-friendly with no transform. A Recording's split is encoded in its path; re-splitting
  moves the file, which is free under single-current-build + atomic replace.
- The exact manifest **fields** and any consumer-specific view files belong to issue #12; how splits
  are **computed** belongs to issue #10. This ADR fixes only where files physically sit.

### File naming keyed to ids

- **Normalized WAV filename = `recording_id`** (a hash, per ADR-0001): `audio/<split>/<recording_id>.wav`.
  The filename *is* the identity, so it is unique by construction, byte-identical Originals collapse
  to one file (matching ADR-0001's dedupe property), and no attempt-ordinal bookkeeping is needed.
- **`recording_id` = `rec_` + first 16 hex chars of `sha256`** over the raw Original **file bytes**
  (lowercase hex). This refines ADR-0001's abstract "content hash of the Original audio": it pins
  the algorithm, encoding, length, and `rec_` prefix. `sample_id` == `recording_id`.
- **The manifest additionally carries the full `sha256` digest as `content_hash`**, and the full
  digest — not the truncated id — is the input to `dataset_version`. Short id for tidy, scannable
  filenames; full digest for integrity and version identity (a git-style short-id/full-hash split).
- **Images and reports share the `recording_id` stem**, so every artifact for a Recording is one
  `ls audio/*/<id>* images/<id>* ` / manifest lookup away. `recording_id` is the single stem across
  audio → images → quality lines. Which images and their params are a separate visualization
  decision.

### `--data-in` input contract

- **A fixed `recordings.csv` at the `--data-in` root** is the authoritative index (columns per issue
  #8: `path, speaker_id, session_id, prompt_text, device, environment`). The name is fixed, not
  configurable. "Manifest" is reserved for the *output* HF/NeMo artifact; the input's rows are
  Recordings, hence `recordings.csv`.
- **The `path` column is a POSIX relative path from the `--data-in` root** to each Original. Any
  subdirectory arrangement of Originals is allowed; the tool imposes no layout. **Absolute paths and
  `..`-escapes are rejected** — an Original must live within `--data-in`, keeping a `--data-in` set
  self-contained and portable.
- **Files under `--data-in` not referenced by the CSV are silently ignored** (not an error, not a
  warning) — `--data-in` is the operator's external drop, not the tool's to police.

### Atomic commit (staging → swap)

Per issue #8, a build lands in "one atomic commit" and, on a hard error, produces no durable output.
There is no portable atomic whole-directory swap (`RENAME_EXCHANGE` is Linux-only; the primary user
is on macOS), so "atomic" means *no partial build is ever visible as finished*.

- **Stage** the entire tree into a sibling `<data-out>.tmp/` (same parent ⇒ same filesystem ⇒ cheap
  renames). Nothing touches `<data-out>` during the run. (Assumes the parent of `--data-out` is
  writable.)
- **`dataset.json` is written last**, inside the staging dir, and serves as the completeness
  sentinel: a `--data-out` whose `dataset.json` is absent/unreadable is by definition incomplete.
- **Commit on success:** rename `<data-out>` → `<data-out>.old` (if present), rename `<data-out>.tmp`
  → `<data-out>`, delete `.old`. The only gap without a live `--data-out` is sub-millisecond and
  recoverable.
- **Abort on hard error:** discard `<data-out>.tmp`, leave the prior `<data-out>` untouched, exit
  non-zero (issue #8 abort policy). Stale `*.tmp`/`*.old` from a crash are cleaned at the next run's
  start. Recovery is just re-running, since the build is deterministic/idempotent.

> **Amended by #64 — who writes what.** This section fixes the protocol but never said which code
> may write where, and the implementation had settled on "`commit` is the only writer" as shorthand.
> Stated precisely: **`commit` is the only writer of `<data-out>` itself** — the sentinel and the
> swap are its and no one else's, so the atomicity guarantee has one auditable enforcement point.
> Writing *into* the staging tree is a different act, and always was: the image and report stages
> have written their PNGs and JSONL into `<data-out>.tmp` since they landed. #64 gives that side of
> the line an owner — a `staging` module that composes every path under the staging root and places
> every artifact in it, sitting above `commit` as its only caller. Nothing about the three moves,
> the sentinel, or the abort behaviour changes; the committed tree is byte-identical.

### Retention

Retention is a consequence of the stateless in→out shape (ADR-0002), not a separate feature or knob.

- **Originals: always retained, untouched.** They live only in `--data-in` (external, read-only);
  the tool never copies, moves, or deletes them.
- **Derived: always regenerated, replaced wholesale.** Every build writes the full derived tree
  fresh into `--data-out`; the swap is the only "cleanup" — there is no per-file pruning/GC.
- **No intermediates persist** outside the committed tree (`.tmp` is renamed in or discarded).
- Soft-flagged Recordings' normalized audio **is** retained and flagged (all attempts are data,
  issue #8); a hard error yields no durable output.

## Considered and rejected

- **Accumulating versions on disk** (`<data-out>/<dataset_version>/…`) — reproducibility is
  intrinsic, so hoarding builds isn't needed for it; `dataset_version` is an unfriendly hash for a
  directory name, growth is unbounded, and it drags in "which is current / GC old ones" machinery.
  Deferred to a dedicated versioning decision.
- **Readable composite WAV filenames** (`{speaker}__{session}__{prompt-slug}__{attempt}.wav`) —
  reintroduces the attempt-ordinal + slug-collision machinery ADR-0001 deliberately avoided for
  identity, and doesn't dedupe byte-identical files. The hash filename plus the manifest as a
  decoder ring preserves inspectability without that machinery.
- **Full 64-char `recording_id`** — one value everywhere, but names are long and wrap in a terminal.
  The short-id/full-`content_hash` split keeps directories scannable while integrity and
  `dataset_version` still rest on the full digest.
- **Flat `audio/` with split only in the manifest** — loses `ls audio/<split>/` inspectability and
  the zero-config HF `audiofolder` split detection.
- **Configurable input-CSV name** — an extra flag for no v0.1 benefit; a fixed `recordings.csv` is
  narrower and more inspectable.
- **Staging inside `<data-out>/.staging/`** — avoids writing outside the given path, but can't be
  committed by a single whole-dir rename and leaves partial state under `--data-out`; the sibling
  `.tmp` is cleaner.
- **Keeping the previous build as `.old`** — contradicts single-current-build; `.old` is deleted
  after a successful swap.
- **A dedicated layout module** (added by #66, deciding #64) — a leaf module owning the composition
  of every path under the staging root, so that this ADR's tree maps one-to-one onto one file. It
  has exactly one production consumer: `staging` evaluates those paths, and nothing else does. The
  tests do import the leaf modules' subtree constants where they assert that two modules *agree*,
  but the assertions that pin this ADR's tree spell it literally on purpose and must keep doing so
  (ADR-0008), so they are not a consumer a layout module could serve. Deleting it would move four
  path expressions back into the only code that evaluates them: complexity relocated, not
  concentrated. The cost is paid either way — four names one hop further from their use — with no
  second implementation, no test double, and no independent variation bought in return. `staging`
  composes all four inside one class instead, while each leaf module keeps owning its own subtree
  name. **Reopen if either trigger fires:** a command that *reads* a built `--data-out` back (a
  verify, an incremental rebuild, a publish step), which makes writing and reading two consumers
  that must agree and a mismatch a silent wrong-path bug; or the tree shape becoming configurable,
  which this ADR currently forbids.
