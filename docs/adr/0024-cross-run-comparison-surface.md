# Cross-run comparison surface (v0.2)

ADR-0020 stated the rule by which two Runs' numbers are legitimately comparable — four tiers over
`run.json`'s nested blocks, spanning three artifacts. ADR-0021 made Runs accumulate side by side and
made `score` write nothing, so two Runs genuinely exist on disk and neither carries a stale Report.
ADR-0022 fixed what the Report contains. This ADR answers the question the map left in fog behind all
three: **does v0.2 ship any surface for comparing two Runs, and if so what?** It resolves #149.

The answer is that it ships one, and it is a **header change**. No fifth command, no second `--run`,
no comparison section, no new flag, and no configuration on either evaluation command.

It builds on ADR-0011 (measurements, never verdicts), ADR-0015 (Run, Evaluation Report, Baseline,
attributed-not-reproducible), ADR-0017 (four commands, `transcribe`/`score` as halves of one act,
Scope label, N-of-M disclosure), ADR-0018 (the Tier B − Tier A delta and why it is exact), ADR-0020
(the comparability rule and its escalation), ADR-0021 (Runs accumulate; the Report is a stdout stream
and `score` is read-only) and ADR-0022 (the header block, the two renderings, no confidence interval).
It consumes #128's finding that the 95% CI is 6–11 points wide at twelve utterances.

It **amends ADR-0022 in three places** and rules a future comparison feature out of scope. Nothing
here changes a number, a Metric, a Scope, or any byte `transcribe` writes.

## The gap this closes

ADR-0021 set a high bar, and it was right to. Because `score` emits the Report to stdout and writes
nothing, comparing two Runs is already `diff <(sdw score --run A) <(sdw score --run B)` with **zero
machinery**, under **one** tool version on both sides — which ADR-0021 notes is *strictly more
comparable* than reading two persisted Reports would have been. ADR-0022 then strengthened it further
than #149 knew: `--format json` is a single document with fixed key order, byte-identical given the
same Run and Scope, and the digest's shape is invariant so *"a diff between two Reports shows values
changing, never lines appearing."* Two ADRs have independently optimised for diffing two Reports.

Against that bar, a comparison surface has to beat `diff`, not merely exist. **It does not have to,
because `diff` does not currently work.**

ADR-0022 enumerates the header block as exactly five items: Scope, N-of-M, the Reference, the
comparability rule, and Attribution — where Attribution is *"both Normalizer identity strings and the
scoring `tool_version`."* **Model identity is not in that list**, and neither is `decode`,
`language.value`, `runtime` or `host`. Those are precisely ADR-0020's **tier 1** — the *must match,
otherwise the two numbers answer different questions* tier — plus the whole of its *may differ, must
be disclosed* tier.

So today, `diff` of a `whisper-tiny` Report against a `whisper-large-v3-turbo` Report renders clean,
well-formatted and byte-stable, shows a large WER delta, and **names neither model**. The diff is
silent on the one condition that makes the comparison illegitimate. Worse, header item 4 *prints the
comparability rule as prose* — so the Report instructs the reader to check something it does not show
them.

This is not ADR-0022 being wrong; it is ADR-0022 not being the ticket that asked. It was scoped to
the contents of a **single** Run's Report, ADR-0020 had just moved the Normalizer strings Report-side,
and "attribution" was reasonably read as *the strings #134 sent here*. Cross-run comparison was still
fog. This is the ticket that asks, and closing the gap is the whole of what v0.2 ships.

## Decisions

### The Report echoes `run.json`

Every Evaluation Report carries the Transcription provenance of the Run it scores. The Report was
already the only artifact carrying Scope and Normalizer identity; adding the third makes it the
sufficient artifact for applying ADR-0020's rule.

This earns its place on **single-Run** grounds independently of any comparison. *Which model produced
this number* is a question you ask of one Report, and `CONTEXT.md` already defines an Evaluation
Report as carrying *"its Metrics, its Breakdowns, and the provenance attributing them"* — a promise
the Report did not keep.

**This is not ADR-0019's forbidden "recording a number twice."** ADR-0022 settled the identical case
for timestamps: those are *"data read from the Record's provenance, fixed at the end of
Transcription"*, and a Report over the same Run reproduces them identically forever. The Report is
not durable, is a pure function of the Run, and nothing reads it back. `run.json` stays authoritative.
Echoing is **quotation**, not a second record, and the two cannot disagree because only one of them is
written.

