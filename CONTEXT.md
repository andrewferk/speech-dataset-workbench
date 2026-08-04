# Speech Dataset Workbench

A local-first, CLI-only tool that turns a collection of **prompted** speech recordings into a
validated, reproducible, versioned dataset with an HF/NeMo-friendly manifest. This glossary is the
ubiquitous language for v0.1's dataset build and v0.2's evaluation of a model against it; it is a
glossary only — no implementation details.

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
_Note_: Unqualified **Normalization** / **Normalized** always means this audio transform. The
text-shaping applied before Scoring is **Text Normalization**, never shortened (ADR-0015).

### Annotation

**Intended text**:
What the Speaker was asked to say — the Prompt text. Collected in v0.1.
_Avoid_: Reference **as another name for this text**, ground truth, label. (**Reference** is
separately defined below as an evaluation *role* — the side a Hypothesis is measured against — which
the Intended text happens to fill in v0.2. Amended by ADR-0015.)

**Perceived text**:
What a listener judges was actually said. A reserved schema slot in v0.1 — **not collected**, no
annotation flow. Named here so the dual-annotation model is explicit.
_Avoid_: Transcript, actual text, hypothesis.
_See_: Hypothesis (below) — machine-emitted text is a Hypothesis and may **never** fill this slot.

### Dataset

