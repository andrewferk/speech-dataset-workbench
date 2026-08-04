# Evaluation report content & breakdowns (v0.2)

ADR-0018 fixed what the numbers **mean**; ADR-0020 fixed what attributes them; ADR-0021 fixed that
the Report is a **stdout stream, never a file**, and handed the rest here: *"What the Report contains
and how it renders stays #136's."* This ADR fixes the contents — what `sdw score` writes to stdout,
in what renderings, with which Breakdowns, at what per-Sample detail, and in what words. It resolves
#136.

It builds on ADR-0004 (disclose plainly; no thresholds, no knobs — the repair lines and the
speaker-overlap note), ADR-0007 (`RATIO_DP`, `render_digest`'s worklist shape and its fixed tally),
ADR-0011 (measurements, never verdicts), ADR-0012 (run duration stays off the compared artifact),
ADR-0015 (Metric, Pooled, Macro-average, Reference, Baseline), ADR-0017 (Scope label, per-Split
Breakdown, N-of-M disclosure, the comparability rule), ADR-0018 (six numbers per Scope, integer
counts as the source of truth, `null` for undefined rates, and the dimensionless canonical form),
ADR-0019 (the Record's field set, and the `long_form` count) and ADR-0021 (stdout only; `score` is
read-only).

It **amends ADR-0017, ADR-0018 and ADR-0021 in one place each** — all three record a synopsis or a
no-configuration claim that a `--format` flag touches — and annotates two `CONTEXT.md` entries,
including the stale **Evaluation Run** sentence ADR-0021 found and deliberately left for this ticket.

The whole ADR follows from a collision between two upstream decisions. **ADR-0018 requires the
per-Sample integer counts to be emitted exactly, under both tiers, "so any later analysis needs no
re-scoring." ADR-0021 requires all of it to leave through stdout.** A human digest cannot carry
12–100 Samples × 2 tiers × 3 count-sets and stay a digest; a JSON dump of the same is not a
digest. ADR-0021 foresaw this and pre-authorised the answer — *"if #136 concludes it needs both a
human rendering and a machine-readable one, that is a rendering question about one stream, not a
reason to write files."* It does, and it is.

## Decisions

### Two renderings of one stream, selected by `--format`

```
sdw score --run <run-dir> [--split <name>] [--format text|json]
```

`--format` defaults to `text`. The two renderings carry **the same Report** — the same Scope, the
same numbers, the same disclosures — at different resolutions:

- **`text`** — the operator's digest. v0.1's `summary.txt` register, with percentages, a fixed
  header block, the Breakdown tables and a worklist of Samples that erred.
- **`json`** — the complete machine Report: every aggregate, every Breakdown group, and one row per
  Sample carrying its integer counts, its normalized text and its alignment under both tiers.

This is v0.1's two-artifacts-for-two-readers shape (ADR-0007: `quality.jsonl` joins to the manifest,
`summary.txt` is the operator's worklist) reproduced across one stream instead of two files, which is
the only form ADR-0021 leaves available. The alternative readings both fail on an upstream
commitment: a digest alone cannot carry ADR-0018's counts, and JSON alone would deliver *the number
the whole map exists to produce* as a key in a blob.

**`--format` is a rendering selector, not configuration, and the distinction is load-bearing rather
than a rescue of a slogan.** ADR-0018 closed `[scoring]` on the rule that *every input to an
Evaluation is a constant this repo owns or a field of the dataset it read* — a claim about what is
**measured**. `--split` already sits on `score` without violating it, and it does more than `--format`
does: it selects the Scope, which changes every number. `--format` changes no number, no Metric, no
Scope, and nothing that reaches durable identity — the same Report renders twice, and a reader who
runs both gets two views of one measurement. The knob ADR-0004 and ADR-0011 rejected was one that
*changes what the tool says for no change in what happened*; this one changes only the typography.
The three ADRs that state the no-configuration property are amended in place to say so precisely,
rather than left to be read as contradicted.

**The JSON rendering is a single JSON document**, not JSONL. A Report is one object with nested
aggregates and a Sample array, unlike `quality.jsonl` and the Manifest, which are line-per-entity
files a consumer streams and joins. Key order is fixed by declaration order and guarded by a test,
as ADR-0018 requires and as v0.1 already does.

### The Report says nothing about quality flags

The Report carries no Quality flag, no flag tally, and no flag Breakdown. **`clipping`,
`low_volume` and `duration_out_of_range` do not appear anywhere in it.**

#136 called correlating WER against the flags *"the single most useful thing this report could
say."* It is genuinely valuable and it is **still available** — but not from inside `score`, and it
does not need to be. The flags live in `<data-out>/reports/quality.jsonl`, and ADR-0017 forbids
`score` opening the dataset at all, which is what makes purity a property *of the command*. So the
correlation is reachable in exactly one of two ways: put the flags on the Hypothesis Record line, or
leave the join to the operator. The join wins:

- **The identifiers already line up.** ADR-0001 gives one id per Recording, ADR-0006 carries it onto
  the Manifest line, ADR-0007 keys `quality.jsonl` by it, ADR-0019 puts it on every Record line, and
  this ADR puts it on every Sample row of the JSON Report. Correlating WER against flags is a `jq`
  join on `id` with **zero machinery** — the same shape as ADR-0020's escalation path, which
  discovered that diffing two masked `hypotheses.jsonl` files *is* manifest-byte equality, "a payoff
  of the Record being a superset, not new machinery."
- **A `flags` field would import a configurable opinion into the eval artifact.** ADR-0019 refused to
  reuse `duration_out_of_range` for `long_form` precisely because ADR-0007's flag fires against a
  **configurable** threshold and Whisper's regime is fixed — *"one name for two thresholds"* in an
  artifact whose job is disclosure. Carrying the flags themselves onto the Record is the stronger
  version of the same mistake: two Runs over the same audio could carry different flags, with nothing
  on the line explaining why, and the Report's flag Breakdown would silently mean different things.
- **It keeps a distinction the map needs from having to be explained.** The map ruled out
  ASR-as-dataset-QA *on the merits, not deferred* — because a model's disagreement inverts its
  meaning on atypical speech. A flags-vs-WER section printed by `sdw` would be read-only correlation
  that **looks** like the ruled-out feedback loop, and would need a paragraph disclaiming itself
  every time it printed. An operator's own `jq` join needs no such paragraph, because the operator is
  the one drawing the inference.

**The cost, on the record:** the join needs the dataset still on disk, whereas ADR-0019 and ADR-0020
deliberately made a Run answer questions *after the dataset is long gone*. This is the one question
that regresses to needing both. It is accepted because the flags are a property of the **audio**
(ADR-0007: computable with no model and no reference), so they belong to the dataset's own record of
itself, and because reversing this later is cheap in exactly the way that matters: adding a field to
the Record is a `record_version` bump and a re-Transcription, and a re-Transcription is what you
would be doing anyway if you cared about a dataset you no longer have.

### The headline, and no confidence interval

**The headline is Tier A Pooled WER over the Scope actually scored** (ADR-0018 and ADR-0017,
unchanged), stated once, with its Scope label attached. **The Report carries no confidence
interval** — not on the headline, not on the Breakdown groups.

This is the ticket's hardest question, because #128's bootstrap put the 95% CI at **6–11 points wide
at twelve utterances** and ADR-0018 handed this ticket a genuinely free choice: the per-Sample counts
make a bootstrap computable with no re-scoring, so cost is not the argument. The argument is that
**the absolute CI describes the statistic this project does not use.**

- **It is the wrong interval for the endorsed comparison.** The destination is *a number you can
  honestly compare against a future fine-tuned model*, and that comparison is **paired on an
  identical corpus** — far tighter than the absolute interval on either number alone. #128's own
  framing is that our absolute number is sampling-limited while comparing two scorings of the same
  Samples is *"pure, paired, and carries no sampling error at all."* An absolute CI printed beside
  the headline is an accurate answer to a question nobody in this design asks.
- **Printing it invites a false *no*.** A reader shown two overlapping absolute CIs concludes *no
  difference* — the standard misreading of overlapping intervals, and here it fires exactly where the
  paired comparison would show a real one. #129 spent an entire ticket on **direction of error**,
  accepting `dataset_version` churn because churn is a false *no* you look at and a stale id is a
  false *yes* you never look at. The same test decides this: a CI's failure mode is a false negative
  on the one comparison the tool exists to enable, and a reader who "sees no significant difference"
  does not go looking further.
- **The interval is itself imprecise at N=12,** and it would arrive carrying three arbitrary
  constants — resample count, seed, percentile method — none of which has a principled value here.
- **The counts are emitted regardless.** Anyone who wants the bootstrap has every input to it in the
  JSON rendering, under both tiers, without re-scoring. Declining to print a CI is not declining to
  make one computable; ADR-0018 already guaranteed that.

> **Amended by ADR-0024 (#149): "paired on an identical corpus" overclaims for the cross-run case —
> the decision is unaffected, the reasoning is corrected.** #128's *"pure, paired, and carries no
> sampling error at all"* is about two scorings of the **same** Hypotheses: Tier A against Tier B,
> where the Hypotheses are byte-identical and only the Normalizer moved, so ADR-0018 can emit that
> delta as exact. A **cross-run** delta is paired by Sample — same `id`s, same References, so
> corpus-composition variance genuinely cancels — but it is **not exact**: the Hypotheses differ, and
> they differ from the model change *and* from the same model's run-to-run non-determinism, which
> ADR-0015 (attributed, not reproducible), #127 (no runtime documents reproducibility at all) and
> ADR-0020's own opening line all decline to claim away. **That floor is unmeasured**, so a v0.3 delta
> beneath it would mean nothing while looking like a result. Both arguments above survive intact and
> ADR-0024 strengthens them: the honest quantity is not a bootstrap on either absolute number but an
> **empirical floor the operator measures** by transcribing twice under identical provenance — which
> carries none of the three arbitrary constants the third bullet objects to. The prose below is
> amended to say *paired but not exact*.

**What replaces it is prose, in ADR-0004's register: surface it plainly, no thresholds, no knobs.**
The header block states, in fixed words, that the absolute number is imprecise on a corpus this size
and that the comparison it exists for is paired against a Run over the same Samples. That sentence is
the single most important thing the Report communicates — #128's own conclusion — and it is exactly
what a decimal place fails to say.

**SER is not a substitute and is not presented as one.** ADR-0018 emits it because it is a per-Sample
binary and *far more stable at N=12*; that stability is a property of a different measure, not
better precision about WER. It sits in the table as one of the six numbers, labelled, and no text
implies it answers the interval question.

### Per-Sample rows: counts, normalized text, and the alignment

The JSON rendering carries **one row per scored Sample**, keyed by `id`, holding under **each** tier:

- the **word-level** S, D, I and Reference token count; the **character-level** S, D, I and Reference
  character count; the sentence-level binary — ADR-0018's mandated set, verbatim
- the derived per-Sample WER, CER and SER — **`null`** where ADR-0018's table makes them undefined
- the **normalized Reference and Hypothesis** as that tier produced them
- the **alignment**: the ordered op sequence (`equal` / `sub` / `del` / `ins`) with the tokens on each
  side

Everything here is re-derivable by re-running `score` in milliseconds, so the question is only what a
reader is saved from redoing. ADR-0018 answered it once already, for the counts — *emitted exactly,
so any later analysis needs no re-scoring* — and the same logic extends to the other two, which are
harder to reconstruct and cheaper to emit:

- **The normalized text exists nowhere on disk.** ADR-0019 puts only *raw* Reference and Hypothesis
  on the Record. Recovering what was actually compared means re-implementing Tier A's six Unicode
  steps and running the vendored Tier B — for the two texts that explain every number above them.
  Emitting them also makes ADR-0018's headline argument *inspectable* rather than asserted: a reader
  can see `O'Brien → 0 brien` happen, on their own corpus, in the row that paid for it.
- **The alignment is the only place the backtrace tie-break is visible.** ADR-0018 fixed the tie-break
  as *"a contract obligation, not an implementation note"* because equal costs make the S/D/I split
  ambiguous. An integer triple obeys that contract silently; the op sequence shows it. And "3
  substitutions" without the ops is a number an operator cannot act on, which is the error analysis
  this Report exists to enable.

**Raw text is not repeated.** It is on the Record, joinable by `id`, and ADR-0021 records that
`hypotheses.jsonl` is the first artifact `sdw` produces containing *what a speaker actually said*.
Copying that field into a second stream for a join `id` already makes free is the wrong trade. The
normalized text is emitted because it is **new** — a derivation that exists in no other artifact —
not because text is harmless.

**Failed Samples get no row**, per ADR-0018's edge-case table: a crashed decode produced no
Hypothesis, so there is no pair to align and any invented value would be a claim about text the model
never produced. They are counted in the header instead, which is the next section.

### The text digest: a fixed header, then the tables, then a worklist

The digest's shape is **invariant**. ADR-0007's `render_digest` prints its three-flag tally *"even at
zero, so the shape is fixed and a diff shows a count change rather than a line appearing"*, and that
rule transfers whole — with more force here, because ADR-0021 hands #138 goldens that **diff a
captured stream**, so a line that appears conditionally is a golden that changes shape rather than
value.

**The header block, always present, in this order:**

1. **Scope** — which Split selection was scored, always labelled (ADR-0017).
2. **N of M** — Samples scored of Samples in Scope, **printed even when N = M**, with the failure
   count and the `long_form` count beside it, both from the Record (ADR-0019).
3. **The Reference** — that it is the Prompt, and therefore that every number below measures
   recognition error **plus speaker deviation**. The map's named ceiling, stated as a property of the
   measurement rather than a footnote.
4. **The comparability rule** — compare only Runs of equal Scope; once a model has trained on
   `train`, only `test` is honest (ADR-0017); and the paired-vs-absolute sentence from the previous
   section.
5. **Attribution** — both Normalizer identity strings (`sdw-tier-a/1`, `whisper-english/b80bcf6`) and
   the **scoring** `tool_version`, which ADR-0020 established is a third occurrence and *routinely*
   differs from the built and transcribed ones.

> **Amended by ADR-0024 (#149): the header also carries the Run's Transcription provenance, and
> item 4 shrinks.** This block was written for a *single* Report and omits every tier-1 fact of
> ADR-0020's comparability rule — `model`, `decode`, `language.value` — and its whole
> *may-differ-must-be-disclosed* tier: `runtime`, `host`, the transcribing `tool_version`. The
> consequence is that `diff` of two Reports, the comparison ADR-0021 endorsed and this ADR's
> fixed-shape rule optimises for, renders clean and byte-stable between a `whisper-tiny` Run and a
> `whisper-large-v3-turbo` Run while **naming neither model** — silent on the one condition that
> makes the comparison illegitimate, in a header that prints the rule as prose at item 4. ADR-0024
> adds the provenance: `run.json` **verbatim** under one key in the JSON rendering, and in the digest
> as a block whose section headings are ADR-0020's tier names, with the facts beneath them. Item 4
> keeps Scope equality, the `train`/`test` honesty rule and the paired sentence — the tier labels
> having absorbed the rest. Items 1, 2, 3 and 5 are unchanged and stay unconditionally present.

**Then the numbers**: the Tier A headline; the six-number table (WER/CER/SER × Tier A/Tier B); the
Tier B − Tier A delta, named a **delta**, never a "deviation" (ADR-0018).

**Then the five Breakdowns**, then the worklist.

**`sdw` never prints the word "Baseline".** ADR-0017 requires that a Run carrying any Transcription
failure *"may not be labelled a Baseline without that count beside it."* This ADR honours that by
making the count **unconditionally present** rather than by policing a label — and by declining to
assert the label at all. **Baseline is a reading an operator applies to a Report**, not a status the
tool confers: ADR-0015 defines it as the Report of an *unmodified, off-the-shelf* model, and `score`
reads a Record and cannot know whether the weights behind it were fine-tuned. A tool that printed
"this is a Baseline" would be issuing the verdict ADR-0011 refused for Images, on evidence it does
not have. The Report states measurements and disclosures; the operator decides what the numbers are
a baseline *for*.

### Percentages in the digest, dimensionless rates in JSON

ADR-0018 fixed the canonical form as a dimensionless rate at `RATIO_DP = 4` and said explicitly that
*"percentage rendering is the human digest's business"*, handing the choice here. It is taken:
**the text digest renders `8.33%`; the JSON rendering carries `0.0833`.**

Every ASR result a reader has seen is written in percent, and the digest exists to be read. The JSON
keeps the canonical form because it is the machine surface and ADR-0018's rounding rule — *round at
serialization, never at measurement* — is stated over it. The percentage is a rendering of the same
rounded rate, at two decimal places, which is `RATIO_DP` shifted by the same two places rather than a
second precision decision.

**Fixed decimal places, not `round`**, per v0.1's `_evidence`: `round` drops trailing zeros and
produces a ragged column where a scannable one was wanted.

### All five Breakdowns, every group carrying its N

**Split, Session, Prompt, Device, Environment** — all five, in **both** renderings, each group
Pooled per ADR-0018, each accompanied by its **Sample count**, with the Macro-average, standard
deviation and median across groups that ADR-0018 mandates and the per-Metric exclusion counts it
requires.

**Nothing is suppressed and no threshold exists.** The worry #136 raises is real: at ADR-0009's ~12
Samples the **Prompt** Breakdown is roughly one group per Sample, and a per-group WER over one
utterance is a table of `0.0` and `1.0` that looks like data. Three things make annotate-don't-suppress
the right answer rather than the lazy one:

- **A threshold would be the cliff ADR-0004 rejected** and a configurable one would be the knob
  ADR-0010's preimage argument makes expensive — both already refused in this repo, twice each.
- **ADR-0018 already forbids the adjacent suppression.** A group whose Pooled rate is *undefined* is
  emitted anyway, with its integer counts, `null`, and its Macro exclusion disclosed. Suppressing a
  group that is merely *small* while emitting one that is mathematically undefined would be
  incoherent.
- **`1.0 (n=1)` reads as what it is.** This is ADR-0011's posture exactly — *states measurements,
  never verdicts*, on fixed absolute scales, so a quiet Recording looks quiet. A group of one, marked
  as a group of one, cannot mislead a reader who has been told its size; a group of one with its size
  hidden can.

**The Prompt Breakdown is kept for the same reason the others are.** The map's charting note is that
the Breakdown is *the only thing that makes v0.1's session metadata earn its keep*, and Prompt is the
axis that would expose a systematically hard prompt — a real finding at any corpus size above
trivial. Dropping the one axis whose groups are small by construction would answer the presentation
problem by deleting the measurement.

Group ordering is fixed and content-derived: groups sort by their attribute value ascending, never by
rate, so the bytes are stable and a diff between two Reports lines up row for row. Splits sort in
ADR-0004's order — reimplemented in the eval path, since ADR-0017 forbids importing `SPLIT_ORDER`.

### The worklist: every Sample that erred, worst-first

After the Breakdowns, the digest lists **one line per Sample with any error under Tier A**, sorted by
Tier A WER **descending**, with its `id`, its rate and its counts as evidence. Perfectly-transcribed
Samples are **counted, not listed**.

This is `render_digest`'s worklist rule transferred without modification — *"clean Recordings are
counted, not listed — the digest is a worklist"* — and it answers #136's worst-N question by making
the question disappear: **the worst Sample is the first line.** No N, no threshold, no knob, which is
the ADR-0004 posture #136 itself named as the precedent (*disclose it plainly, no thresholds, no
knobs*).

A fixed top-N was the alternative and is rejected below. The honest cost of this rule is that on a
larger corpus, where nearly every Sample carries one error, the worklist approaches the Sample count
— answered by the sort putting the worst on top, and by `--format json` for anyone processing rather
than reading. Ties sort by `id` ascending, so the order is total and the bytes are stable.

### Determinism: the Report is a pure function of the Record, the Scope and the tool

**No wall-clock, no host fact, no path, and no measured duration enters either rendering.** Given the
same Run directory, the same `--split` and the same `sdw`, both renderings are **byte-identical** on
any machine — which is what makes ADR-0021's stream-diffing goldens well-defined and what ADR-0018's
purity contract requires.

Two clarifications, because the naive reading of "no wall-clock" is wrong in both directions:

- **`score` prints no timing of its own.** ADR-0012 permitted v0.1 to print run duration *on stdout*
  precisely because stdout was not a compared artifact. Under ADR-0021 stdout **is** the artifact, so
  that permission does not transfer. It is the one v0.1 rule this ADR narrows rather than inherits.
- **Quoting `run.json`'s `started_at` / `finished_at` is not a violation.** Those are *data read from
  the Record's provenance*, fixed at the end of Transcription; a Report over the same Run reproduces
  them identically forever. Determinism here means *same inputs → same bytes*, not *no timestamps
  anywhere* — and ADR-0020 already settled that the byte-diff exclusion is scoped to files that must
  diff clean, which `run.json` never was. The header's attribution block may therefore quote the
  Run's timing; it may not report its own.

> **Amended by ADR-0024 (#149): "no host fact" means the *scoring* machine's host facts.** ADR-0024
> echoes `run.json` into the Report, which puts `host.platform_machine`, `host.platform_system` and
> `runtime.torch_num_threads` into both renderings — read literally, a head-on contradiction of the
> sentence above. It is the identical case the second bullet already resolves for timestamps: these
> are **data read from the Record's provenance**, fixed at the end of Transcription, so a Report over
> the same Run reproduces them byte-identically on any machine, forever. **Determinism is untouched
> and #138's goldens stay well-defined.** The rule, stated once and generally: *the Report may quote
> any fact the Run recorded; it may not observe a fact of its own.* That is the distinction this
> section already draws for timing, applied to the rest of the file.

### `CONTEXT.md`: two entries annotated, no term added

**Evaluation Report** gains the two renderings: a Report is one thing with a human and a machine
rendering of it, selected by `--format`, both emitted to stdout and neither persisted.

**Evaluation Run** is corrected. ADR-0021 found this and deliberately left it here, since this ticket
would be writing the replacement sentence. The entry says the two Normalizer strings *"are both
required inputs to a Run's identity"* — **stale twice over**: ADR-0020 abolished Run identity
entirely, and ADR-0020 also moved the Normalizer strings out of `run.json` because `transcribe`
writes that file and Text Normalization happens in `score`. The corrected reading is that a Run has
no identity, and the Normalizer strings are **Report-side attribution**: this ADR puts them in the
header block, where ADR-0015's requirement that *"an Evaluation Report must state which one it used"*
is actually discharged.

**One further staleness is annotated rather than left.** ADR-0018's own text still reads *"Both
strings are required inputs to a Run's identity"* — carrying the same claim ADR-0020 abolished, in
the ADR that originated it. ADR-0020 corrected `CONTEXT.md`'s neighbourhood and its own file but did
not annotate that paragraph. This ADR does, since it was writing the matching correction and this
repo's practice is to set the correction against the text it corrects.

**No term is added.** A rendering is not a domain concept, and `--format` is a flag. That the
vocabulary needed only two annotations across eight v0.2 ADRs is the same retrospective signal
ADR-0018 and ADR-0020 recorded.

## Consequences

- `sdw score --run <dir> --format json | jq` is the analysis surface: every Metric, every Breakdown
  group, and every per-Sample count, alignment and normalized text, in one document, keyed by `id`.
- A confidence interval is **computable but not printed**. If a later effort wants one, it needs no
  re-scoring and no new field — only a decision this ADR declined to make for it.
- Correlating WER against Quality flags is a `jq` join on `id` between the JSON Report and
  `reports/quality.jsonl`. It works while the dataset exists and stops working when it does not —
  the one eval question that does not survive the dataset.
- Both renderings are byte-identical given the same Run, Scope and tool version, so #138's goldens
  are two captured streams over ADR-0019's single fixture — and `score` printing any timing of its
  own is itself a testable violation, alongside ADR-0021's `score`-writes-nothing.
- The digest's shape is fixed, so a diff between two Reports shows values changing, never lines
  appearing — including at zero failures, zero `long_form` Samples, and zero errors.
- The tool never asserts that a Run is a Baseline. Every fact needed to decide it is unconditionally
  in the header.
- The map's named ceiling is now stated in a fixed sentence at the top of every Report, and measured
  beneath it as the Tier B − Tier A delta. It remains a disclosure obligation, not a solved problem.

## Rejected alternatives

**A single JSON rendering, no flag** — one output, no format decision to relitigate, and nothing to
keep in sync between two renderings. Rejected because it abandons v0.1's two-readers precedent at the
exact moment the tool produces its most-read artifact, and delivers the headline — the number the
whole map exists to produce — as a key in a blob rather than a sentence. The map's own framing is
that *a single corpus WER is one number with no story*; JSON-only makes the story `jq`'s problem.

**A digest only, with ADR-0018's counts dropped** — the smallest surface, no flag, no second
rendering. Rejected because it contradicts ADR-0018 head-on: the counts exist so later analysis needs
no re-scoring, which is a property of the split reproducibility contract the entire map was built
around.

**Both renderings concatenated into one stream** — preserves "no flag" literally. Rejected because
neither half is then consumable: `jq` chokes on the prose, and `> baseline.txt` yields a file that is
half digest and half blob. It preserves a slogan by damaging both readers.

**Adding `flags` to the Hypothesis Record so the Report can cross WER against them** — the version
that keeps the correlation available after the dataset is gone, and free today since nothing has
shipped and `record_version` would stay `"1"`. Rejected because it imports a **configurable** v0.1
quality opinion into the eval artifact — ADR-0019's own reason for refusing `duration_out_of_range` —
so two Runs over the same audio could disagree about a Sample's flags with nothing on the line
explaining why; and because a flags-vs-WER section printed by `sdw` reads as the ASR-as-dataset-QA
loop the map ruled out on the merits, needing a disclaimer every time it prints. The `id` join gives
the same answer with no field, no version bump and no disclaimer.

**A `--dataset` flag on `score` for flag enrichment** — no Record change, and the correlation lands
inside the Report. Rejected on ADR-0017: `score` never opening the dataset is what makes purity a
property *of the command*, guarantees a rebuild between the two commands cannot silently re-pair
against changed text, and reduces the Scoring golden to one fixture file.

**A bootstrap confidence interval on the headline** — the strongest form of "surface it plainly", and
free from counts already held. Rejected because the absolute CI is the wrong interval for the paired
comparison this project endorses, because overlapping intervals produce a **false no** on exactly
that comparison, and because it arrives with three arbitrary constants and is itself imprecise at
N=12. The counts remain emitted, so the interval is one decision away for anyone who wants it.

**Confidence intervals on every Breakdown group** — uniform statistical honesty. Rejected on
arithmetic: at ~12 Samples most groups are size 1–3, where the interval spans nearly the whole range,
burying the one number that matters under a table of near-useless ones.

**A fixed top-N worst-Samples section (`worst 5`)** — bounded output at any corpus size and a
scannable digest. Rejected because N is a constant with no principle behind it: the sixth-worst
Sample is invisible for no reason, and the first request would be to make N configurable — the knob
this repo has now refused in ADR-0004, ADR-0011, ADR-0016, ADR-0017 and ADR-0018. Sorting
worst-first delivers the same top of the list without inventing a cutoff.

**Suppressing or annotating Breakdown groups below a size threshold** — keeps the Prompt table from
filling with `n=1` rows. Rejected as ADR-0004's invented cliff, and as incoherent beside ADR-0018,
which emits *mathematically undefined* groups rather than hiding them. Printing the group size next
to every rate dodges both objections, which #136 itself suspected.

**Dropping the Prompt Breakdown** — the one axis whose groups are ~1 by construction on a prompted
single-speaker corpus. Rejected because it answers a presentation problem by deleting a measurement,
and because Prompt is the axis that surfaces a systematically hard prompt, which is a real finding at
any corpus size the tool will see.

**Suppressing the *rate* on `n=1` groups while showing their counts** — a middle path that withholds
only the misleading part. Rejected because the rate **is** well-defined (ADR-0018 defines it exactly),
so withholding it asserts an editorial judgment the tool has refused to make everywhere else, and it
would create a second null-like state distinct from ADR-0018's `null` — two encodings of *no number
here*, which is how they come to disagree.

**Having the Report assert Baseline status** — the tool naming what the operator most wants to know.
Rejected because `score` reads a Record and cannot tell whether the weights behind it were
unmodified, so the assertion would rest on evidence it does not have — ADR-0011's verdict line,
crossed.

**Repeating raw Reference and Hypothesis text in the JSON rendering** — self-contained rows needing no
join. Rejected because `id` already makes the join free, and because ADR-0021 records that the raw
Hypothesis is the first text in this repo carrying *what a speaker actually said*. The normalized
text is emitted because it exists nowhere else; the raw text is not, because it exists exactly one
join away.