### JSON echoes it verbatim; the digest reorganises the header into ADR-0020's tiers

The two renderings want different things, and they get different things.

**JSON carries `run.json` whole and unaltered under one key.** Not a projection, not a re-nesting, not
a curated subset — the same blocks under the same names in the same order ADR-0020 fixed. ADR-0020
chose nested blocks *specifically* so the rule reads as *"these must match; those two are a caveat;
that one never matters"* over named blocks. Reproducing them unaltered means **ADR-0020's tier table
applies to the Report without translation**, and a diff scoped to that key *is* the tier check.

A curated subset was the alternative and is rejected below: it needs a second relevance decision that
will drift from ADR-0020 the first time a field is added, leaving two places to update and ADR-0020's
table quietly no longer describing the Report.

**The digest reorganises the header so ADR-0020's tier names are the section headings**, with the
facts beneath them:

```
Transcription conditions — must match to compare
  model      openai/whisper-large-v3-turbo @ 41f01f3f (mit)
  decode     transcribe · greedy · temperature=null · no prev-cond · no timestamps
  language   en (declared)
Dataset — must match, or escalate to a masked diff of the two Records
  dataset_version  sha256:9f2a…c418
Disclosed — may differ; the same question under different arithmetic
  runtime    transformers 5.14.1 · torch 2.13.0 · py 3.12.7 · cpu · float32 · sdpa · 8 threads
  host       arm64 · Darwin
  tool       built 0.1.0 · transcribed 0.2.0 · scored 0.2.0
```

Verbatim would have been the smaller amendment, and is rejected because a digest exists to be read:
the tier labels turn the rule from a paragraph sitting beside unlabelled facts into the structure the
facts are printed under. An operator holding two of these applies ADR-0020 by reading down the left
column, which is exactly what #134 asked for when it wanted a rule *"a human can apply by reading two
files."*

**Header item 4 shrinks rather than vanishes.** The tier labels absorb its tier content; what stays as
prose is Scope equality, ADR-0017's rule that once a model has trained on `train` only `test` is
honest, and the paired-delta sentence — rewritten below. ADR-0022's other four header items are
unchanged and stay unconditionally present.

**`record_version` and `record_line_count` ride along in the JSON echo**, being part of the file.
They are ADR-0020's *never relevant* tier, already labelled as such, and dropping them would be the
curation this decision refuses. The digest omits them: `record_line_count` is already discharged in
the header as N-of-M.

### Nothing is enforced, and that is a decision

`score` machine-checks no part of the comparability rule. There is no tier-1 hard error, no loud
caveat, and no comparison mode in which one could fire.

#149 asked what a tier-1 mismatch should do. The question dissolves once no comparison surface is
built: **`score` only ever sees one Run**, so there is nothing to compare it against and no mismatch
to detect. The rule stays human-applied, precisely as ADR-0020 stated it — *"applied by reading the
files."*

This is recorded rather than left silent, because an absent enforcement mechanism reads as an
oversight and the next reader adds one. It is also the right answer on this repo's own terms: a tool
that refused to print numbers because it judged two Runs incomparable would be issuing the verdict
ADR-0011 refused for Images, on a rule whose own first line says equality of conditions **does not
promise** equality of output.

### A cross-run delta is paired, but not exact

ADR-0018 emits the Tier B − Tier A delta as a first-class number because comparing two scorings of
the **same** Hypotheses is exact: the Hypotheses are byte-identical, only the Normalizer moved, so the
delta is fully attributable and carries no randomness at all. ADR-0022 then declined a confidence
interval partly by extending that to the comparison the destination exists for — *"paired on an
identical corpus"*, citing #128's *"pure, paired, and carries no sampling error at all."*

**That extension overclaims, and this ADR corrects it.** A cross-run delta is paired by Sample — same
`id`s, same References, so corpus-composition variance genuinely cancels, and that is worth a great
deal. But the Hypotheses differ, and they differ from two causes at once:

1. **the model changed** — the thing you are trying to measure; and
2. **the same model's run-to-run non-determinism** — which this repo has three times refused to claim
   away. ADR-0015 makes Transcription attributed-not-reproducible; #127 found **no runtime documents
   reproducibility at all**; and ADR-0020's rule opens by saying total equality across every tier does
   not promise identical Hypotheses.

