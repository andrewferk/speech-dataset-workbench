# Audio validation & quality checks (v0.1)

We fix what the workbench measures about each Recording's audio, how it reports those measurements,
and — crucially — what it does *not* do with them. The checks are energy/amplitude thresholds
computed directly from PCM samples: **no model-based VAD, no auto-trimming, no gain change**. This
ADR builds on ADR-0002 (stateless transform), ADR-0003 (report file locations), ADR-0005
(normalization target & the decode/ingest boundary), ADR-0006 (manifest — which carries no quality
fields), issue #8 (failure policy & the `validate`/`build` commands), and research #6 (quality-metric
conventions); it resolves research #6's six open sub-choices. It does not reopen the ingest boundary
(ADR-0005/#11 owns decode/format/zero-frame as hard aborts).

## Decisions

### Outcome model — two outcomes, no third state

A file has exactly two possible fates:

- **Abort** — a *structural* failure (decode-fail / non-WAV / zero-frame) aborts the whole build with
  a non-zero exit and **no durable output**. This is owned by ADR-0005/#11, not by these checks.
- **Include and flag** — anything that decodes becomes a Sample, carrying zero or more **advisory**
  quality flags.

There is **no exclusion and no quarantine** — not even for pathological durations (a 0.1 s blip or a
10-minute runaway is a flagged Sample, never dropped). This preserves the "all attempts are data"
invariant and keeps the manifest a total function of what decoded. Quality flags are metadata a
**downstream consumer** may filter on; the workbench itself never filters, moves, or deletes a
Recording for a quality flag. An operator curates by editing `recordings.csv` and rebuilding, not by
trusting the tool to silently discard.

### What is measured, and on which audio

Clipping is measured on the **Original** (decoded to float64, *before* normalization's downmix/resample);
the other three are measured on the **Normalized** (mono · 16 kHz · 16-bit PCM). Clipping is a
flat-top artifact of the capture, and soxr `HQ` resampling smears those runs and can introduce
ringing overshoot — so post-resample clip detection is systematically unreliable (false-negative on
erased runs, false-positive on overshoot). Clipping is therefore tapped off the Original float samples
that normalization already reads (ADR-0005: "read → float64") as its first step — not a second decode.
The other three metrics describe what the Sample actually ships and are uniform on the Normalized.

| Check | Audio | Metrics | Flag |
|---|---|---|---|
| Clipping | **Original** floats (pre-resample) | `peak_dbfs`, `clip_ratio` | `clipping` |
| Leading/trailing/overall silence | Normalized | `leading_silence_s`, `trailing_silence_s`, `silence_ratio` | **none — report-only** |
| Low volume | Normalized, active region | `active_rms_dbfs` | `low_volume` |
| Duration sanity | Normalized | `duration_s` | `duration_out_of_range` |

### Metric definitions & fixed conventions

Work in normalized floats `s[n] = x[n] / FS` so `s[n] ∈ [-1, 1)`.

- **RMS dBFS** = raw `20·log10(√mean(s²))` — **no AES17 offset** (a full-scale sine reads ≈ −3 dBFS).
  The literal formula, reproducible from the PCM by hand. `log10(0)` clamps to a **−120 dBFS** floor.
- **Clipping.** A *clip run* = **≥ 3 consecutive** samples with `|s| ≥ 0.99` (full scale; the 0.99
  tolerance catches ADCs that saturate a code or two below max, and applies uniformly across any
  Original bit depth once decoded to float). `clip_ratio` = (count of samples belonging to any clip
  run) ÷ N. `peak_dbfs` = `20·log10(max|s|)`. The `clipping` flag trips when `clip_ratio > 0`. This
  is FFmpeg's "Flat_factor > 0 and Peak_count > 2" heuristic. Sample peak only (no true-peak /
  oversampling).
  - **Multi-channel Originals:** clipping is evaluated **per channel** (runs are within a channel).
    The flag trips if **any** channel has a clip run; `peak_dbfs` = max across channels; `clip_ratio`
    = union clip-sample count ÷ (N × channels).
- **Silence.** The Normalized signal is framed into **20 ms non-overlapping** frames (320 samples at
  16 kHz; a trailing partial frame folds into the last frame). A frame is silent when
  `frame_rms_dBFS < silence_threshold_dbfs`. A **`D_min = 0.2 s` minimum-duration guard** applies to
  the leading and trailing runs so natural pauses aren't counted. `leading_silence_s` = initial
  silent run, `trailing_silence_s` = final silent run, `silence_ratio` = silent frames ÷ total
  frames. **All three are report-only metrics — silence raises no flag.**
- **Low volume.** `active_rms_dbfs` = raw RMS dBFS over the **active region** (first to last
  non-silent frame, reusing the silence detector) — a *measurement* trim only, the audio is never
  trimmed. A wholly-silent Recording has no active frames → `active_rms_dbfs` = the −120 floor,
  which correctly trips `low_volume`. The `low_volume` flag trips when
  `active_rms_dbfs < low_volume_rms_dbfs`.
- **Duration sanity.** `duration_s` = `num_frames / 16000` from the Normalized. The
  `duration_out_of_range` flag trips when `duration_s < duration_min_s` or `> duration_max_s`.

### Fixed constants vs. config knobs

Level/taste thresholds are operator knobs; anything that defines what a check *means* is a fixed
constant (so two configs cannot disagree on what "clipped" means while producing
indistinguishable `dataset_version`s).

**Fixed constants** (this ADR, not configurable): RMS = raw `20·log10`, −120 dBFS floor; silence
frame = 20 ms non-overlapping, `D_min = 0.2 s`; clipping run length `N = 3`, `T_clip = 0.99` FS;
clipping per-channel-any.

**Config — the 4-knob `[quality]` section** (tool defaults below; `--config` TOML overrides; the
effective values fold into `dataset_version` per #8):

```toml
[quality]
silence_threshold_dbfs = -40.0   # T_sil: frame RMS below this = silent
low_volume_rms_dbfs    = -30.0   # active-region RMS below this = low_volume flag
duration_min_s         = 0.5     # duration_out_of_range if below
duration_max_s         = 20.0    # duration_out_of_range if above
```

### Flag vocabulary — exactly three

`clipping`, `low_volume`, `duration_out_of_range`. Silence contributes metrics only. "Malformed /
decode failure" is not a flag here — it is ADR-0005/#11's hard abort.

### Where results are recorded

- **`reports/quality.jsonl`** (written by `build`) — **one row per kept Recording** (clean rows
  included). Fixed key order, sorted by `id`, deterministic (no timestamps/host), rounding: dBFS
  2 dp / ratios 4 dp / seconds 3 dp. `flags` is an array of tripped flag names; `[]` = clean.

  ```json
  {"id":"rec_ab12cd34ef56gh78","duration_s":4.213,"peak_dbfs":-0.51,"clip_ratio":0.0,"active_rms_dbfs":-22.40,"leading_silence_s":0.340,"trailing_silence_s":0.120,"silence_ratio":0.0812,"flags":[]}
  ```

- **`reports/summary.txt`** (written by `build`, quality section) — the human **quality digest**: a
  per-flag tally plus one line per flagged Recording (clean ones omitted). Deterministic, no
  wall-clock.

  ```
  Quality: 42 recordings — 37 clean, 5 flagged
    clipping              2
    low_volume            3
    duration_out_of_range 1

  Flagged:
    rec_0a1b… clipping              peak=-0.02dBFS clip_ratio=0.0031
    rec_3c4d… low_volume            active_rms=-33.8dBFS
    rec_7e8f… duration_out_of_range duration=0.31s
  ```

- **`validate --data-in`** — prints that same digest to **stdout**, writes nothing durable, and
  **exits 0 even when Recordings are flagged** (quality flags never hard-error). `validate` is
  non-zero only on a structural (#11) or split (#10) failure. Machine-readable per-Recording data
  comes from running `build` and reading `quality.jsonl`.

The manifest (ADR-0006) carries **no** quality fields; quality lives only in `quality.jsonl`,
joinable on `id`.

## Consequences

- Quality is purely descriptive in v0.1 — the tool measures and reports, the operator and any
  downstream consumer decide. No stage of the pipeline branches on a quality flag.
- Clipping's Original-vs-Normalized split means clip detection reads the pre-resample floats; the
  other checks read the mono Normalized. This is a measurement tap, not extra I/O.
- The 4-knob `[quality]` config participates in `dataset_version`, so changing a threshold yields a
  new Version — consistent with #8's determinism contract.

## Rejected alternatives

- **A quarantine/exclude state** — rejected; breaks "all attempts are data" and makes the manifest a
  non-total function of the input.
- **AES17 +3.01 dB RMS convention** — rejected; the offset is a sine-calibration convenience we don't
  need and it hides math from an inspector.
- **Peak-based silence** — rejected; too sensitive to transients. Per-frame RMS is smoother.
- **LUFS (BS.1770) for low volume** — rejected; K-weighting + gating is opaque and heavy for a coarse
  "did the mic level collapse" check. Raw RMS is reproducible by hand.
- **Clip detection on the Normalized** — rejected; soxr resampling smears flat-top runs and adds
  overshoot, making post-resample clip metrics systematically wrong.
- **A `mostly_silent` / silence flag** — rejected; needs a 5th threshold, and a near-empty capture
  already trips `low_volume` and exposes `silence_ratio` for a consumer to filter on.
- **A second decode path (stdlib `wave`) for validation** — rejected; ADR-0005 already fixes
  `soundfile`/libsndfile as the one decoder and #11 owns decode failure.
