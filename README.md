# Speech Dataset Workbench

A local-first, CLI-only tool that turns a collection of **prompted** speech recordings into a
validated, reproducible, versioned dataset with an HF/NeMo-friendly manifest.

## Why this exists

The longer-term goal is a product that helps people with atypical or difficult-to-understand speech
communicate, likely via speech-recognition models adapted to an individual speaker. Before
attempting model fine-tuning or a mobile app, this workbench builds the reusable data
infrastructure those experiments need.

It is also a deliberate **learning project** — modern Python, digital audio, speech dataset design,
and the HF/NeMo ecosystem. That goal shaped the scope: the work lives where the learning is.

## What it does

One `sdw build` turns an input directory of recordings into a complete dataset, in a single atomic
pass:

1. **Parse** the operator-authored `recordings.csv` index.
2. **Resolve & decode** every referenced Original (PCM WAV only).
3. **Normalize** to mono · 16 kHz · 16-bit PCM WAV, deterministically.
4. **Measure quality** — energy/amplitude metrics per recording, against the normalized audio;
   clipping is the exception, tapped off the decoded Original before the downmix and resample
   ([ADR-0007](docs/adr/0007-audio-validation-quality-checks.md)).
5. **Split** into train/validation/test, session-aware.
6. **Emit** per-split manifests, a `dataset.json` descriptor, waveform + spectrogram PNGs, and
   quality reports.

The input is a fixed `recordings.csv` at the root of `--data-in`, one row per Original —
hand-authorable in a spreadsheet:

```csv
path,speaker_id,session_id,prompt_text,device,environment
session-a/take-01.wav,spk_ak,ses_a,"Hello, how are you?",shure-sm7b,quiet-room
```

`path` is a POSIX path relative to the `--data-in` root; absolute paths and `..`-escapes are
rejected. Files not referenced by the CSV are silently ignored. The full contract — every column,
every way a row aborts the build, and how byte-identical Originals collapse — is in
[`docs/usage.md`](docs/usage.md).

The tool manages **no state of its own**. A build is a pure function of `--data-in` plus the
effective config and tool version: `--data-in` is external and read-only, `--data-out` is external
and fully regenerable. Originals are never copied, moved, or modified. `--data-out` holds exactly
one build and is replaced wholesale each run via an atomic staging swap — an aborted build leaves it
untouched. There is no `init`, `import`, or `delete` command: deleting a recording means removing
its file from `--data-in` and rebuilding
([ADR-0002](docs/adr/0002-stateless-data-in-data-out.md)).

## Install

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/). There are two paths, and they are for
different things.

**To run it on your own recordings** — install the tagged release as a standalone tool:

```bash
uv tool install git+https://github.com/andrewferk/speech-dataset-workbench@v0.1.0
```

That puts `sdw` on your PATH (run `uv tool update-shell` if uv warns that its bin directory is not
there). Two things to know about this path: dependencies are resolved fresh rather than from the
committed `uv.lock`, and the example data is **not** packaged — there is no demo to run here, so
bring your own WAVs.

**To run the demo, or to work on the tool** — clone and sync:

```bash
git clone https://github.com/andrewferk/speech-dataset-workbench
cd speech-dataset-workbench
uv sync
```