Nobody has measured (2). The floor beneath a cross-run delta — what you would see re-transcribing the
same Dataset Version with the same model under identical provenance — is **unmeasured**, and a v0.3
delta smaller than it would mean nothing while looking like a result. That is a false *yes* of exactly
the kind #129 spent a ticket ruling against.

So the honest statement, and the one the Report's header carries and the documentation repeats: **a
cross-run delta is exact as a description of these two Runs, paired at the Sample level, and rests on
a floor that has not been measured.** Measuring it costs one extra `transcribe` — single-digit minutes
on ADR-0009's ~12-Sample corpus — and the operator is told to do it before trusting a delta.

**This does not reopen ADR-0022's no-CI decision; it strengthens it.** ADR-0022 rejected a bootstrap
CI because the absolute interval describes a statistic this project does not use and invites a false
*no* on the paired comparison. Both arguments survive intact. What changes is that the honest
quantity is not a bootstrap on either absolute number — it is an **empirical floor the operator
measures on their own corpus**, needing no resample count, no seed and no percentile method, and
therefore free of the three arbitrary constants ADR-0022 objected to.

**It cannot be a CI acceptance criterion.** ADR-0009's `examples/` ships synthetic tones containing no
speech, so a Transcription of them produces meaningless output and a floor measured over them would
be a number about nothing. This is an operator instruction, not a test.

### The comparison lives in `diff` and `jq`, documented as a recipe

v0.2 ships **no additional surface**. Comparing two Runs is:

- **the conditions** — `diff` of two Reports, which after the echo is a complete application of
  ADR-0020's rule; and
- **the paired per-Sample deltas** — a `jq` join on `id` across two `--format json` Reports.

The second half deserves stating because it is why no comparison command is needed. ADR-0022 puts one
row per Sample, keyed by `id`, carrying its integer counts under both tiers; two Reports over two Runs
of the same Dataset Version have the **same `id` set in the same fixed order**. The paired data is
therefore already in hand, one `jq` invocation away, in exactly the shape ADR-0022 named when it wrote
that *"`sdw score --run <dir> --format json | jq` is the analysis surface."*

A comparison command would not be providing **access** to paired data. It would be providing an
**opinion** about how to summarise it — over a delta whose floor is unmeasured — which is the knob
this repo has refused in ADR-0004, ADR-0011, ADR-0016, ADR-0017, ADR-0018 and ADR-0022.

**#144 inherits the recipe**, including ADR-0020's escalation for unequal `dataset_version`: the
masked diff of two `hypotheses.jsonl` files with the `hypothesis` and `error` columns removed, which
is `jq` on the same two files and needs neither dataset to still exist.

### The three clauses now land in one stream

ADR-0020 warned that *"the rule spans three artifacts, not one — `run.json` is not sufficient, and
reading it as sufficient is the likely error."* After this ADR the **Report** is:

| ADR-0020 clause | Where it lands in the Report |
| --- | --- |
| `run.json`'s four tiers | the echo — verbatim in JSON, tier-organised in the digest |
| the same Evaluation Scope, with failures and `long_form` | header items 1 and 2, unconditionally printed |
| the same Normalizer identity | header item 5 |

All three, on both sides of a `diff`, under one tool version. This is a stronger outcome than a fifth
command would have produced, and it arrives as a header change.

**One exception, stated so the table does not imply otherwise:** the Report is sufficient to *apply*
the rule, not to *discharge its escalation*. Unequal `dataset_version` still sends the operator to the
two `hypotheses.jsonl` files, because the escalation is a masked diff of the Records and the Report
carries no raw text by ADR-0022's own decision.

### Determinism survives, and ADR-0022's phrasing needs narrowing

ADR-0022 requires both renderings to be byte-identical on any machine given the same Run, Scope and
tool. The echo puts `host.platform_machine`, `host.platform_system` and `runtime.torch_num_threads`
into the Report — and ADR-0022's determinism section reads *"no wall-clock, **no host fact**, no path,
and no measured duration enters either rendering."*

