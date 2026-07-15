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
The deterministic derived audio produced from an Original (mono 16 kHz PCM WAV target; exact
procedure pinned by the normalization spec). Also called *derived* audio.
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

**Dataset**:
The complete collection defined by one input set. The tool is a stateless transform with no
managed workbench directory: a Dataset is exactly the contents of one `--data-in`, transformed
into `--data-out`. There is **one Dataset per input set**, and it carries no user-assigned name.
_Avoid_: Corpus, collection, project.
_See_: ADR-0002 (stateless `--data-in`/`--data-out`).

**Dataset Version**:
An immutable snapshot produced by a build: a fixed set of Samples, their split assignment, the
normalization params, and the tool version. Identified by a content-derived id, so identical inputs
always yield the same version. A rebuild after adding data is a new Version.
_Avoid_: Release, snapshot (as a noun), tag, revision.

### Metadata

**Environment**:
The acoustic setting of a Session (e.g. quiet room, office). An attribute of the Session.
_Avoid_: Location, background, scene.

**Device**:
The capture hardware used for a Session (e.g. a specific microphone). An attribute of the Session.
_Avoid_: Mic, hardware, equipment.
