# Visualization output (v0.1)

We fix what the image stage of `build` renders, from which audio, with which parameters, and what it
refuses to do. The two PNGs per Recording are an **operator inspection aid** — a debugging surface for
a single technical user — not a dataset deliverable and not a consumer-facing artifact. This ADR
builds on ADR-0003 (which fixed image naming and location), ADR-0005 (normalization target &
within-arch determinism), ADR-0007 (quality metrics — whose computed values this stage consumes),
ADR-0008 (which handed down "the image stage must emit deterministic PNGs" as a hard constraint),
ADR-0010 (`dataset_version` preimage — which decides the config question), issue #8 (pipeline stages &
failure policy) and research #4 (library stack). It does not reopen image naming (ADR-0003) or the
manifest line (ADR-0006).

## Decisions

### The governing principle — the image states measurements, never verdicts

Every downstream choice follows from the audience: the reader is the operator, diagnosing one
Recording. That makes **diagnostic legibility** the objective, and it yields the invariant this ADR
is built on — **an image may state a measurement, but never a verdict**. The image stage therefore
reads **no `[quality]` threshold**, and stays decoupled from the quality stage's judgements even
while consuming its numbers.

The corollary, applied three times below: **an image may not contradict the flag.** A quiet recording
must *look* quiet in the waveform, *render dim* in the spectrogram, and *read low* in the title.

### Coverage — all Recordings, always

Every Recording gets both PNGs on every build. `images/` is a guaranteed **1:1 mirror of the
manifest** — exactly 2×N files, no lookup required, no dependence on the quality stage's output.

Rendering only flagged Recordings was rejected: it would make `images/` contents depend on
`[quality]` thresholds — a config knob with a filesystem side effect — and would leave you unable to
eyeball a recording that sounds wrong but tripped no flag. The corpus is small by design (prompted
speech; ~12 Recordings in `examples/`), so the cost of rendering everything is a non-issue.

### Source — both images render from the Normalized

Both render from the **Normalized** audio (mono · 16 kHz · 16-bit PCM). This aligns with three of
ADR-0007's four checks (silence, `low_volume`, duration are all measured there), and it is what a
consumer actually trains on. Mono means one waveform trace with no channel ambiguity; 16 kHz means a
fixed 8 kHz Nyquist, so **every spectrogram shares an axis and images are comparable**. ADR-0005
guarantees no gain change, so amplitude on the plot is still the true captured level.

**Known trade:** a `clipping`-flagged Recording renders from soxr-smeared audio, so its waveform will
not show crisp flat tops. The flag itself remains honest — ADR-0007 measures clipping on the Original
pre-resample for exactly this reason — but the *picture* is one resample removed from the *number*.
Rendering the waveform from the Original was rejected (see below).

### Waveform — fixed y, per-recording x

| Axis | Rule | Why |
|------|------|-----|
| **y** | **Fixed −1.0 .. +1.0**, always | Level is invisible unless the axis is fixed. Autoscale renders a −45 dBFS whisper and a −1 dBFS shout as the identical picture — the image would silently contradict `low_volume`, the single most common reason to open it. |
| **x** | **Per-recording, 0 .. duration** | Deliberately asymmetric with y: duration is *already* legible — a manifest field, a summary number, and its own flag — so nothing is hidden by fitting the axis. Also avoids coupling the image stage to `[quality].duration_max_s`. |

A fixed 0..`duration_max_s` window was rejected: the median prompted utterance would occupy a fifth
of the plot, and a threshold change would silently redraw every PNG.

### Spectrogram — ASR framing, absolute dB

STFT via `scipy.signal.ShortTimeFFT` on the Normalized:

| Parameter | Value | Why |
|-----------|-------|-----|
| `n_fft` | **400** (25 ms) | The Whisper/NeMo/Kaldi frontend framing — **what you read is what a v0.2 model eats**. |
| `hop` | **160** (10 ms) | 100 frames/sec; ample time resolution for speech. |
| window | **Hann** | Same convention. |
| output | 201 bins, **0 .. 8 kHz** | Fixed by the 16 kHz Normalized rate. |

