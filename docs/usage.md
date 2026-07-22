# Usage

The reference for `sdw`: the input contract, both commands, every config key, and how to read what
a build emits.

This assumes you have already run the tool once. If you have not, start with
[the example dataset](../examples/README.md) — it walks one committed dataset end to end and tells
you what you will see. This page answers the question you have *after* that: what are my options,
now that I am pointing it at my own recordings.

For verifying a built dataset's `dataset_version` from `--data-out` alone, see
[auditing](auditing.md).

## The input: `--data-in`

`--data-in` is a directory you author and the tool only ever reads. It holds:

- **`recordings.csv`** at the root. The name is fixed and not configurable.
- **The Originals**, in any subdirectory layout you like. The CSV is the authority on which files
  make up the dataset; anything under `--data-in` that the CSV does not list is **silently
  ignored**, with no warning. There is nothing to clean up before a run.

Originals must be **PCM WAV** — a `WAV`, `WAVEX`, or `RF64` container carrying a `PCM_*` encoding.
Sample rate, bit depth, and channel count are free; the tool downmixes to mono and resamples to
16 kHz itself. A FLAC, an MP3, a float WAV, or an MP3-in-a-WAV is rejected even if the filename says
`.wav`.

### The `recordings.csv` contract

Six columns, and the set must match **exactly** — a missing column or an extra one is a hard error.
Column *order* in the file is free.

