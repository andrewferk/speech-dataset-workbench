# Dataset version & provenance mechanics (v0.1)

`dataset_version` is this project's entire substitute for DVC-style data versioning: ADR-0001 chose
a content-derived id precisely so that reproducibility would be **intrinsic**, needing no registry
and no bookkeeping. That promise is only as good as the byte-exact recipe behind the hash — an id
that two machines compute differently, or that two materially different datasets share, is worse
than no id at all. ADR-0001 fixed the *intent* and ADR-0006 fixed the *manifest*, but neither
pinned the preimage. This ADR pins it, and settles what `dataset.json` promises as the
reproducibility record.

It builds on ADR-0001 (identifiers), ADR-0003 (storage & single current build), ADR-0004
(splitting), ADR-0005 (normalization), ADR-0006 (manifest), and ADR-0007 (quality config). It
**amends** ADR-0001's statement of the hash inputs and ADR-0006's `dataset.json` shape.

## Decisions

### The preimage

`dataset_version` is a `sha256` over this byte sequence, built in exactly this order:

```
sdw-dataset-version/1\n
tool_version\n<tool_version>\n
config\n<canonical config JSON>\n
train.jsonl <byte-length>\n<raw bytes of train.jsonl>
val.jsonl <byte-length>\n<raw bytes of val.jsonl>
test.jsonl <byte-length>\n<raw bytes of test.jsonl>
```

- **`sdw-dataset-version/1`** is a domain separator whose trailing `/1` versions *the scheme*. A
  future change to the preimage increments it, so an id computed under a new recipe can never be
  mistaken for a stale one silently recomputed under the old.
- **Each split file is framed** with its name and exact byte length before its raw bytes. Framing is
  structural, not decorative: plain concatenation is ambiguous, since `train=[a,b], val=[c]` and
  `train=[a], val=[b,c]` produce identical bytes despite being different split assignments. The
  per-row `split` field happens to disambiguate them today, but that is a coincidence of ADR-0006's
  schema, and the hash must not depend on it. An empty `val`/`test` — ADR-0004's produce-and-flag
  case at fewer than 3 sessions — frames cleanly as length `0`.
- Files are framed in the fixed order `train`, `val`, `test`. Raw bytes are used exactly as written
  to disk; ADR-0006 already fixes their key order, float formatting, encoding, and line endings.

### What the preimage covers, and why

**The manifest is hashed as emitted, rather than as a hand-listed set of fields.** The rows already
carry `content_hash`, `text`, `prompt_id`, `speaker_id`, `session_id`, `device`, `environment`,
`lang`, and `split`, so hashing them covers every one — and keeps covering fields added later
without a list to maintain in parallel.

This closes a hole in ADR-0001's formulation, which predates the `recordings.csv` sidecar (issue
#8): hashing only the sorted Sample `content_hash`es covers the *Original audio bytes* and nothing
else. Fixing a typo in a `prompt_text`, relabelling a `session_id`, or correcting a `speaker_id`
leaves every audio file untouched — identical content-hashes, identical id, **different manifest**.
Two materially different datasets would claim the same version. Hashing the emitted rows makes that
unrepresentable.

**The effective config is hashed alongside** because not every output-affecting input reaches a row.
ADR-0007's four `[quality]` thresholds change `reports/quality.jsonl` but appear in no manifest
field; without config in the preimage, a threshold change would silently reuse the id — the same
hole one door down. It is serialized as canonical JSON: keys sorted, UTF-8, and **all defaults
materialized**. Materializing matters — omitting `[quality]` entirely and writing out its four
default values describe the same build and must yield the same id.

**Deliberately excluded:**

- **`dataset.json`** — it contains `dataset_version`, so hashing it is circular. No manifest row
  contains the id, so the rows are safe.
- **The Normalized WAVs, `reports/quality.jsonl`, and `reports/summary.txt`** — all derive from
  resampled audio floats, which ADR-0005 establishes are **not** cross-arch bit-exact (soxr FFT
  ULPs). Hashing them would make `dataset_version` vary by machine and break the exact-`dataset_version`
  golden test ADR-0008 requires. The manifest is safe by contrast: its `duration` comes from a frame
  count, not a float comparison.
- **The `normalization` block** — ADR-0005 made normalization fixed constants with no config
  section, so there are no params to feed. The constants ride in via `tool_version`.

### `tool_version`