Magnitude maps to colour as **absolute dBFS over a fixed −80 .. 0 window**, clamped, identical for
every image — reusing ADR-0007's raw `20·log10` convention and its −120 floor discipline. Same colour
therefore means same energy across any two spectrograms, and a quiet recording renders visibly dim.

Per-image normalization (dB relative to that file's own max — librosa's common default) was rejected:
it re-lies about level exactly as waveform autoscale does, and would put the spectrogram in direct
contradiction with the fixed-scale waveform sitting next to it.

### Annotation — numbers taken verbatim from the quality stage

The title carries `recording_id | speaker_id | session_id`, duration, and **peak / RMS dBFS**. Axis
labels state units. This makes the image self-contained — you read the level off it without opening
`quality.jsonl` — while stating only measurements.

The levels are **not recomputed**. The image stage receives the values the quality stage already
computed and renders them verbatim: **one measurement, two presentations**, which cannot disagree.
This matters because the two artifacts measure differently — ADR-0007 takes `peak_dbfs` on the
**Original** (pre-resample) and `low_volume` RMS over the **active region** (silence excluded).
Recomputing whole-file peak/RMS on the plotted Normalized signal would produce a title reading
`peak -3.2` beside a `quality.jsonl` reading `peak_dbfs: -3.0` — two artifacts disagreeing about one
recording, both correct, neither explained. The labels admit the gap: **`peak (orig)`** and
**`RMS (active)`**.

Rendering the quality **flags** was rejected — it would make the image stage depend on `[quality]`
thresholds, redraw every PNG on a threshold change, and duplicate a verdict into two artifacts that
can drift apart. Rendering the **prompt text** was rejected: arbitrary-length sentences force
wrapping/truncation and font-metric layout, the most determinism-hostile thing available.

### Constants, not config — there is no `[images]` section

Figure size, DPI, colormap, STFT params and dB range are **fixed constants in code**. This follows
ADR-0005's precedent, which chose fixed constants over a `[normalize]` section for the same reason.

The decisive argument is ADR-0010's: the `dataset_version` preimage hashes the **effective config**,
so **any** `[images]` key would fold into the dataset's identity. An `[images].dpi = 200` would mint a
new `dataset_version` for a dataset whose manifest bytes are byte-identical — re-rendering a picture
at a different size would change the identity of the data. That directly undermines what ADR-0010
bought. An `[images].enabled` switch fails identically, in miniature.

Changing a render constant changes `tool_version`, which *does* feed the preimage. Coarse, but
correct: it is a tool change, not a property of this dataset's configuration.

| Constant | Value |
|----------|-------|
| waveform figure | 10 × 3 in @ 100 DPI → **1000 × 300 px** |
| spectrogram figure | 10 × 4 in @ 100 DPI → **1000 × 400 px** (taller for the frequency axis + colorbar) |
| colormap | **`magma`** — perceptually uniform, colorblind-safe, greyscale-safe, the conventional dB-spectrogram map |
| dB range | **−80 .. 0 dBFS**, clamped |

Wide aspect suits a time series; 100 DPI keeps each PNG ~50–150 KB. Images live only in `--data-out`,
which is never committed (ADR-0002), so file size is a convenience concern, not a repo-budget one.

### Determinism — same-machine byte-identity, cross-machine accepted

ADR-0008 requires deterministic PNGs so its build-twice-and-diff test holds. The stage pins
everything it controls:

- **Agg** backend (headless).
- **Explicit rcParams via a style context** — insulating from any user `~/.matplotlib/matplotlibrc`,
  which would otherwise silently alter output on one machine and not another.
- **Fixed figsize + DPI** (above).
- **`savefig(..., metadata={"Software": None})`** — matplotlib's PNG writer embeds a
  `Software: Matplotlib version X` tEXt chunk by default. It writes no timestamp chunk.

