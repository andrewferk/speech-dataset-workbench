# The example dataset

> **The audio here is generated tones, not speech.** Every WAV under `data-in/` is a pure sine
> tone — no voice, no words. The `prompt_text` in `recordings.csv` is honest English so the
> columns look like real recordings, but nothing was spoken. This example teaches the *shape* of a
> dataset and exercises every mechanical stage — hashing, normalization, quality checks,
> session-aware splitting, manifest emission, image rendering — faithfully. It does **not**
> demonstrate transcription quality, because there is nothing to transcribe. See
> [ADR-0009](../docs/adr/0009-seed-example-data.md).

## Run it — one command, no downloads

The tree is committed, so there is nothing to fetch and nothing to record. This demo needs the
clone install — follow [Install](../README.md#install) in the top-level README to clone the repo and
run `uv sync`, which puts the `sdw` command in `.venv`. The standalone `uv tool install` path does
not package this example tree, so there is nothing to run there. Then, from the repo root:

```bash
sdw build --data-in examples/data-in --data-out /tmp/example-out
```

Without [mise](https://mise.jdx.dev) making `sdw` directly available, prefix it with `uv run` —
`uv run sdw build --data-in examples/data-in --data-out /tmp/example-out`. There is **no config
file** in this directory on purpose: the tool's defaults *are* the demo (80/10/10 split, the
−30 dBFS `low_volume` knob, and the rest). You supply a `--config` only when you want to change
them.

`build` prints nothing to stdout on success — it is a pure transform whose whole product is the
`--data-out` tree. The human-readable digest is written to `reports/summary.txt`. Read it:

```bash
cat /tmp/example-out/reports/summary.txt
```

## What you should see

The output below is transcribed from an actual run of the committed tree. **All four signals are
disclosures from a build that *worked*, not errors.** Read each before you meet it.

```
Quality: 12 recordings — 11 clean, 1 flagged
  clipping              0
  low_volume            1
  duration_out_of_range 0

Flagged:
  rec_2fb62f996acdb5b2 low_volume            active_rms=-36.00dBFS

split     target  realized
train  9.6 (80%)   6 (50%)
val    1.2 (10%)   3 (25%)
test   1.2 (10%)   3 (25%)

non-emptiness repair: moved session sess_a1 from train to test
  (≥3 Sessions → val & test must be non-empty; ratios are best-effort)

Speaker spk_a appears in train and test — test set is not speaker-independent
Speaker spk_b appears in train and val — val set is not speaker-independent
```

### 1. The configured 80/10/10 lands at a realized 6/3/3

The `split` table shows `train` **6 (50%)**, `val` **3 (25%)**, `test` **3 (25%)** against a target
of 9.6 / 1.2 / 1.2 — a wide miss from the configured 80/10/10. This is not a bug. Splitting is
**session-aware**: a Session is never torn across splits (otherwise the same Session leaks between
train and test, and any later evaluation is quietly meaningless). The demo has 4 Sessions of
3 Recordings each, and whole Sessions are indivisible, so 80/10/10 is simply *inexpressible* — the
tool lands on the nearest legal placement and reports both numbers. Ratios are best-effort; the
promise the tool actually keeps is non-emptiness, next.

### 2. The repair line

```
non-emptiness repair: moved session sess_a1 from train to test
```

With ≥3 Sessions, `val` and `test` must each receive at least one, or a downstream evaluation has
nothing to run on. The seeded placement would otherwise have left `test` empty, so the tool moved
one whole Session (`sess_a1`) out of `train` to satisfy that guarantee — and **says so out loud**
rather than shipping a silently broken split. (This repair is a fact about 4-Session input sets,
discovered, not something the demo was designed to trigger.)

### 3. The speaker-overlap note

```
Speaker spk_a appears in train and test — test set is not speaker-independent
Speaker spk_b appears in train and val — val set is not speaker-independent
```

Disjointness is **Session-level, not Speaker-level**: the same *Speaker* may appear on both sides of
a Split as long as no *Session* does. With only 2 Speakers across 4 Sessions that overlap is
unavoidable, so the tool flags it — report-only, exit code unaffected — so you understand exactly
what kind of independence your Splits do and don't have.

### 4. The one `low_volume` flag — the flagged Sample is still in the Manifest

```
  rec_2fb62f996acdb5b2 low_volume            active_rms=-36.00dBFS
```

One Recording (`spk_b/sess_b1/b1_02.wav`, "I moved too far from the microphone on this one") was
generated at −36 dBFS, below the −30 dBFS knob, so it is flagged `low_volume`. Crucially, it is
**included and flagged, never dropped** — quality flags are advisory metadata, and *all attempts are
data*. You can confirm the flagged Sample is still in the Manifest:

```bash
grep rec_2fb62f996acdb5b2 /tmp/example-out/val.jsonl
```

It lands in the `val` Split with its full metadata and `content_hash`. The only things that
hard-abort a build are structural — a file that won't parse, resolve, or decode — never a quality
flag.

### Preflight without writing anything

`validate` runs the same checking engine read-only (it writes nothing, anywhere) and prints just the
Quality digest — the first block above. It exits `0` if and only if a subsequent `build` would clear
every check that reads `--data-in` or `--config`, so it is a trustworthy CI gate for the input. A
merely-flagged Recording still exits `0`:

```bash
sdw validate --data-in examples/data-in
```

## Bring your own recordings

The demo `recordings.csv` **is** the template — there is no separate prompts file to keep in sync.
To point the tool at your own recordings:

1. **Copy the tree elsewhere** so your captures never touch this repo (audio lives only in external
   `--data-in` / `--data-out` directories — that is how privacy is architectural, not a gitignore
   rule):
   ```bash
   cp -r examples/data-in ~/my-recordings
   ```
2. **Replace the WAVs with your own.** Input is **WAV only** (PCM). Arrange them under any
   subdirectory layout you like — the tool imposes no structure; only the `path` column matters.
3. **Edit `recordings.csv`.** Keep the six columns
   (`path,speaker_id,session_id,prompt_text,device,environment`) and rewrite the rows: `path` is a
   POSIX path relative to the `--data-in` root (absolute paths and `..`-escapes are rejected), and
   `speaker_id` / `session_id` / `prompt_text` describe each Recording. Files you don't list are silently
   ignored, so `--data-in` can stay your own external drop.
4. **Run `validate` first**, before any build:
   ```bash
   sdw validate --data-in ~/my-recordings
   ```
   A green preflight means `build` will not hard-error on your input or your config. Then build for
   real:
   ```bash
   sdw build --data-in ~/my-recordings --data-out ~/my-dataset
   ```

Aim for **at least 3 Sessions** so `val` and `test` are non-empty, and spread each Speaker's
Recordings across several Sessions if you want more balanced Splits than the demo can manage.
