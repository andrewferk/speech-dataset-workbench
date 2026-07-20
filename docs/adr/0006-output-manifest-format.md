# Output manifest format (v0.1)

We fix the concrete shape of the dataset the workbench emits — which files, the per-Sample fields,
the dataset-level descriptor, and the explicit mapping to Hugging Face `datasets` and NVIDIA NeMo —
because these are the deliverable a downstream consumer actually loads, and every other stage
(normalization, splitting, validation, versioning) exists to feed them. This ADR builds on ADR-0001
(identifiers), ADR-0003 (storage layout & naming), ADR-0004 (splitting), ADR-0005 (normalization
target), and research #5 (manifest conventions); it does not reopen them, only makes their output
consequences concrete. It owns the manifest's fields and any consumer-view files — the scope
ADR-0003 explicitly deferred to issue #12.

## Decisions

### Files a build emits

- **Per-split canonical manifests** at the `--data-out` root: `train.jsonl`, `val.jsonl`,
  `test.jsonl` — **JSON Lines**, one Sample per line. NeMo-native (see mapping). JSONL, not CSV:
  CSV quoting of free-form transcript text is a hazard both consumers avoid.
- **A dataset-level descriptor** `dataset.json` at the root (below).
- **Per-split HF views** `audio/<split>/metadata.jsonl`, one beside each split's WAVs, so
  `load_dataset("audiofolder", data_dir="<data-out>/audio")` works with **zero** user code.
- There is **no `export` command and no `README.md`** in v0.1: both manifest views are written by
  the single atomic `build` (issue #8, ADR-0003). HF Hub publishing (dataset card, `configs` YAML,
  `push_to_hub`) is v0.2.

> **Amended by #28**: the empty-Split case was unstated — the canonical manifests are emitted
> unconditionally, the HF views only where there is audio. See *Sample order and the empty-Split
> case* below.

### Canonical Sample line (`train/val/test.jsonl`)

A superset of NeMo's required keys, emitted in this fixed key order:

| Field            | Value                                                                        |
|------------------|------------------------------------------------------------------------------|
| `id`             | `= sample_id = recording_id` — `rec_` + first 16 hex of `sha256(Original bytes)` (ADR-0001/0003) |
| `audio_filepath` | relative POSIX from the `--data-out` root: `audio/<split>/<recording_id>.wav`, pointing at the **Normalized** WAV |
| `duration`       | seconds of the Normalized WAV, float, rounded to 3 decimals (ms)             |
| `text`           | the **verbatim** Prompt text (intended text)                                 |
| `perceived_text` | always `null` — the reserved dual-annotation slot (uncollected in v0.1)      |
| `prompt_id`      | `prm_` + first 16 hex of `sha256(NFC + trim + whitespace-collapse of the prompt text)` |
| `speaker_id`     | human-assigned, carried from `recordings.csv`                                |
| `session_id`     | human-assigned, carried from `recordings.csv`                                |
| `device`         | free-text, carried from `recordings.csv`                                     |
| `environment`    | free-text, carried from `recordings.csv`                                     |
| `sample_rate`    | `16000` (the on-disk Normalized WAV)                                         |
| `num_channels`   | `1` (the on-disk Normalized WAV)                                             |
| `content_hash`   | `sha256:` + full 64 hex of the **Original file bytes**                       |
| `lang`           | configured ISO 639-1 code, or `null` (see config)                           |
| `split`          | `"train"`/`"val"`/`"test"` — provenance only; no consumer reads split from the line |

- **`text` is always verbatim**; `prompt_id`'s normalization only defines when two Prompts are
  *the same*, and does not case-fold or strip punctuation, so `"Hello."` and `"hello"` stay distinct.
- `content_hash` and `recording_id` hash the **Original file bytes**, not decoded PCM (ADR-0003).
  The `sha256:` prefix makes the algorithm self-describing and a future algorithm change unambiguous.
- The manifest describes the **Normalized** audio (the file on disk in `audio/`); the Original is
  referenced only through `content_hash`/`recording_id` and lives untouched in `--data-in`. The
  Original's native rate/channels are recoverable from it and are **not** duplicated into the line.
- `offset` (a NeMo optional) is **omitted**: one Recording is one utterance per file, so it is
  always `0.0`, which NeMo assumes for a missing key.

### HF view line (`audio/<split>/metadata.jsonl`)

The canonical line with two mechanical transforms: `audio_filepath` → **`file_name`** (bare
`<recording_id>.wav`, since the metadata sits beside the audio) and **`split` dropped** (the folder
*is* the split). All other keys ride along as HF features, so both views stay in lockstep. HF
recognizes `val` as a validation-split keyword, so `audio/val/` needs no rename (ADR-0003 stands).

### `dataset.json`

> **Amended by ADR-0010** (`config` block added; `split` reduced to realized counts; top-level
> `lang` removed; `hashing.dataset_version` corrected). The shape below is superseded — see ADR-0010
> for the current `dataset.json`.

