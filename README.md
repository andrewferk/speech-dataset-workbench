# Speech Dataset Workbench

A local-first, CLI-only tool that turns a collection of **prompted** speech recordings into a
validated, reproducible, versioned dataset with an HF/NeMo-friendly manifest.

## Status: specified, not yet implemented

The wayfinding is **complete** and there is **no application code yet**. Every product,
architecture, data-model, privacy, and tooling decision for v0.1 is settled and written down:

- **[`CONTEXT.md`](CONTEXT.md)** — the domain glossary (the ubiquitous language for v0.1).
- **[`docs/adr/`](docs/adr/)** — twelve ADRs recording every decision and the alternatives rejected.
- **[Wayfinding map #1](https://github.com/andrewferk/speech-dataset-workbench/issues/1)** — the
  destination, the route taken, and what is deliberately out of scope.

Nothing stands between here and implementing v0.1. Start with `CONTEXT.md`, then read the ADRs in
order — they build on and amend one another.

## Why this exists

The longer-term goal is a product that helps people with atypical or difficult-to-understand speech
communicate, likely via speech-recognition models adapted to an individual speaker. Before
attempting model fine-tuning or a mobile app, this workbench builds the reusable data
infrastructure those experiments need.

It is also a deliberate **learning project** — modern Python, digital audio, speech dataset design,
and the HF/NeMo ecosystem. That goal shaped the scope: the work lives where the learning is.

## What v0.1 does

One `build` turns an input directory of recordings into a complete dataset, in a single atomic pass:

1. **Parse** the operator-authored `recordings.csv` index.
2. **Resolve & decode** every referenced Original (PCM WAV only).
3. **Measure quality** — energy/amplitude metrics per recording.
4. **Normalize** to mono · 16 kHz · 16-bit PCM WAV, deterministically.
5. **Split** into train/validation/test, session-aware.
6. **Emit** per-split manifests, a `dataset.json` descriptor, waveform + spectrogram PNGs, and
   quality reports.

## What v0.1 deliberately does not do

The scope was narrowed hard, and these exclusions are decisions, not gaps:

- **No model ever runs.** No Whisper, no ASR baseline, no WER/CER — that is v0.2.
- **No perceived-transcript collection and no annotation UI.** v0.1 stores *intended text* (the
  prompt). The dual-annotation model is a reserved schema slot, named but not collected.
- **No web UI.** CLI only; visualization is emitted as PNG files.
- **No DVC / experiment tracking.** Reproducibility is intrinsic — content hashes, a deterministic
  pipeline, and the manifest.
- **No auto-trimming and no VAD model.** Silence is measured and reported, never acted on.
- **No spontaneous speech, auth, multi-tenancy, cloud, or mobile.**

## How it works

### A stateless transform

The tool manages **no state of its own**. A build is a pure function of `--data-in` plus the
effective config and tool version:

```
--data-in  (external, read-only)   →   --data-out  (external, fully regenerable)
```

Originals are never copied, moved, or modified. `--data-out` holds exactly one build and is
replaced wholesale each run via an atomic staging swap — an aborted build leaves it untouched.

There is no `init`, `import`, or `delete` command: deleting a recording means removing its file
from `--data-in` and rebuilding. See [ADR-0002](docs/adr/0002-stateless-data-in-data-out.md).

### Input contract

A fixed `recordings.csv` at the root of `--data-in`, one row per Original — hand-authorable in a
spreadsheet:

```csv
path,speaker_id,session_id,prompt_text,device,environment
session-a/take-01.wav,spk_ak,ses_a,"Hello, how are you?",shure-sm7b,quiet-room
```

`path` is a POSIX path relative to the `--data-in` root; absolute paths and `..`-escapes are
rejected. Files not referenced by the CSV are silently ignored.

### Commands

Two commands, sharing one checking engine so they can never disagree:

```bash
# Full build: normalize → validate → split → manifest → images → report
sdw build --data-in ./data-in --data-out ./data-out [--config config.toml]

# Read-only preflight; runs build's stages 1–4, prints to stdout, writes nothing
sdw validate --data-in ./data-in [--config config.toml]
```

`uv sync` installs the package into `.venv`, so those commands run as written under
[mise](https://mise.jdx.dev), which points `python` at that venv. Without mise, prefix them with
`uv run` to select the same interpreter:

```bash
uv run sdw validate --data-in ./data-in
```

Nothing needs `PYTHONPATH` set — not `pytest`, not CI, not you (ADR-0014). `python -m sdw` is
equivalent to `sdw` and works wherever the venv's interpreter does; both route to the same entry
point.

`validate` exits `0` **if and only if** a subsequent `build` on the same input will not hit a hard
error. All tuning lives in an optional TOML config rather than per-parameter flags, so the CLI stays
at three flags. See [issue #8](https://github.com/andrewferk/speech-dataset-workbench/issues/8).

### Output tree

```
<data-out>/
  dataset.json              # dataset_version, effective config, tool version
  train.jsonl               # per-split manifests, NeMo-native
  val.jsonl
  test.jsonl
  audio/                    # normalized WAVs, bucketed by split (HF audiofolder layout)
    train/<recording_id>.wav …
    val/…  test/…
  images/                   # 2 per recording, keyed by recording_id
    <recording_id>.waveform.png
    <recording_id>.spectrogram.png
  reports/
    quality.jsonl           # one line per recording: all metrics + flags
    summary.txt             # human-readable build digest
```

The manifest is a superset of NeMo's required keys (`audio_filepath`, `duration`, `text`), so it is
a valid NeMo manifest with zero transformation, while HF `audiofolder` reads the same data from the
split-bucketed `audio/` tree.

## Auditing a build — recomputing `dataset_version`

`dataset_version` is a `sha256` you can recompute from a `--data-out` tree **alone**, without the
`--data-in` that produced it (ADR-0010). There is no `verify` command — the two-command spine
(`build`, `validate`) stands — because the recipe below is all it would be. Follow it by hand, or in
~15 lines of any language, to confirm a distributed Dataset's id matches its bytes:

1. **Read `dataset.json`.** Take the `tool_version` string and the entire `config` object.
2. **Re-serialize `config` canonically:** keys sorted, no whitespace between tokens
   (`,`/`:` separators), UTF-8, non-ASCII left as-is. These are the exact bytes `dataset.json`
   already stores for that block, so a canonical dump of the parsed object reproduces them.
3. **Build the preimage** — a byte string, in exactly this order, with `\n` as shown:

   ```
   sdw-dataset-version/1\n
   tool_version\n<tool_version>\n
   config\n<canonical config JSON>\n
   train.jsonl <byte-length>\n<raw bytes of train.jsonl>
   val.jsonl <byte-length>\n<raw bytes of val.jsonl>
   test.jsonl <byte-length>\n<raw bytes of test.jsonl>
   ```

   `sdw-dataset-version/1` is a domain separator whose `/1` versions the scheme. Each split file is
   framed by its **name and exact byte length** before its **raw bytes read from disk** (never
   re-serialized), in the fixed order `train`, `val`, `test`. An empty `val`/`test` frames cleanly
   at length `0`.
4. **`sha256` the preimage**, hex-encode it, and prefix `sha256:`. That string must equal
   `dataset_version` in `dataset.json`.

A mismatch means the tree's bytes and its recorded id disagree — either the Dataset was tampered
with, or this recipe and the tool have drifted. `dataset.json`'s `hashing.dataset_version` field
carries a one-line summary of the same recipe, so the artifact explains its own id standalone.

> This recipe is checked in CI by `tests/e2e/test_audit_recipe.py`, which reimplements it
> **independently — importing nothing from `src/`** — and runs it against the committed reference
> build. A test sharing the tool's own hashing code would compute `f(x) == f(x)` and pass even when
> both the code and this prose are wrong; the two are kept honest only by being written twice and
> edited together (ADR-0012 Check 3).

## The claims the design makes

- **Deterministic.** The same `--data-in` + config + tool version yields the same `dataset_version`
  and byte-identical artifacts. Re-running is a safe, byte-identical rewrite. (Cross-*architecture*
  bit-exactness is explicitly **not** claimed — soxr's FFT denies it; reproducibility leans on
  pinned versions plus content hashes.)
- **`dataset_version` is recomputable from `--data-out` alone**, without the inputs — a `sha256`
  over the emitted manifest bytes, the effective config, and the tool version.
- **Privacy is architectural.** Audio never enters git because it lives only in the two external
  directories the repo never contains — not because a gitignore rule blocks it. Metadata is
  pseudonym-only, so the manifest is freely shareable.
- **All attempts are data.** Quality flags (`clipping`, `low_volume`, `duration_out_of_range`) are
  advisory metadata; a flag never drops or quarantines a recording. Structural errors — a file that
  won't parse, resolve, or decode — hard-abort the whole build instead.
- **Splits are session-aware.** A Session is never torn across splits. Ratios (default 80/10/10,
  seeded) are **best-effort at Session granularity** — non-emptiness is the promise, exact ratios
  are not, and the tool says so out loud when it repairs a split.
- **Images state measurements, never verdicts.** Fixed absolute scales mean an image can never
  contradict a quality flag — a quiet recording looks quiet.

## Stack

Chosen for a transparent, inspectable, no-ML-at-runtime pipeline:

| Concern | Choice |
| --- | --- |
| Environment & deps | `uv` (committed `uv.lock`), Python ≥ 3.13 |
| Lint & format | `ruff` |
| Types | `mypy --strict` (CI gate) |
| Tests | `pytest` |
| Audio I/O | `soundfile` |
| Resampling | `python-soxr` (`HQ`) |
| DSP & rendering | `numpy`, `scipy.signal`, `matplotlib` (Agg) |

No FFmpeg, no PyAV, no torch, no librosa. Layout is `src/`, with a single `pyproject.toml` and a
`hatchling` build backend — `uv sync` installs the package, and v0.1 runs as `sdw`.

## Decision record

| ADR | Decision |
| --- | --- |
| [0001](docs/adr/0001-identifier-scheme.md) | Identifier scheme |
| [0002](docs/adr/0002-stateless-data-in-data-out.md) | Stateless `--data-in` → `--data-out`, privacy, deletion |
| [0003](docs/adr/0003-storage-layout-naming-retention.md) | Storage layout, file naming, retention |
| [0004](docs/adr/0004-session-aware-splitting.md) | Session-aware splitting |
| [0005](docs/adr/0005-input-formats-and-normalization-target.md) | Input formats & normalization target |
| [0006](docs/adr/0006-output-manifest-format.md) | Output manifest format |
| [0007](docs/adr/0007-audio-validation-quality-checks.md) | Audio validation & quality checks |
| [0008](docs/adr/0008-testing-strategy-and-synthetic-fixtures.md) | Testing strategy & synthetic fixtures |
| [0009](docs/adr/0009-seed-example-data.md) | Seed / example data |
| [0010](docs/adr/0010-dataset-version-and-provenance.md) | Dataset version & provenance |
| [0011](docs/adr/0011-visualization-output.md) | Visualization output |
| [0012](docs/adr/0012-v0-1-acceptance-criteria.md) | v0.1 acceptance criteria |
| [0013](docs/adr/0013-recordings-csv-ingest-and-duplicate-resolution.md) | `recordings.csv` ingest & duplicate resolution |
| [0014](docs/adr/0014-build-backend-and-installed-entry-point.md) | Build backend & installed entry point |

Background research (library and convention surveys) lives on the local `research/*` branches.

## Implementing v0.1

[ADR-0012](docs/adr/0012-v0-1-acceptance-criteria.md) defines done. v0.1 ships when:

1. CI is green — `ruff`, `mypy --strict`, and the full ADR-0008 suite.
2. Three checks pass — the examples build, the privacy allowlist, and the audit recipe.
3. A human has walked `examples/README.md` once on a clean clone.
4. `v0.1.0` is tagged.

`examples/README.md` is specified but must be **written from observed output**, not from the spec —
which is why the manual gate exists.
