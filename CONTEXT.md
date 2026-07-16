# Speech Dataset Workbench

A local-first, CLI-only tool that turns a collection of **prompted** speech recordings into a
validated, reproducible, versioned dataset with an HF/NeMo-friendly manifest. This glossary is the
ubiquitous language for v0.1; it is a glossary only — no implementation details.

## Language

### Capture

**Speaker**:
A person whose voice is recorded. One human = one Speaker.
_Avoid_: User, talker, voice.

**Session**:
One continuous sitting in which a Speaker reads prompts under a single set of conditions
(one device, one environment). Re-reading the same prompts on another occasion is a new Session.
_Avoid_: Take, sitting, batch.

**Prompt**:
A unit of intended text presented to the Speaker to read aloud. The same text read across Sessions
is the same Prompt. In v0.1 the Prompt text *is* the intended transcript.
_Avoid_: Sentence, text, script, utterance.

**Recording**:
The atomic captured unit — one Speaker reading one Prompt in one Session, on a single attempt.
A Recording owns its audio artifacts (the Original and its Normalized/derived audio). Identity is
capture-oriented and independent of `(Session, Prompt)`, which is **not** unique.
_Avoid_: Clip, file, utterance, sample (a Sample is a distinct concept — see below).

**Attempt**:
The observation that several Recordings share the same `(Session, Prompt)` — e.g. a re-read after a
flub. In v0.1 **all attempts are data**; there is no "keeper" selection. Not a first-class entity,
just the ordinal that distinguishes sibling Recordings.
_Avoid_: Retake, keeper, candidate.

### Audio artifacts

**Original**:
The audio file exactly as captured, retained unmodified.
_Avoid_: Source, raw (as a noun), input.

**Normalized**:
The deterministic derived audio produced from an Original: **mono, 16 kHz, 16-bit PCM WAV**,
downmix-by-mean → soxr `HQ` resample → `PCM_16`, with **no loudness change and no dither**
(exact procedure and determinism guarantees pinned by ADR-0005). Also called *derived* audio.
_Avoid_: Processed, converted, output.

### Annotation

**Intended text**:
What the Speaker was asked to say — the Prompt text. Collected in v0.1.
_Avoid_: Reference, ground truth, label.

**Perceived text**:
What a listener judges was actually said. A reserved schema slot in v0.1 — **not collected**, no
annotation flow. Named here so the dual-annotation model is explicit.
_Avoid_: Transcript, actual text, hypothesis.

### Dataset

**Sample**:
One row of a dataset/manifest: a single Normalized audio file plus its metadata and split
assignment, ready for a consumer (HF / NeMo). A Sample points at a Recording's Normalized audio.
In v0.1 kept Recordings map 1:1 to Samples.
_Avoid_: Row, example, item, recording (distinct — see above).
_See_: ADR-0006 (manifest format — the exact per-Sample fields).

**Manifest**:
The **output** HF/NeMo artifact describing a Dataset's Samples: the per-Split `train/val/test.jsonl`
(canonical, NeMo-native) plus the per-Split `audio/<split>/metadata.jsonl` (HF `audiofolder` view),
alongside the `dataset.json` descriptor. Each Manifest line is one Sample. "Manifest" always names
this emitted artifact — the **input** index the operator authors is `recordings.csv`, never a
"manifest".
_Avoid_: Index, listing, catalog; recordings.csv (that is input, not a Manifest).
_See_: ADR-0006 (manifest format), ADR-0003 (where the files sit).

**Split**:
One of the three disjoint subsets a Dataset is partitioned into — **train**, **validation** (val),
**test** — each Sample belonging to exactly one. The partition is **session-aware**: a whole Session
is never torn across Splits (a Speaker may recur across Splits, as v0.1 data is single-speaker). The
tool never trains or evaluates; it produces the Split labels a downstream consumer (HF / NeMo)
honors, frozen into the Dataset Version so the partition is reproducible.
_Avoid_: Fold, partition (as a noun for one subset), subset.
_See_: ADR-0004 (session-aware splitting).

**Dataset**:
The complete collection defined by one input set. The tool is a stateless transform with no
managed workbench directory: a Dataset is exactly the contents of one `--data-in`, transformed
into `--data-out`. There is **one Dataset per input set**, and it carries no user-assigned name.
_Avoid_: Corpus, collection, project.
_See_: ADR-0002 (stateless `--data-in`/`--data-out`).

**Dataset Version**:
An immutable snapshot produced by a build: a fixed set of Samples with their metadata and split
assignment, built under a fixed config and tool version. Identified by `dataset_version` — a
content-derived id (`sha256:` + full 64 hex) computed over the **emitted manifest bytes** plus the
effective config and the tool version, so identical inputs always yield the same Version and any
change to a Sample, its metadata, its split, or a config knob yields a different one. Because the id
covers the manifest as emitted, a Version is **recomputable from `--data-out` alone** — no access to
`--data-in` required. It identifies the manifest and config, **not** the Normalized audio bytes
(which ADR-0005 makes cross-arch non-bit-exact); the audio is covered via each Sample's
`content_hash` of the Original. A rebuild after adding data, editing `recordings.csv`, or changing
config is a new Version. Only the current Version exists on disk (ADR-0003).
_Avoid_: Release, snapshot (as a noun), tag, revision.
_See_: ADR-0010 (version & provenance mechanics), ADR-0001 (identifiers).

### Quality

**Quality flag**:
An advisory label attached to a Sample when an energy/amplitude check crosses a threshold — one of
exactly three in v0.1: **clipping**, **low_volume**, **duration_out_of_range**. A flag never excludes
or quarantines a Recording (all attempts are data); it is descriptive metadata a downstream consumer
may filter on. Silence is measured but **never flagged** (leading/trailing/overall silence are
report-only metrics). Distinct from a structural failure, which aborts the whole build (ADR-0005).
_Avoid_: Error, warning, rejection, defect.
_See_: ADR-0007 (audio validation & quality checks).

**Quality report**:
The emitted record of the quality checks: `reports/quality.jsonl` (one row per kept Recording, all
metrics + its `flags` array) and the human quality digest in `reports/summary.txt` (a per-flag tally
plus one line per flagged Recording). The `validate` command prints the same digest to stdout without
writing anything. The Manifest itself carries no quality fields.
_Avoid_: Validation log, QC output.
_See_: ADR-0007 (audio validation & quality checks), ADR-0003 (report file locations).

### Visualization

**Image**:
A rendered PNG view of a Recording's **Normalized** audio, emitted for **every** Recording on every
build as exactly two per Recording: `images/<recording_id>.waveform.png` and
`images/<recording_id>.spectrogram.png`. An Image is an **operator inspection aid** — a diagnostic
surface, never part of the Dataset a consumer receives, and outside `dataset_version` (ADR-0010).
An Image states **measurements, never verdicts**: it renders the peak/RMS values the quality checks
computed, but carries no Quality flag and reads no threshold. Its scales are absolute and fixed
(waveform y at ±1.0; spectrogram at −80..0 dBFS) so an Image can never contradict a Quality flag —
a quiet Recording looks quiet.
_Avoid_: Plot, figure, chart, viz, thumbnail, preview.
_See_: ADR-0011 (visualization output), ADR-0003 (image naming & location).

### Metadata

**Environment**:
The acoustic setting of a Session (e.g. quiet room, office). An attribute of the Session.
_Avoid_: Location, background, scene.

**Device**:
The capture hardware used for a Session (e.g. a specific microphone). An attribute of the Session.
_Avoid_: Mic, hardware, equipment.