| Column | What it means |
| --- | --- |
| `path` | Where the Original is, relative to `--data-in`, POSIX-separated. |
| `speaker_id` | Who spoke. Your label; the tool never interprets it beyond reporting split overlap. |
| `session_id` | The sitting this recording belongs to. **This is the split unit** — see [`[split]`](#split). |
| `prompt_text` | What they were asked to say. Emitted verbatim as the manifest's `text`. |
| `device` | Capture device. Free text, carried into the manifest. |
| `environment` | Capture environment. Free text, carried into the manifest. |

`path` is validated before anything is read:

- **Empty** → rejected.
- **Absolute** (`/home/me/take1.wav`) → rejected.
- **Containing a `..` component** → rejected.
- **Containing a backslash** → rejected, as not POSIX and not portable.
- **Not on disk** → rejected.

The first three exist so a `--data-in` directory is self-contained: it can be moved or handed to
someone else and still resolve.

Every column is required on every row. A row with more or fewer fields than the header declares is a
hard error, as is a header with no rows at all.

#### Duplicate Originals

A Recording's identity is the **bytes of its Original**, not its row. Two rows whose files are
byte-identical collapse into one Recording — the same `recording_id`, one audio file, one manifest
line.

If those two rows **disagree** on `speaker_id`, `session_id`, `prompt_text`, `device`, or
`environment`, the run **aborts**: one audio file cannot carry two conflicting manifest lines, and
silently picking one would be a guess. `path` is excluded from that check — two different paths to
identical bytes is exactly the collapse case, not a conflict.

Prompts deduplicate the same way, on the text: `prompt_id` is derived from `prompt_text` after
Unicode NFC normalization, trimming, and whitespace collapsing. There is no case or punctuation
folding, so `"Hello."` and `"hello"` are two different Prompts.

## Commands

Two commands, three flags between them. A subcommand is required.

```
sdw build    --data-in DIR --data-out DIR [--config FILE]
sdw validate --data-in DIR               [--config FILE]
```

`python -m sdw` reaches the same parser and reports itself as `sdw`.

### `sdw build`

| Flag | Required | Meaning |
| --- | --- | --- |
| `--data-in` | yes | The input directory. Read-only. |
| `--data-out` | yes | The output directory. **Replaced wholesale.** |
| `--config` | no | A TOML file overriding the defaults. |

Runs the whole pipeline and writes [the output tree](#the-output-data-out).

**`build` prints nothing on success** — zero bytes to stdout and zero to stderr. The tree is its
entire product; the human digest goes to `reports/summary.txt`.

`--data-out` is replaced, not merged: there is no per-file pruning and no deletion command. To drop
a recording, remove its row from `recordings.csv` and rebuild. The replacement is atomic — the tree
is built in a sibling `<data-out>.tmp` and swapped in by rename, so an abort at any stage leaves the
previous `--data-out` exactly as it was, and a build is never visible half-finished.
`<data-out>.tmp` and `<data-out>.old` are the tool's own scratch siblings; a leftover one is debris
from a crashed run and is cleared at the start of the next.

### `sdw validate`

| Flag | Required | Meaning |
| --- | --- | --- |
| `--data-in` | yes | The input directory. Read-only. |
| `--config` | no | A TOML file overriding the defaults. |

Runs the input-facing half of the pipeline — config loading, `recordings.csv` ingest, decoding
every Original, and measuring quality — then **prints the quality digest to stdout and writes
nothing, anywhere**. There is no `--data-out`, and no file is created even temporarily.

The digest it prints is rendered by the same code that produces the quality section of
`reports/summary.txt`, so the two commands can never describe one input differently.
`summary.txt` additionally carries the split table, repair disclosures, and speaker-overlap notes —
`validate` never runs the splitter, so it has nothing to say about them.

**A flag never fails `validate`.** Flags are advisory; a run of nothing but clipped, near-silent
recordings still exits `0`.

**What a green `validate` covers:** every structural problem with the *input* — the config, the
split ratios, the CSV, the paths, the duplicate-metadata conflict, and the decode gate. Two hard
errors are outside its reach because they belong to stages it deliberately never runs: `--data-out`
existing as something other than a directory, and a failure rendering a specific recording's images.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | A hard error. The run aborted; no durable output. The message goes to **stderr**, prefixed `error: `. |
| `2` | A usage error — an unknown flag, a bad subcommand, a missing required flag. argparse's own message and exit. |

## Configuration

`--config` is optional. Every knob has a default, and the defaults are a working configuration —
you supply a file only to change something.

Three sections. **An unknown section, an unknown key, or a value of the wrong type is a hard
error**, not a warning and not a silent ignore. A typo aborts the run rather than quietly dropping
out of the effective config — which matters because the effective config is hashed into
`dataset_version`, and a silently-ignored knob would produce a dataset whose identity claims a
setting it did not use.

A full config, with every key at its default:

```toml
[manifest]
# lang is unset by default

[quality]
silence_threshold_dbfs = -40.0
low_volume_rms_dbfs = -30.0
duration_min_s = 0.5
duration_max_s = 20.0

[split]
seed = 0
train = 0.8
val = 0.1
test = 0.1
```

### `[manifest]`

| Key | Type | Default | Effect |
| --- | --- | --- | --- |
| `lang` | ISO 639-1 code | *unset* → `null` | Written to every manifest line's `lang` field. Nothing else reads it. |

The format check is exactly two lowercase ASCII letters, so `en` is accepted and `EN`, `eng`, and
`english` are rejected. It is a format check, not a registry lookup — an unassigned two-letter code
will pass.

### `[quality]`

All four are thresholds. **None of them changes the audio, and none can drop a recording** — they
move where a measurement crosses into an advisory flag.

| Key | Type | Default | Effect |
| --- | --- | --- | --- |
| `silence_threshold_dbfs` | float | `-40.0` | The level below which a 20 ms frame counts as silent. Moves the reported `leading_silence_s`, `trailing_silence_s`, and `silence_ratio`, and the active window `active_rms_dbfs` is measured over. **Raises no flag.** |
| `low_volume_rms_dbfs` | float | `-30.0` | A recording whose `active_rms_dbfs` falls below this is flagged `low_volume`. |
| `duration_min_s` | float | `0.5` | A recording shorter than this is flagged `duration_out_of_range`. |
| `duration_max_s` | float | `20.0` | A recording longer than this is flagged `duration_out_of_range`. |

What a check *means* is fixed and not configurable — only where its threshold sits. The clip
definition (three or more consecutive samples at or above 0.99 full scale), the 20 ms silence frame,
the 0.2 s guard on leading and trailing silence runs, and the −120 dBFS floor are constants. Two
configs can therefore never disagree about what "clipped" means while producing dataset versions
that look interchangeable.

There is no knob for clipping: `clipping` trips whenever `clip_ratio` is greater than zero.

### `[split]`

| Key | Type | Default | Effect |
| --- | --- | --- | --- |
| `seed` | int | `0` | Seeds the deterministic Session ordering, via `sha256("<seed>:<session_id>")`. No RNG is involved. Changing it reshuffles which Session lands where. |
| `train` | float | `0.8` | Target share of **samples**, not of sessions. |
| `val` | float | `0.1` | Target share of samples. |
| `test` | float | `0.1` | Target share of samples. |

Each ratio must be **greater than zero** — there is no two-way or `test = 0` mode — and the three
must sum to `1.0` within `1e-9`. Both rules are checked when the config loads, not when the splitter
runs, so `validate` catches an illegal ratio even though it never splits.

**The split unit is the Session and that is not configurable.** A whole session lands in exactly one
split, so a prompt re-read within one sitting can never straddle train and test. Because sessions are
indivisible, the ratios are **best-effort targets**: a configured 80/10/10 over a handful of sessions
will land somewhere else, and `reports/summary.txt` always prints the target beside the realized
count so you can read that as arithmetic rather than as a bug.

Two consequences worth knowing before you tune ratios:

- At **three or more** sessions, `val` and `test` are guaranteed non-empty; the splitter moves a
  session from a surplus split if it has to, and discloses every such move.
- Below three sessions a three-way split is arithmetically impossible. The build does not abort — it
  assigns what it can, emits valid empty split files, and prints a warning saying so.

The grouping guarantee is session-level, **not** speaker-level. A speaker recurring across splits is
expected and is reported as a disclosure, never repaired.

### The sections that deliberately do not exist

There is no `[normalize]` section and no `[images]` section, and this is a design decision, not an
omission.

Normalization's parameters — mono, 16 kHz, 16-bit PCM, mean downmix, the soxr HQ resampler — and the
image rendering parameters are fixed constants. Both feed `dataset_version` through the tool version
rather than through the config. If either were configurable, two runs could produce byte-identical
manifests under different settings and claim the same dataset identity, or mint a new identity for a
dataset a consumer cannot distinguish. Changing any of them is a change to the tool, and a new tool
version, not a per-run option.

Neither is silently ignored: a `[normalize]` or `[images]` table in your config aborts the run.

## The output: `--data-out`

```
<data-out>/
  dataset.json                            identity + provenance; written last
  train.jsonl                             canonical manifest, one JSON object per sample
  val.jsonl
  test.jsonl
  audio/
    train/
      metadata.jsonl                      the Hugging Face `audiofolder` view of this split
      <recording_id>.wav                  normalized: mono, 16 kHz, 16-bit PCM
    val/   …
    test/  …
  images/
    <recording_id>.waveform.png
    <recording_id>.spectrogram.png
  reports/
    quality.jsonl                         one line per recording, machine-readable
    summary.txt                           the operator's digest
```

### Who consumes what

**`<split>.jsonl` — NeMo, and anything else that reads a JSONL manifest.** One object per sample,
with `audio_filepath`, `duration`, and `text` as the NeMo-required subset, plus every other field
below. All three files are always emitted, empty ones included, so a consumer opening `test.jsonl`
on a dataset too small to fill test reads zero samples instead of crashing on a missing file.

Fifteen fields, in fixed key order:

| Field | Notes |
| --- | --- |
| `id` | The `recording_id` — `rec_` + 16 hex of the sha256 over the Original's bytes. |
| `audio_filepath` | `audio/<split>/<recording_id>.wav`, relative to `--data-out`. |
| `duration` | Seconds of the *normalized* audio, from the frame count, rounded to milliseconds. |
| `text` | `prompt_text` **verbatim** — the normalization behind `prompt_id` never reaches this. |
| `perceived_text` | Always `null`. The slot for what was actually said, as distinct from what was prompted; nothing collects it. |
| `prompt_id` | `prm_` + 16 hex over the normalized prompt text. |
| `speaker_id`, `session_id`, `device`, `environment` | Carried from the CSV. |
| `sample_rate` | `16000`. Describes the emitted WAV, not the Original. |
| `num_channels` | `1`. Likewise. |
| `content_hash` | `sha256:` + the full 64 hex over the Original's bytes. The Original's native format stays recoverable through this. |
| `lang` | `[manifest].lang`, or `null`. |
| `split` | `train`, `val`, or `test`. |

**The manifest carries no quality fields.** Flags are the operator's diagnostics and they live in
`reports/`. Keeping them out means a downstream consumer's schema does not change shape when the
tool's advisory vocabulary does.

**`audio/<split>/metadata.jsonl` — Hugging Face `audiofolder`.** The same samples, with two
mechanical differences: `audio_filepath` becomes a bare `file_name` (the metadata sits beside the
audio), and `split` is dropped (the folder *is* the split). Emitted only for splits that have audio,
since a metadata file describing an absent folder would point at nothing. `val` is already what HF
reads as a validation split, so no split is renamed.

**`audio/<split>/*.wav`** — the normalized audio, bucketed by split so `ls audio/test/` answers what
is in test without parsing a manifest. Nothing here changes a level: no gain, no loudness
normalization, no dither. The levels the quality checks report are the levels that were recorded.

**`images/`** — two PNGs per recording, a waveform and a spectrogram, at a fixed scale. They state
measurements and never verdicts: no flag appears in an image, and nothing in them is recomputed from
the samples independently of the quality stage.

**`dataset.json`** — the dataset's identity and the record that explains it. Written **last**, as
the completeness sentinel: a tree without it is a build that did not finish. Eight top-level blocks:

| Block | Contents |
| --- | --- |
| `manifest_version` | The emitted schema's version — currently `"0.1"`. Distinct from the tool version. |
| `tool_version` | The `sdw` version that built this. Feeds `dataset_version`. |
| `dataset_version` | `sha256:` + 64 hex. The content-derived identity. |
| `config` | The **effective** config — every knob resolved, defaults materialized. These exact bytes feed `dataset_version`. |
| `normalization` | Self-description: sample rate, channels, encoding, downmix, resampler. |
| `hashing` | Self-description: the recipe behind each id, in prose. |
| `split.counts` | Realized sample counts per split, plus the total. Realized, not configured — the configured ratios live under `config`. |
| `sessions` | One entry per session — `session_id`, its `split`, and `num_samples` — sorted by id. |

`dataset_version` is recomputable from `--data-out` alone; see [auditing](auditing.md) for the
recipe.

## Reading the reports

### `reports/summary.txt`

The operator's digest — the quality section, then the split section. It is written on every build
and is deterministic: no wall-clock, no host facts, so two runs of the same input produce
byte-identical text.

The quality section is a fixed-shape tally followed by a list:

```
Quality: N recordings — N clean, N flagged
  clipping              N
  low_volume            N
  duration_out_of_range N

Flagged:
  <recording_id> <flag>  <the numbers that justify it>
```

All three flags are always listed, **even at zero** — a zero is itself the answer to "did anything
clip?", and a fixed shape means diffing two runs shows a count change rather than a line appearing.
The `Flagged:` block is the exception: it is omitted entirely when nothing is flagged. A recording
carrying two flags gets two lines, one per flag, because the evidence stated is per flag.

The split section always prints the configured target beside the realized count:

```
split      target   realized
train  T.T (NN%)  N (NN%)
val    T.T (NN%)  N (NN%)
test   T.T (NN%)  N (NN%)
```

The target is a fractional sample count with its configured percentage; the realized column is the
whole number of samples that actually landed there, with the percentage it works out to. Column
widths are computed from the content, so they stay aligned at any dataset size.

There is no threshold and no condition on this table — it appears on every build, so a gap between
target and realized reads as the arithmetic of indivisible sessions rather than as a fault. Below
it, when they apply:

- **`WARNING: N Session(s) …`** — fewer than three sessions, so val and/or test are empty by
  arithmetic. This one is printed in *both* sections, because it changes how each should be read.
- **`non-emptiness repair: moved session … from … to …`** — one line per move the splitter made to
  keep val and test non-empty. Omitted when there were none.
- **`Speaker … appears in train and test — test set is not speaker-independent`** — one line per
  speaker spanning splits. Omitted on single-speaker data, where the overlap is unavoidable and
  naming it would point at nothing you could act on.

### `reports/quality.jsonl`

One JSON object per **kept** recording — every recording, clean ones included — sorted by `id` and
joinable to the manifest on it.

Clean lines are present because this file is the *record* of what was measured, not a worklist: an
absent line could not distinguish "clean" from "never measured". `summary.txt` is the worklist, and
it is the one that omits them.

Each line carries the `id`, seven measurements, and the flags:

| Field | Unit | Meaning |
| --- | --- | --- |
| `duration_s` | seconds, 3 dp | Length of the normalized audio. |
| `peak_dbfs` | dBFS, 2 dp | Peak of the **Original**, across channels. |
| `clip_ratio` | ratio, 4 dp | Share of the Original's samples belonging to a clip run. |
| `active_rms_dbfs` | dBFS, 2 dp | RMS of the normalized audio over its active region — first to last non-silent frame. |
| `leading_silence_s` | seconds, 3 dp | Silence before the first active frame; `0.0` if under the 0.2 s guard. |
| `trailing_silence_s` | seconds, 3 dp | Silence after the last active frame; same guard. |
| `silence_ratio` | ratio, 4 dp | Share of frames measured as silent. |
| `flags` | list | Zero or more of `clipping`, `low_volume`, `duration_out_of_range`. Empty when clean. |

Clipping is measured on the **Original**, pre-resample; everything else on the normalized audio.
That asymmetry is deliberate: clipping is an artifact of the capture, and the downmix can average a
clipped channel away while the resampler smears the flat top — a post-resample clip metric is wrong
in both directions. The other metrics describe what the sample actually ships.

The dBFS convention is the raw `20*log10`, with no AES17 offset, so a full-scale sine reads about
−3 dBFS. Every number here is reproducible from the PCM by hand.

### What a flag means

**A flag is advisory. It never drops a recording, never fails a command, and never changes an exit
code.** Every recording that ingests successfully appears in a manifest, has audio written, has
images rendered, and is counted in a split — flagged or not.

The three flags:

| Flag | Trips when |
| --- | --- |
| `clipping` | `clip_ratio > 0` — at least one run of three or more consecutive Original samples at or above 0.99 full scale. |
| `low_volume` | `active_rms_dbfs` is below `[quality].low_volume_rms_dbfs`. |
| `duration_out_of_range` | `duration_s` is below `[quality].duration_min_s` or above `[quality].duration_max_s`. |

Silence raises no flag at all. A recording that opens with a breath and closes with a pause is
described, never flagged. A wholly silent recording is caught by `low_volume` instead — its active
region is empty, which floors `active_rms_dbfs`.

Filtering on flags is the consumer's decision, made by joining `quality.jsonl` to the manifest on
`id`. The tool records; it does not decide for you.
