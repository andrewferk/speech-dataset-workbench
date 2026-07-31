# Evaluation vocabulary (v0.2)

v0.1's glossary was written for a tool with no model in it: it has no word for text a machine
produced, for the act of producing it, or for the act of scoring it. v0.2 needs all three at once,
and several of the obvious words are already spent — `Normalization` names an audio transform,
`Reference` is on an _Avoid_ list, `Perceived text` is reserved for a human, and `Version` carries a
content-derived promise evaluation cannot keep. This ADR fixes the evaluation vocabulary recorded in
`CONTEXT.md` and, where a v0.1 term had to move, says what moved and why.

It builds on ADR-0001 (identifiers), ADR-0003 (storage & retention), ADR-0005 (normalization),
ADR-0006 (manifest), ADR-0007 (quality) and ADR-0010 (`dataset_version` & provenance). It **amends**
`CONTEXT.md`'s **Intended text** entry. It amends no ADR.

## Decisions

### The sentence the vocabulary exists to make sayable

v0.2's architecture is a split reproducibility contract, and the glossary is correct exactly when
that contract fits in one line:

> **Transcription** is attributed and emits a **Hypothesis Record**; **Scoring** is reproducible and
> derives **Metrics** from it; **Evaluation** is both.

Three terms rather than one, because a single word cannot carry two contracts. "Evaluation is
reproducible" and "evaluation is not reproducible" are both false, and any vocabulary that forces a
reader to pick between them has already lost the property v0.2 is built around.

### `Hypothesis`, and the `perceived_text` firewall

Model-emitted text is a **Hypothesis** — the field's standard term, spoken by every source, every
paper and every scoring library.

It costs nothing to adopt because v0.1 **already pushed the word away from the human slot**:
`Perceived text` carries _Avoid_: "Transcript, actual text, hypothesis." That entry is usually read
as a hazard here. It is the opposite — it is a reservation. v0.1 declined to spend "hypothesis" on
the human judgment, so the word was free, and adopting it makes the firewall bidirectional: a
Hypothesis is never a Perceived text, and a Perceived text is never called a hypothesis.

The firewall matters more than the naming. Filling `perceived_text` with machine output would
destroy the dual-annotation model at the moment it starts to pay, and would later train a fine-tuned
model on a generic model's own mistakes. Making that unsayable in the glossary is cheaper than
policing it in review.

`Transcript` was the alternative — friendlier, and the word a non-specialist reaches for. Rejected
because it is silent about *who produced it*, which is the single distinction this vocabulary
exists to protect; `perceived_text` rejects it for the same reason, and reusing it would make the
glossary say "avoid transcript, use Hypothesis" and "Hypothesis means transcript" at once.

### `Reference` as a role — amending `CONTEXT.md`'s Intended text

**Intended text** carries _Avoid_: "Reference, ground truth, label." That rejection is narrowed, not
lifted. **Reference** is now defined as an evaluation **role** — the side a Hypothesis is measured
against — while remaining rejected as a *synonym* for the Prompt text.

The distinction is not lawyering. A role is a position in a comparison; the text that fills it is a
choice. In v0.2 the Reference *is* the Intended text, but that is a contingent fact about v0.2, and
three things follow that a synonym could not express:

- **The ceiling becomes sayable in one line.** v0.1 collects intended text only, so v0.2's WER
  conflates *recognition error* with *speaker deviation* — small for careful reading, not small for
  the atypical-speech population this project exists for. The report must state what it measured;
  with a role term that is `Reference = Intended text`, not a paragraph re-derived each time.
- **`perceived_text` already has its landing site.** When perceived text is collected, the Reference
  becomes a choice between two texts. The slot should exist before that day, not be retrofitted on
  it. Today the glossary cannot even express "we could have measured against something else."
- **Every source speaks it.** Scoring libraries take `(reference, hypothesis)` positionally and the
  literature is written in those terms throughout. Refusing the word means translating in both
  directions forever, at exactly the seam where mistranslation is most expensive.

The _Avoid_ list keeps **ground truth** and **gold**, which is the part of the original rejection
that was really load-bearing: those words assert the text is *correct*. A Reference asserts only
that it is the side being measured against — and on atypical speech the difference between those two
claims is the whole subject.

### `Text Normalization` is qualified; bare `Normalization` stays audio

ADR-0005 fixed **Normalization** as a format transform (mono / 16 kHz / `PCM_16`) and **Normalized**
as a *noun* for the derived audio. Scoring needs an unrelated operation on text. The new term is
**Text Normalization**, always written with "Text", plus **Normalizer** for a specific rule-set.
ADR-0005 is untouched and remains true as written.

The symmetric fix — renaming v0.1's to *Audio* Normalization — is tidier on paper and rejected on
two grounds. It ripples through `CONTEXT.md`, ADR-0003, ADR-0005, ADR-0011 and the code to buy
symmetry a qualifier already provides; and the symmetry would **overstate the resemblance**. One is
a retained artifact on disk with a determinism guarantee; the other is an ephemeral function applied
inside a pure stage. Making them look parallel implies a kinship they do not have.

The accepted cost is that "Text Normalization" is two words and readers will shorten it. The
mitigation is structural rather than editorial: the two live in disjoint halves of the tool —
`sdw.pipeline` has no text normalizer and the evaluation path never touches audio normalization — so
a bare "normalization" is disambiguated by where it is written.

**`Normalizer` is a term because there is no canonical one.** Several widely-used English
normalizers ship under a single class name and are *not the same function*; at least one popular
fork silently changes published numbers. "Which normalizer" is therefore a provenance question, and
a provenance question needs a nameable, identifiable thing rather than an adjective.

### An Evaluation Run is not a Version

