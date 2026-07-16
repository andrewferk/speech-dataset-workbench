# Supported input formats & the normalization target

We fix exactly which audio the workbench ingests and the precise procedure that turns an
**Original** into its **Normalized** derived audio (#11), because normalization is the first
`build` stage (#8): it produces the audio the quality checks (#6, #13), the splitter (#10,
ADR-0004), the manifest (#12) and the visualizations all stand on. This ADR builds on
ADR-0001 (identifiers), ADR-0002 (stateless `--data-in` → `--data-out`) and ADR-0003 (storage
layout); it consumes research #4 (audio-library landscape) and does not reopen those. It pins
the "exact procedure" that CONTEXT.md's **Normalized** entry defers to.

No model ever runs in this tool, and no loudness is altered, so the Normalized audio is a
faithful, format-canonicalized copy of the capture — every level the quality checks measure is
the level that was recorded.

## Decisions

### Accepted inputs — WAV (PCM) only

- v0.1 ingests **PCM WAV only**. This keeps the stack free of any FFmpeg/PyAV dependency
  (research #4: MP3 would ride libsndfile with no ffmpeg, but M4A/AAC forces FFmpeg; neither is
  worth widening v0.1's surface for a prompted-capture workbench whose operator controls export).
- **Decodability is the ingest gate.** A file listed in `recordings.csv` that is not WAV, or is
  a corrupt / truncated / zero-frame WAV that `soundfile` cannot decode, is a
  **hard/structural error → abort** (non-zero exit, no durable output — #8). *If it decodes, it
  is data; if it does not, the build aborts.*
- A file that **does** decode but is silent, clipped, too quiet, or out of the duration range is
  **not** an ingest error — it is a **soft quality flag** (included + flagged), owned by the
  validation/quality spec (#13). This is the clean line between #8's hard-abort policy and the
  report-only quality metrics of #6/#13.

### Canonical target — mono · 16 kHz · 16-bit PCM WAV

The Normalized target is **mono, 16 kHz, signed 16-bit PCM WAV** (`PCM_16`) — the near-universal
ASR/dataset convention (LibriSpeech, Common Voice, NeMo, HF `audiofolder`).

### Procedure (fixed; no config knobs)

```
1. read   → float64                         (soundfile)
2. downmix → arithmetic mean of all channels; already-mono passes through unchanged
3. resample → 16 kHz, python-soxr quality "HQ"   (skipped when the input is already 16 kHz)
4. write  → PCM_16, 16 kHz, mono             (soundfile / libsndfile)
```

- **Downmix = mean of channels.** Phase-preserving, standard. A dead channel makes the mean
  quieter, which the low-volume quality check (#6/#13) surfaces — it is not corrected here.
- **No loudness change / no gain.** "Normalization" means *format* normalization only. Quality
  metrics measure the true captured signal; consumers apply per-utterance loudness normalization
  at feature-extraction time. Baking an irreversible gain into the corpus is explicitly rejected.
- **No dithering.** Deterministic round-to-nearest quantization (libsndfile's default when writing
  float to `PCM_16`). Seeded dither would add pseudo-noise for no ASR benefit at 16-bit
  (quant-error floor ≈ −96 dBFS) and complicate determinism.
- **No `[normalize]` config section.** Every parameter above is a hard-coded constant. Changing
  any of them is a tool change (new tool version → new `dataset_version` per ADR-0001 / #2), not a
  per-run knob. This honors the project's narrow > broad preference.

### Library stack

`soundfile` (WAV I/O; bundled **LGPL** libsndfile), `python-soxr` quality `HQ` (resample; bundled
**LGPL** libsoxr — LGPL accepted), `numpy`. **Zero ffmpeg / PyAV.** `soundfile` is kept over
`scipy.io.wavfile` for exact frame counts (exact durations) and safer float handling; its LGPL
class is one we have already accepted via libsoxr.

### Determinism guarantees

- **Same input bytes + same tool version → byte-identical Normalized WAV** on a fixed
  platform/architecture.
- **Cross-architecture bit-exactness is not guaranteed.** `python-soxr` is FFT-based; results may
  differ by a few ULPs across FFT builds. Pure-FIR methods would be more portable but were not
  chosen (quality; see research #4).
- Reproducibility therefore rests on **pinned library versions + content hashes**, not on
  cross-machine bit-identity: `recording_id` / `content_hash` = sha256 of the **Original**
  (ADR-0001, ADR-0003), and `dataset_version` folds in the normalization constants via the tool
  version (ADR-0001 / #2).

This resolves research #4's three open questions: (1) **WAV-only** → drop ffmpeg entirely;
(2) **LGPL accepted** (libsndfile, libsoxr); (3) reproducibility = **pinned versions + content
hashes**, not cross-machine bit-exactness.

## Consequences

- **#13 (validation/quality spec)** inherits two boundaries: the ingest gate (decode-fail →
  abort; decoded-but-bad → soft flag) and the guarantee that quality metrics see **true**,
  un-gained levels.
- **#15 (seed / example data sourcing)** must supply example recordings **as WAV** — the WAV-only
  contract is now firm.
- **#12 (manifest)** carries `sample_rate = 16000`, `num_channels = 1` as constants for every
  Sample.
- CONTEXT.md's **Normalized** entry now points here for the exact procedure.

## Rejected alternatives

- **WAV + MP3 / + M4A ingest** — MP3 is free via libsndfile but adds a lossy-source caveat; M4A
  forces FFmpeg. Rejected: unjustified surface for a controlled-capture workbench.
- **`scipy.signal.resample_poly` (BSD)** — more portable, but below soxr `HQ` in quality; LGPL was
  acceptable, so quality won.
- **Peak- or loudness-normalization** — irreversible, and it would gut the clipping/low-volume
  quality checks by pegging every file's level. Rejected in favor of faithful capture.
- **Seeded dither; 24-bit / float32 output; a `[normalize]` config section** — all add complexity
  or surface for no v0.1 benefit.