Read literally that is a head-on contradiction. It is the identical case ADR-0022 already resolved for
timestamps: these are **data read from the Record's provenance**, fixed at the end of Transcription, so
a Report over the same Run reproduces them byte-identically on any machine, forever. Determinism is
untouched and #138's goldens stay well-defined.

What needs narrowing is the sentence. The exclusion is on **the scoring machine's** host facts — the
same distinction ADR-0022 drew when it allowed the header to quote the Run's timing while forbidding
`score` to report its own. Stated once, generally: **the Report may quote any fact the Run recorded;
it may not observe a fact of its own.** ADR-0022 is annotated accordingly, because without it the next
reader finds a contradiction rather than a rule.

### No new command, no new flag, no configuration

The surface remains `sdw transcribe --dataset <dir> --eval-out <dir>` and `sdw score --run <run-dir>
[--split <name>] [--format text|json]`. ADR-0021's *"neither evaluation command has any
configuration"* — as amended by ADR-0022 to admit `--format` as a rendering selector — stands
untouched. This ADR adds nothing to either command line.

### `CONTEXT.md`: one entry annotated, no term added

**Evaluation Report** is annotated: the provenance attributing a Report's Metrics now includes the
Transcription provenance of the Run it scores, quoted from `run.json` — so a Report states its Scope,
its Normalizers **and** its conditions, and is sufficient to apply ADR-0020's comparability rule
against another Report.

**Breakdown** is deliberately untouched. Its *"a diagnostic view of a **single** Run's numbers, never
a comparison between Runs"* and its `_Avoid_: comparison` remain exactly true — this ADR adds no
comparison to the Report, only the facts that let a reader compare two of them by hand.

**No term is added.** There is no Comparison in this domain, and inventing one would name a feature
this ADR declines to build.

## Amendments to earlier ADRs

- **ADR-0022** — three annotations, each set against the text it corrects. **(1)** Its five-item header
  block gains the Transcription provenance and its item 4 shrinks, the tier labels having absorbed the
  tier content. **(2)** Its *"paired on an identical corpus"* justification borrows #128's exactness
  claim, which holds for two scorings of the **same** Hypotheses and not for two Runs; the no-CI
  decision is unaffected and the reasoning is corrected. **(3)** Its *"no host fact enters either
  rendering"* is narrowed to the **scoring** machine's host facts, on the distinction it had already
  drawn for timestamps.
- **ADR-0021 and ADR-0018** are untouched. This ADR adds no flag, so the no-configuration property
  holds as those ADRs state it.

Nothing here changes `run.json`, `hypotheses.jsonl`, `dataset.json`, any Metric, or any v0.1 artifact.

## Consequences

- `diff <(sdw score --run A) <(sdw score --run B)` is a **complete** application of ADR-0020's
  comparability rule. The tool ships a cross-run comparison surface and it is two shell redirections.
- A Report that omitted its model could compare two different models and look rigorous doing it. It
  cannot any more, and the fix costs no command, no flag and no number.
- The Report becomes the sufficient artifact ADR-0020 said `run.json` was not — for applying the rule.
  Its escalation still needs both Records, which is the one thing that does not fit in one stream.
- `score` remains read-only, pure, and single-Run. It never sees two Runs, so it never judges their
  comparability, and ADR-0011's measurements-never-verdicts line stays uncrossed.
- **#144 inherits** the recipe: `diff` for conditions, `jq` on `id` for paired per-Sample deltas, the
  masked-Record diff for the `dataset_version` escalation, and the instruction to measure the
  non-determinism floor by transcribing twice under identical provenance.
- **#138 inherits** goldens that change **shape, not value** — the digest's header grows a fixed block
  and the JSON grows one key. Both remain byte-identical across machines, and the shape is invariant,
  so it is one golden re-capture rather than a new class of test.
- v0.3 inherits a Report sufficient to apply the rule, a documented recipe, and an **unmeasured
  non-determinism floor** that any delta feature must characterise before it can claim a delta means
  anything.
- The map's cross-run fog closes. A comparison **command** is out of scope for v0.2's destination.

## Rejected alternatives

**Shipping nothing at all, as a scope ruling** — the option #149 leads with, and the honest case for it
was strong: v0.2 produces **one** Baseline, so the second operand does not exist until v0.3, and
building a comparison against a hypothetical is how you get the wrong shape. Rejected because the gap
above is real *today*, on a single Report, and because "ship nothing" would have been quiet rather than
honest: it would have left `diff` — the surface two ADRs had already endorsed — unable to detect a
tier-1 mismatch, while the header printed the rule it could not apply.