**Evaluation Run** (shortened to **Run**) names one execution. It is deliberately **not** a
"version", and the reasoning is the same reasoning ADR-0010 used to earn the word in the first
place. A Dataset Version is content-derived, yields an identical id from identical inputs, and is
recomputable from `--data-out` alone. An evaluation satisfies none of the three: the model is
non-deterministic, so hashing its output mints a new id every run, and nothing about it is
recomputable after the fact.

Reusing "version" would import a guarantee we cannot honour, at precisely the point where the
comparability claim lives — the reader most likely to be misled is the one leaning hardest on
`dataset_version`'s meaning. Naming it a Run makes the identity question **visible and open**
instead of silently answered; what a run id actually *is* remains undecided here, and belongs to the
run-identity decision. `Experiment` is also rejected: it implies a tracked multi-run registry, and
MLflow-style tooling is out of scope.

### `Metric`, and why `score` is not a noun

Scoring's outputs are **Metrics**. "Score" is pushed onto the _Avoid_ list for two reasons: it
collides with **Scoring**, the act, leaving "the score from scoring" as the only phrasing; and it is
the word people reach for when they mean a *verdict on quality*, which evaluation here explicitly is
not. `Accuracy` is worse — it inverts the direction and implies a 0–1 range.

That range matters enough to sit in the glossary rather than a spec: an error rate is **never
clamped**. Rates above 1.0 are real and published, and runaway decoding on near-silent or atypical
audio is this project's likeliest path to one. A glossary that lets a reader assume 0–1 has
pre-broken the report.

**`Pooled` and `Macro-average` are glossary terms, not spec vocabulary.** Pooled sums errors and
Reference lengths across a group and divides once; macro-average averages per-unit rates. They can
differ by several points on the same data, and the reference scoring toolkit has printed both side
by side for decades. A headline number that moves that far on an unstated convention is a number
whose convention has to be **named where the language is defined** — otherwise a report can print
"WER: 0.31" and be unfalsifiable. Which one is the headline is a scoring-spec decision; that both
have names is this one.

### The unit does not change, but the covered set gets a name

One **Sample** yields one Hypothesis yields one Hypothesis Record line, with the same identity
throughout. Evaluation introduces **no new unit**. A subset of Samples is still Samples, and the
architecture's stranger-consumer reading of the emitted manifest means what the evaluator reads
*is* a Manifest line — a separate unit noun would imply a translation step the design deliberately
does not have. Stable identity is also what makes pairing by identifier rather than by position
obviously correct.

What does need a name is the **Evaluation Scope**: the set of Samples one Run covers, fixed by a
Split selection. Without it the comparability rule between two Runs is unstatable — two Runs over
the same Dataset Version are not comparable if one covered `test` and the other covered everything.

"Evaluation Set" was the natural phrase and is rejected: "eval set" already means *a split* in
common usage, and this glossary has **Split** as a first-class term, so it would read as "the
val/test split" to exactly the audience learning this ecosystem.

### Evaluation output never re-enters the Dataset

**Evaluation Report** is deliberately parallel to **Quality report**, and inherits its firewall:
the Manifest carries no evaluation fields, and evaluation output never lands in `--data-out`, which
ADR-0003 replaces wholesale on rebuild. **Breakdown** — a Metric over a group of Samples sharing an
attribute value — is a diagnostic view of a *single* Run, never a comparison between Runs;
`comparison` is left unclaimed for cross-run work.

This is the vocabulary-level expression of a scoping decision already taken: ASR disagreement will
not become a Quality flag. ADR-0007's three flags are properties of the *audio signal*, computable
with no model and no Reference; a model's opinion is a different kind of fact, and on atypical
speech a disagreement flag would invert its meaning and flag exactly the data most worth keeping.

## Considered and rejected

- **No glossary work; let each v0.2 spec name things as it goes** — cheapest, and the reason this
  ticket exists: six specs inventing terms in passing would produce six vocabularies, and the
  collisions above (`reference`, `normalization`, `version`) would be discovered *after* they were
  written into artifacts.
- **Refusing `Reference` and writing "Intended text" everywhere** — keeps v0.1's glossary untouched
  with no amendment to justify. Rejected: it bakes the measurement ceiling into the vocabulary,
  leaves no slot for perceived text to occupy later, and makes real edge cases ("the Reference
  normalized to empty") awkward to even state.
- **`Audio Normalization` / `Text Normalization` as a symmetric pair** — see above; ripples widely
  and asserts a parallel that is not real.
- **`Evaluation Version`, mirroring Dataset Version** — attractive symmetry, and a false promise at
  the exact point the comparability claim rests on.
- **`Transcript` for model output** — friendlier, and ambiguous about authorship, which is the one
  thing that must never be ambiguous here.
- **`Hypothesis Set` for the durable artifact** — precise about being a collection, but loses the
  durability and attribution connotation "Record" carries, and "set" implies unordered and unique
  when the thing is neither.
- **Promoting `Hypothesis Artifact` to a proper noun** — it is the map's own prose, but `CONTEXT.md`
  uses "artifact" as a *category* word ("a Recording owns its audio artifacts"); promoting it would
  make the generic use ambiguous.
- **A glossary entry for `decode parameters`** — three downstream specs need the concept, but it is a
  runtime configuration surface, not domain language: the ASR analogue of `soxr HQ`, which ADR-0005
  pins without `CONTEXT.md` defining it. The phrase is mentioned inside **Transcription** so that
  "decoding" stays visibly narrow.
- **Restyling v0.1's `Quality report` to title case** for consistency with `Evaluation Report` —
  a docs-wide ripple for cosmetics, and this ADR already spends its amendment budget on the
  `Reference` narrowing.