**Cross-machine PNG byte-identity is explicitly not guaranteed and not sought.** Text is rasterized
through freetype, whose glyph rasterization varies by version. This is the same bargain ADR-0005
already struck for soxr WAVs and ADR-0008 codified by committing **no golden PNGs** — #14's test
builds twice on one machine, so same-machine identity satisfies it exactly. No new precedent is set,
and nothing needs the stronger property: ADR-0010 excludes images from `dataset_version` entirely.

Dropping all text to reach cross-machine bit-exactness was rejected — it would pay the whole
annotation spec for a property no test asserts. A bespoke numpy+zlib PNG writer was rejected as
re-implementing matplotlib badly.

### Failure — a render error aborts the build

A render failure is a **tool bug, not a property of the data**: every decoded Recording is renderable
by construction. It is therefore structural, per #8 — non-zero exit, staging directory discarded, **no
durable output** (ADR-0003's atomic commit delivers this for free).

This preserves the 1:1 invariant: no build ever emits a partial `images/`. Warn-and-skip was rejected
— it invents a third outcome in a pipeline that deliberately has exactly two, and a missing PNG
becomes indistinguishable from one never rendered. A `render_failed` quality flag was rejected:
ADR-0007 froze the flag vocabulary at exactly three, all describing *audio quality*; a tool-failure
flag is a category error in that field.

## Consequences

- **`validate` renders nothing.** #8 defines it as stages 1–4, read-only, stdout only; images are
  stage 5. `validate`'s exit code remains unaffected by the image stage.
- **The manifest gains no image fields.** Images are located by the `recording_id` stem (ADR-0003).
  Adding a field would change manifest bytes → change `dataset_version` (ADR-0010), reopening ADR-0006
  to serve a convention that already works.
- **Pipeline ordering constraint for implementation:** the quality stage computes peak/RMS **once**;
  the image stage consumes those values rather than recomputing. Consistent with #8's
  `normalize → validate → split → manifest → images → report`.
- **The image stage reads no config.** Its only inputs are the Normalized samples and the quality
  stage's computed metrics.
- Waveform, spectrogram, title, and `quality.jsonl` now all agree about level — the property the
  fixed y-axis, absolute dB scale, and verbatim-metrics decisions were each chosen to protect.
- `[quality]` thresholds no longer reach the image stage at all, so a threshold change redraws
  nothing.

## Rejected alternatives

- **Flagged-Recordings-only rendering** — rejected; makes `images/` contents a function of `[quality]`
  thresholds and hides recordings that sound wrong but tripped no flag.
- **Rendering from the Original** — rejected; Originals vary in rate and channel count, so the
  spectrogram's Nyquist would differ per recording (48 k → 24 kHz vs 16 k → 8 kHz), destroying
  comparability, and a stereo Original forces a downmix choice — at which point it isn't the Original.
- **Waveform from Original + spectrogram from Normalized** — rejected; two images of one Recording
  would depict different signals while appearing to align in time and amplitude.
- **Waveform y-autoscale** — rejected; hides level, the most common thing being inspected.
- **A zoomed autoscaled inset** — rejected; real render complexity and non-determinism surface for a
  second reading the spectrogram already gives.
- **Fixed 0..`duration_max_s` x-axis** — rejected; mostly whitespace, and couples images to a quality
  threshold.
- **Per-image dB normalization** — rejected; contradicts the fixed-scale waveform and re-hides level.
- **Rendering quality flags / clipped regions in red** — rejected; re-couples the image stage to
  thresholds and duplicates a verdict.
- **Rendering the prompt text** — rejected; wrapping/truncation and font metrics threaten determinism
  for a nice-to-have.
- **An `[images]` config section (any key, including `enabled`)** — rejected; would fold into the
  `dataset_version` preimage and mint new dataset identities for byte-identical manifests.
- **Cross-machine bit-exact PNGs via text removal** — rejected; sacrifices the spec for a property no
  test asserts and ADR-0010 doesn't need.
- **A bespoke PNG writer (numpy + zlib)** — rejected; hundreds of lines re-implementing matplotlib,
  against v0.1's avoid-premature-engineering principle.
- **Warn-and-skip on render failure** — rejected; invents a third outcome and breaks the 1:1 mirror.