```json
{
  "manifest_version": "0.1",
  "tool_version": "<workbench version>",
  "dataset_version": "<full sha256 content-derived id, ADR-0001>",
  "lang": "en",
  "normalization": { "sample_rate": 16000, "num_channels": 1, "encoding": "PCM_16",
                     "downmix": "mean", "resampler": "soxr_hq" },
  "hashing": { "algorithm": "sha256",
               "recording_id": "rec_ + first 16 hex of sha256(Original file bytes)",
               "content_hash": "sha256:<full 64 hex>",
               "dataset_version": "sha256 over sorted Sample content_hashes + normalization params + tool_version" },
  "split": { "seed": "<seed>", "ratios": { "train": 0.8, "val": 0.1, "test": 0.1 },
             "counts": { "train": 42, "val": 6, "test": 5, "total": 53 } },
  "sessions": [ { "session_id": "2026-07-14-quiet", "split": "train", "num_samples": 18 } ]
}
```

- The `normalization` and `hashing` blocks are recorded even though they are v0.1 constants, so the
  dataset explains its own reproducibility inputs standalone.

  > **Corrected by ADR-0010.** This originally continued: "— they are literally what feeds
  > `dataset_version`." They do not, and could not under any workable scheme. Normalization is fixed
  > constants (ADR-0005) that reach the id via `tool_version`, and `hashing` merely describes the
  > recipe. Both blocks remain, as **self-description**. What actually feeds the id is the emitted
  > manifest plus the effective config — recorded in the new `config` block (ADR-0010).
- The `sessions` inventory documents the session-aware partition (ADR-0004) at the dataset level,
  making "a whole Session is never torn" auditable without parsing the three manifests.
- The **byte-exact serialization of the `dataset_version` hash preimage** (how the inputs above are
  canonicalized before hashing) is pinned by **ADR-0010**, not here. Note its consequence for this
  ADR: the preimage hashes the emitted `train/val/test.jsonl` **bytes**, so every field in the table
  above is covered by the id automatically, and any field added here in future is covered without
  touching ADR-0010.

### Config

- This ADR owns the **`[manifest]`** config section. Its only v0.1 key is **`lang`** — an optional
  ISO 639-1 code (default unset → emitted as `null` in every line, and under `config.manifest.lang`
  in `dataset.json`; ADR-0010 removed the top-level `lang` field).

### Determinism

Per issue #8, the same input + config + tool version must yield byte-identical artifacts, so
`dataset_version` is intrinsically reproducible:

- Fixed per-Sample key order (the table above); `duration` rounded to 3 decimals; floats formatted
  canonically; UTF-8, LF newlines, stable JSON separators, no trailing whitespace.
- Sample lines ordered deterministically; `sessions` sorted by `session_id`.
- **No timestamps, wall-clock, host, or path-outside-the-tree facts** anywhere in the durable output.

> **Amended by #28**: "ordered deterministically" left the key unnamed — it is now `recording_id`,
> ascending. See *Sample order and the empty-Split case* below.

### Amended by #28 — Sample order and the empty-Split case

The decisions above required Sample lines to be "ordered deterministically" without naming a key,
and were silent on what a build emits for a Split with no Samples. Both are pinned here:

- **Sample lines are ordered by `recording_id`, ascending.** A total order over a content-derived
  id, so reordering the rows of `recordings.csv` — which changes nothing about the Dataset —
  cannot change a byte of any manifest, and so cannot mint a new `dataset_version` (ADR-0010).
  Session- or speaker-grouped order was available and is rejected: it would make the emitted bytes
  depend on a grouping the consumer does not read.
- **All three `<split>.jsonl` are always emitted; `audio/<split>/metadata.jsonl` only where there
  is audio.** A consumer opening `test.jsonl` on a Dataset too small to fill test should read zero
  Samples, not crash on a missing file. The HF view is asymmetric with it deliberately: no
  `audio/<split>/` directory exists for an empty Split, so a `metadata.jsonl` there would describe
  a folder that is not present.

## Considered and rejected

- **A single manifest serving both consumers** — impossible: NeMo needs `audio_filepath`
  (root-relative), HF needs `file_name` (relative to the metadata file). Different key *and*
  different base. Emitting both views is the only zero-transform path for both.
- **HF via a documented rename only (no `metadata.jsonl`)** — narrower, but leaves HF non-turnkey;
  emitting the second view during `build` (folded in, not a separate command) keeps both consumers
  zero-code and is consistent with issue #8.
- **`device_id` / `environment_id`** — implies an id scheme that does not exist (ADR-0001 ids only
  prompt/recording/speaker/session); the `_id` suffix stays reserved for real id handles.
- **Reserving `perceived_text` in docs only** — emitting `perceived_text: null` per line makes the
  dual-annotation schema literal, so v0.2 populates it in place with no schema change.
- **Bare-hex `content_hash`** — matches `sha256sum` output but leaves the algorithm implicit; the
  `sha256:` prefix is cheap self-description.
- **Aggressive `prompt_id` normalization** (case-fold, strip punctuation) — risks merging Prompts
  the operator meant as distinct (capitalization/punctuation drills); light normalization only.
- **`source_sample_rate`/`source_num_channels` provenance fields** — the Original is retained in
  `--data-in` and identified by `content_hash`, so its native format is recoverable; not duplicated.
- **Keeping `offset`, or a per-line split HF reads** — always-constant noise; dropped.
- **Emitting a `README.md` dataset card + `configs` YAML** — real surface that reads as a v0.2
  publish feature; the local `audiofolder` path already works turnkey without it.
```