`uv sync` installs the package into `.venv` from the locked dependency set, so `sdw` and `pytest`
run as written under [mise](https://mise.jdx.dev), which points `python` at that venv. Without mise,
prefix them with `uv run` to select the same interpreter:

```bash
uv run sdw validate --data-in examples/data-in
```

Nothing needs `PYTHONPATH` set — not `pytest`, not CI, not you. From here,
[`examples/README.md`](examples/README.md) walks a committed example dataset end to end.

## Commands

Two commands, sharing one checking engine so they can never disagree:

```bash
sdw build    --data-in DIR --data-out DIR [--config FILE]
sdw validate --data-in DIR               [--config FILE]
```

`build` runs the full pass and prints nothing on success — its entire product is the tree.
`validate` is a read-only preflight: it runs every check that reads the input, prints the quality
digest to stdout, and writes nothing, anywhere.

`validate` exits `0` **if and only if** a subsequent `build` would clear every check that reads
`--data-in` or `--config` — the only hard errors outside its reach are a `--data-out` that is not a
directory and a failed image render.

| Exit code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Hard error — aborted, no durable output; the message goes to stderr as `error: …`. |
| `2` | Usage error — an unknown flag, a bad subcommand, or a missing required flag. |

All tuning lives in an optional TOML config rather than per-parameter flags, so the CLI stays at
three flags. Nine keys across `[manifest]`, `[quality]`, and `[split]`; an unknown section or key is
a hard error rather than a silent no-op. Every key, its default, and its effect are documented in
[`docs/usage.md`](docs/usage.md).

`python -m sdw` is equivalent to `sdw` and reaches the same parser, wherever the venv's interpreter
does ([ADR-0014](docs/adr/0014-build-backend-and-installed-entry-point.md)).

If you have not run either command before, [`examples/README.md`](examples/README.md) walks both
against the committed example dataset; [`docs/usage.md`](docs/usage.md) is the reference to reach
for once you are pointing them at your own recordings.

## What you get

```
<data-out>/
  dataset.json              # identity + provenance; written last, as the completeness sentinel
  train.jsonl               # per-split manifests, NeMo-native
  val.jsonl
  test.jsonl
  audio/                    # normalized WAVs, bucketed by split
    train/
      metadata.jsonl        # the Hugging Face `audiofolder` view of this split
      <recording_id>.wav
    val/  test/  …
  images/                   # 2 per recording, keyed by recording_id
    <recording_id>.waveform.png
    <recording_id>.spectrogram.png
  reports/
    quality.jsonl           # one line per recording: all metrics + flags
    summary.txt             # human-readable build digest
```

The per-split manifests are a superset of NeMo's required keys (`audio_filepath`, `duration`,
`text`), so they are valid NeMo manifests with zero transformation; HF `audiofolder` reads the same
samples from the sidecar `metadata.jsonl` beside each split's audio. Every manifest field, every
`dataset.json` block, and both reports are documented in [`docs/usage.md`](docs/usage.md).

## What it does not do

The scope was narrowed hard, and these exclusions are design boundaries, not gaps:

- **No model ever runs.** No Whisper, no ASR baseline, no WER/CER. Nothing in the stack does
  inference.
- **No perceived-text collection and no annotation UI.** The tool stores *intended text* (the
  prompt). Every manifest line carries a `perceived_text` key — what a listener judges was actually
  said — and its value is always `null`: the dual-annotation slot is named in the schema, and
  nothing collects it.
- **No web UI.** CLI only; visualization is emitted as PNG files.
- **No DVC / experiment tracking.** Reproducibility is intrinsic — content hashes, a deterministic
  pipeline, and the manifest.
- **No auto-trimming and no VAD model.** Silence is measured and reported, never acted on.
- **No spontaneous speech, auth, multi-tenancy, cloud, or mobile.**

## The claims the design makes

- **Deterministic.** The same `--data-in` + config + tool version yields the same `dataset_version`
  and byte-identical artifacts. Re-running is a safe, byte-identical rewrite. Cross-*architecture*
  bit-exactness is explicitly **not** claimed — soxr's FFT denies it; reproducibility leans on
  content hashes plus pinned versions, and the pinning is `uv.lock`'s, which governs the clone
  install and not the standalone one.
- **`dataset_version` is recomputable from `--data-out` alone**, without the inputs — a `sha256`
  over the emitted manifest bytes, the effective config, and the tool version. The recipe is
  [`docs/auditing.md`](docs/auditing.md)
  ([ADR-0010](docs/adr/0010-dataset-version-and-provenance.md)); there is no `verify` command
  because the recipe is all it would be.
- **Privacy is architectural.** Captured audio never enters git because it lives only in the two
  external directories the repo never contains — not because a gitignore rule blocks it. Metadata
  is pseudonym-only, so the manifest is freely shareable.
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
`hatchling` build backend — `uv sync` installs the package, and it runs as `sdw`.

## Documentation

| Document | What it is for |
| --- | --- |
| [`examples/README.md`](examples/README.md) | The tutorial. Walks the committed example dataset end to end and tells you what you will see. |
| [`docs/usage.md`](docs/usage.md) | The reference. The input contract, both commands, every config key, and how to read what a build emits. |
| [`docs/architecture.md`](docs/architecture.md) | Orientation for someone about to change the code: the shape, the pipeline seam, where each concern lives. |
| [`docs/auditing.md`](docs/auditing.md) | How to recompute a build's `dataset_version` from `--data-out` alone. |
| [`docs/adr/README.md`](docs/adr/README.md) | The decision records — what was decided, and what was considered and rejected. |
| [`CONTEXT.md`](CONTEXT.md) | The glossary: the ubiquitous language this project and its docs use. |