**Sample**:
One line of a Manifest: a single Normalized audio file plus its metadata and split
assignment, ready for a consumer (HF / NeMo). A Sample points at a Recording's Normalized audio.
In v0.1 kept Recordings map 1:1 to Samples.
_Avoid_: Row (that is `recordings.csv`'s vocabulary — the input has rows, the Manifest has lines),
example, item, recording (distinct — see above).
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
The emitted record of the quality checks: `reports/quality.jsonl` (one line per kept Recording, all
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

### Evaluation

Introduced in v0.2. Every term here names something on the model side of the tool; nothing in this
section may alter a Dataset, a Manifest, or a Quality flag.

**Evaluation**:
Measuring how well a model transcribes a Dataset Version's audio — Transcription followed by
Scoring. A measurement an operator reads, never a judgment fed back into the Dataset.
_Avoid_: Benchmarking, testing, validation (that names v0.1's `validate` command — a different act).
_See_: ADR-0015 (evaluation vocabulary).

**Transcription**:
The act of running a model over a Sample's Normalized audio to produce a Hypothesis. **Attributed,
not reproducible**: its output is not guaranteed identical across runs, so it is stamped with the
provenance that identifies it instead. Its runtime knobs are *decode parameters* — "decoding" names
those knobs, never the whole act.
_Avoid_: Inference, recognition, prediction, decoding (narrower — see above).

**Hypothesis**:
The text a model emits for one Sample. **Never** a Perceived text: that slot is a human judgment and
machine output may not occupy it.
_Avoid_: Transcript, perceived text, prediction, guess.

**Hypothesis Record**:
The durable artifact Transcription emits — one line per transcribed Sample carrying its Hypothesis,
alongside the provenance of the Run that produced it. Retained unmodified so Scoring can be re-run
against it without re-running the model, the same relationship an Original has to its Normalized
audio.
_Avoid_: Cache, transcript file, hypothesis artifact ("artifact" is a category word here, not a name).
_Note_: "alongside" is **not** on the same line or in the same file. **ADR-0019** puts the Record in
`hypotheses.jsonl` and the Run's provenance in a sibling `run.json`, written last as the completeness
sentinel — a header line could not be written last. The two files are one Run directory and one
artifact in the sense meant here; neither is readable as a Run without the other. A line whose
`hypothesis` is `null` is a **failed** Transcription, distinct from `""`, which is the model's output.

**Scoring**:
The derivation of Metrics from a Hypothesis Record and its References — **pure and byte-identical**
across machines, with no model and no audio involved.
_Avoid_: Measurement, grading, judging.

**Reference**:
The **role** a text plays in Scoring: the side a Hypothesis is measured against. It is a position in
a comparison, not a claim of correctness, and an Evaluation Report always names which text filled
it. In v0.2 that is the Intended text — so a Metric conflates recognition error with speaker
deviation, and the Report must say so.
_Avoid_: Ground truth, label, gold.

**Text Normalization**:
The deterministic text-shaping applied to **both** Reference and Hypothesis before they are
compared. Always written with "Text": unqualified **Normalization** means ADR-0005's audio transform
and nothing else.
_Avoid_: Normalization (unqualified), cleaning, preprocessing.

**Normalizer**:
A named, versioned rule-set that performs Text Normalization. Named because there is no single
canonical one — widely-used normalizers share a class name yet produce different numbers — so an
Evaluation Report must state which one it used.
_Avoid_: Cleaner, filter, preprocessor.

**Metric**:
A named measure Scoring derives from Reference/Hypothesis pairs — word error rate (WER), character
error rate (CER), sentence error rate (SER). An error rate is not a proportion of a whole and is
**never clamped**: a Metric above 1.0 is a real, reportable result.
_Avoid_: Score (reserved — Scoring is the act, and "score" invites a verdict reading), accuracy.

**Pooled**:
The aggregation that sums errors and Reference lengths across a group and divides **once**.
_Avoid_: Total, overall, corpus average.

**Macro-average**:
The aggregation that averages per-unit rates, weighting every unit equally. Legitimate for a
Breakdown, where groups differ in size on purpose; never presented unlabelled as "the WER", because
it and Pooled can differ by several points on the same data.
_Avoid_: Average, mean (unqualified).
_Note_: This entry said "per-Sample Metrics"; ADR-0015 defines it as "per-unit rates" and leaves the
unit to the scoring spec. **ADR-0018 fixes the unit as the Breakdown group**, each of which is Pooled
first — so a per-Sample `null` inside a mixed group never reaches a Macro-average.

**Evaluation Scope**:
The set of Samples one Run covers, fixed by a Split selection. The unit inside a Scope is a
**Sample**, unchanged — evaluation introduces no new unit, and pairing is by identifier, never by
position.
_Avoid_: Eval set, test set, subset.

**Evaluation Run**:
One execution of an Evaluation: one model over one Evaluation Scope of one Dataset Version, under
one Normalizer and one set of decode parameters. Shortened to **Run**. Explicitly **not** a version —
a Dataset Version is content-derived, reproducible, and recomputable from output alone, and a Run is
none of those.
_Avoid_: Version, snapshot, release, experiment.
_Note_: "one Normalizer" is superseded by **ADR-0018**, which computes every Metric under **two**
always-on Normalizers, `sdw-tier-a/1` and `whisper-english/b80bcf6`; what a Run still holds one of is
the *set* of Normalizers, fixed and not selectable. This entry also said both strings were "required
inputs to a Run's identity", which went stale twice: **ADR-0020** gives a Run **no identity at all**
(its handle is its directory name) and moves the Normalizer strings out of `run.json`, since
`transcribe` writes that file and Text Normalization happens in `score`. Per **ADR-0022** they are
**Report-side attribution**, named in every Evaluation Report's header — which is where ADR-0015's
requirement that a Report state which Normalizer it used is discharged.

**Evaluation Report**:
The emitted record of a Run: its Metrics, its Breakdowns, and the provenance attributing them. An
operator-facing artifact, like the Quality report — the Manifest carries no evaluation fields, and
Evaluation output never lands in `--data-out`.
_Avoid_: Results, scorecard, summary.
_Note_: "emitted record" is **not** a file. Per **ADR-0021**, `sdw score` writes nothing to disk — a
Report is emitted to **stdout** and never persisted by the tool, and a Run directory never contains
one. A Report is cheap and pure where a Hypothesis Record is expensive and irreproducible, so it is
regenerated rather than retained. An operator's redirected copy is their artifact, not `sdw`'s.
_Note_: **ADR-0022** gives one Report **two renderings** of that same stream, selected by
`--format` — a human digest (percentages, fixed header, Breakdown tables, a worklist of Samples that
erred) and a JSON document (every aggregate and Breakdown group, plus one row per Sample with its
integer counts, normalized text and alignment under both tiers). Two renderings, one Report: same
Scope, same numbers, same disclosures. A Report carries no Quality flag — that correlation is a join
on `id` against `reports/quality.jsonl` — and no confidence interval; and `sdw` never calls a Report
a **Baseline**, which is a reading an operator applies to it.
_Note_: **ADR-0024** fills in what "the provenance attributing them" includes. A Report quotes the
**Transcription provenance** of the Run it scores — `run.json` verbatim in the JSON rendering, and in
the digest as a block whose headings are ADR-0020's comparability tiers. So a Report states its
Scope, its Normalizers **and** its conditions, which makes it sufficient to apply ADR-0020's
comparability rule against another Report: comparing two Runs is `diff` of two Reports for the
conditions and a `jq` join on `id` for the paired per-Sample deltas. Only the rule's *escalation* for
an unequal `dataset_version` still needs the two Hypothesis Records. A Report quotes facts the Run
recorded; it never observes one of its own, so both renderings stay byte-identical across machines.

**Breakdown**:
A Metric computed over a group of Samples sharing an attribute value — one Session, one Prompt, one
Device, one Environment. A diagnostic view of a **single** Run's numbers, never a comparison between
Runs.
_Avoid_: Slice, segment, cut, comparison.

**Baseline**:
The Evaluation Report of an **unmodified**, off-the-shelf model over a Dataset Version — the number
later work is measured against. Only meaningful alongside the Reference and Normalizer it names.
_Avoid_: Benchmark (implies a shared public leaderboard; a Baseline is local).