**A fifth command, `sdw compare --run A --run B`** — honest about being a new act rather than smuggling
a mode onto `score`. Rejected on #8's own standard for `verify`. ADR-0017 broke the two-command spine
into four by splitting **one act** in half at a natural artifact seam and explicitly framed
`transcribe`/`score` as *halves of one act* rather than peers of `build`; a comparison is not half of
anything. It would also be the first command whose output is an opinion about a delta whose floor is
unmeasured.

**A second `--run` on `score`** — no fifth command, reuses the existing entry point, and the smallest
CLI change that ships a real comparison. Rejected because it makes `score` stop being the other half
of `transcribe` and grow its first genuine mode — a command that means two different things depending
on how many times a flag appears — and because it buys nothing: ADR-0022's per-Sample rows already put
the paired data one `jq` join away, so the flag would deliver an opinion, not access.

**A comparison section inside the Report** — no new command and no new flag, which is superficially
the shape this ADR chose. Rejected because it would require `score` to open a second Run, which ends
the property ADR-0021 spent a section establishing: `score` reads exactly one Run directory and writes
nothing. It would also make every Report either carry an empty section or vary its shape, and
ADR-0022's fixed-shape rule exists precisely so a diff shows values changing rather than lines
appearing.

**A curated subset of `run.json` — tier 1 and tier 3 only** — the leanest echo, dropping `timing`,
`record_version` and `record_line_count` as *never relevant*. Rejected because it is a second
relevance decision layered on ADR-0020's, and the two will drift: the first field added to `run.json`
lands in the file and not in the Report, and ADR-0020's tier table quietly stops describing the
Report. Verbatim has one rule — *the file, whole* — and no maintenance.

**Tier-organised in both renderings** — maximum consistency, and it would make the JSON self-describing
too. Rejected because re-shaping `run.json`'s blocks into tier groups means a diff of the Report's
provenance no longer lines up with the file it came from, and ADR-0020's table would need translating
to apply to the machine surface. The digest can afford the reorganisation because it is read; the JSON
cannot, because it is diffed.

**Verbatim in both renderings** — the smallest amendment to ADR-0022, one rule for both renderings and
nothing to keep in sync. Rejected because the digest exists to be read and would carry tier-4 noise
while leaving the rule as prose beside facts a reader must map onto it by hand. The tier headings are
the whole reason the digest becomes self-applying.

**Machine-checking the rule and hard-erroring on a tier-1 mismatch** — the strongest anti-false-yes
move available, and what #149 asks under its item 3. Rejected because it presupposes the comparison
command rejected above: `score` sees one Run and has nothing to check against. Had a command existed,
it would still have been rejected on ADR-0011 — a tool refusing to print numbers because it judged two
Runs incomparable is a verdict, on a rule whose first line concedes that equality of conditions does
not promise equality of output.

**Printing a cross-run delta anywhere in the Report** — the number an operator most wants. Rejected
because the Report scores one Run and has no second operand, and because the delta's floor is
unmeasured: a printed delta smaller than the noise it sits on is a false *yes* the reader never checks.

**Declaring cross-run deltas dishonest at ~12 Samples and refusing to document them** — the strongest
anti-false-yes position on the delta itself. Rejected as the disclosure this repo does not make: ADR-
0004's posture is *surface it plainly, no thresholds, no knobs*, and refusing to document a comparison
the operator will perform anyway removes the caveat rather than the comparison.

**Measuring the non-determinism floor in CI as an acceptance criterion** — it would turn the caveat
into a number the project owns. Rejected because ADR-0009's `examples/` is synthetic tones containing
no speech, so a floor measured there describes nothing; and measuring it on a real corpus is the
operator's own act on their own data, which is what the recipe instructs.

**Leaving the echo to #136 as an ADR-0022 defect and shipping nothing here** — defensible, since the
gap is a single-Run provenance omission and would need fixing whatever #149 decided. Rejected because
it splits one decision across two tickets: the reason the echo is worth the amendment is the cross-run
rule, the form it takes is chosen by ADR-0020's tiers, and #149 is the ticket holding both.