`tool_version` is the **workbench's own version string** (e.g. `"0.1.0"`), read from package
metadata. The dependency set is covered by convention rather than by the hash: `uv.lock` is
committed (research #3), and the release rule is that **any lock change ships a version bump**.

The residual — a `soxr` bump changing Normalized WAV bytes under an unchanged id — is a consequence
of the scheme, not a defect in it. `dataset_version` identifies **the manifest and the config**; the
audio enters only through `content_hash` of the **Originals**, which is a hash of bytes at rest and
therefore byte-exact on every machine. It was never a claim about the *Normalized* bytes, because
ADR-0005 already says those are not cross-arch reproducible — an id that covered them could not be
cross-machine stable at all. The scheme and ADR-0005 agree.

### Format

`dataset_version` is written as **`sha256:` + the full 64 hex digits**, matching `content_hash`.

ADR-0001/0003 use two id shapes, and the distinction is now explicit: a **truncated `rec_`/`prm_` +
16 hex handle** for ids that become filenames and join keys, and a **`sha256:` + full digest** for
provenance values. `dataset_version` is never a filename — ADR-0003 keeps a single current build with
no version-named directories — so it takes the provenance form and keeps its full collision margin.
`reports/summary.txt` may display a short prefix; that is presentation, not identity.

### Provenance: what `dataset.json` promises

Hashing the emitted manifest makes `dataset_version` **recomputable from `--data-out` alone**, with
no access to `--data-in`. `dataset.json` must therefore carry every preimage input, so it gains a
**`config` block** holding the effective config **verbatim — byte-identical to what the preimage
hashed** (serialize once, use for both). Without it the quality thresholds would feed an id they are
not recorded next to, and the property would be hollow.

`config` becomes the **single home** for `seed`, `ratios`, and `lang`:

```json
{
  "manifest_version": "0.1",
  "tool_version": "0.1.0",
  "dataset_version": "sha256:<64 hex>",
  "config": {
    "manifest": { "lang": "en" },
    "quality": { "silence_threshold_dbfs": -40, "low_volume_rms_dbfs": -30,
                 "duration_min_s": 0.5, "duration_max_s": 20 },
    "split": { "seed": "<seed>", "train": 0.8, "val": 0.1, "test": 0.1 }
  },
  "normalization": { "sample_rate": 16000, "num_channels": 1, "encoding": "PCM_16",
                     "downmix": "mean", "resampler": "soxr_hq" },
  "hashing": { "algorithm": "sha256",
               "recording_id": "rec_ + first 16 hex of sha256(Original file bytes)",
               "content_hash": "sha256:<full 64 hex>",
               "dataset_version": "sha256 over: domain separator + tool_version + canonical effective config + each of train/val/test.jsonl framed by name and byte length" },
  "split": { "counts": { "train": 42, "val": 6, "test": 5, "total": 53 } },
  "sessions": [ { "session_id": "2026-07-14-quiet", "split": "train", "num_samples": 18 } ]
}
```

Changes against ADR-0006: `split` keeps only the **realized counts** (which are output, not config),
top-level `lang` is **removed**, and `hashing.dataset_version` now describes the real preimage.
`normalization`, `hashing`, and `sessions` otherwise stand.

**Correction to ADR-0006:** it states that the `normalization` and `hashing` blocks "are literally
what feeds `dataset_version`." They are not, and never were under any workable scheme — both are
**self-description**, kept so the dataset explains its own reproducibility inputs standalone. The
`config` block is what feeds the id.

### Auditing

Recomputing the id is a **documented recipe**, not a command: read `config` and `tool_version` from
`dataset.json`, reframe the three `.jsonl` files, hash, compare. It is roughly fifteen lines, and
`hashing.dataset_version` self-describes it in the artifact itself.

Issue #8's **two-command surface (`build`, `validate`) stands** — no `verify`. A third command would
reopen the spine decision to serve an audit need a single technical user does not have, when the
recipe already serves it.

### On-disk multi-version accumulation

**Out of scope for v0.1**, confirming ADR-0003's single-current-build rather than merely deferring
it. ADR-0003 decided it on the merits and named the trade (older versions are unregenerable once
`--data-in` changes). Nothing here reopens it — if anything, hashing the manifest weakens the case
for hoarding builds, since a Version is now fully described by its own `dataset.json`. Retaining
prior builds is a v0.2 concern.

## Considered and rejected

- **Keeping ADR-0001's formulation literally** (sorted `content_hash`es + normalization params +
  tool version) — accepts the metadata-edit collision above, and its "normalization params" term is
  now an empty set. Defensible only if the id identifies the *audio corpus* rather than the *built
  dataset*; it identifies the built dataset.
- **An explicitly enumerated field list** (content-hashes + prompt_ids + speaker/session + device/
  environment + split + config + tool_version) — identical coverage today, but the list must be kept
  in sync with the manifest by hand forever. Add a field, forget the list, and the id silently stops
  covering it. Hashing the emitted rows cannot drift from the rows.
- **Hashing `uv.lock`** — mechanically forces a new id on any dependency change, no discipline
  needed. Rejected: it churns every dataset id on bumps that cannot affect output (`ruff`, `pytest`),
  and it requires a source checkout, so an installed wheel could not compute an id at all.
- **Hashing the runtime versions of audio deps** (`soxr`/`soundfile`/`numpy`) — precise, and works
  from a wheel, but needs a hand-maintained "deps that matter" list that rots, makes the id vary with
  the *install* rather than the repo, and misses the point anyway: `libsndfile` is a bundled C
  library whose version is not the `soundfile` wheel's.
- **Hashing all emitted artifacts, including the WAVs** — the strongest-sounding guarantee, and
  impossible: ADR-0005's resampler is not cross-arch bit-exact, so the id would differ by machine.
- **`ds_` + 16 hex** — consistent with the `rec_`/`prm_` handle style and pleasant to quote, but it
  truncates the project's central reproducibility claim to 64 bits for readability in a field nobody
  types.
- **Both a `ds_` handle and a full digest** — two names for one fact, and the ambiguity ("which do I
  quote?") is exactly what a single canonical id prevents.
- **Adding `config` while leaving `split.seed`/`ratios`/`lang` in place** — smallest amendment to
  ADR-0006, but three values would appear twice in one generated file. Low risk (one atomic build
  writes both from the same values), yet it leaves a reader unsure which copy fed the hash.
- **Recording nothing extra in `dataset.json`** — discards the main benefit of hashing the manifest,
  and leaves the quality thresholds silently affecting an id they are not recorded beside.
- **A `verify --data-out` command** — genuinely cheap (no audio decode, no `--data-in`) and makes
  self-verification a real feature, but reopens issue #8's deliberate two-command spine.
