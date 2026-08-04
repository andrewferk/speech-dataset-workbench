# v0.2 acceptance criteria & the demonstration problem (#139)

We fix what "v0.2 is done" means, and answer the question the map could not settle until every other
decision had landed: **what demonstrates a feature whose input is real speech, in a project whose
architecture forbids real speech from existing anywhere it could demonstrate it?**

This is the last decision on the v0.2 map. It consumes ADR-0015–0025 and amends ADR-0009, ADR-0012,
ADR-0021, ADR-0024 and ADR-0025. Like ADR-0012 before it, it adds no product behavior: everything
here is a check, a document, a fixture, or a constraint on when work may land.

ADR-0012 is the direct precedent, and this ADR applies its **lesson** rather than its text. That
lesson was not the four-item list — it was that *the list of things nothing exercises was the real
product*, and that writing the list down is what made most of its entries cheap enough to just fix.
That happened again here, and the *Unexercised list* section below is this decision's substantive
output for the same reason.

## Decisions

### The demonstration: a genuine Run over the tones

`examples/` ships a committed **Evaluation Run** — `hypotheses.jsonl` and `run.json` — produced by
running `sdw transcribe` once, with ADR-0016's pinned `openai/whisper-large-v3-turbo`, against a
build of the committed `examples/data-in`. `sdw score --run examples/<run-dir>` is then a real
demonstration: one command, no downloads, and — by ADR-0023 — no `asr` extra and no torch.

The ticket framed the choice as three bad options: put real speech in the example (ADR-0002 and
ADR-0009 forbid it), commit **fabricated** hypotheses no model produced (honest about being fake,
but then it demonstrates Scoring and not Evaluation), or ship no runnable example at all. The fourth
option is better than all three, and the reason is that **it is not fake**. A model really ran. The
Record is attributed and provenance-stamped exactly as ADR-0015 requires, and the seam ADR-0017 was
built around is demonstrated rather than described.

The audio is still tones, so **the numbers will be garbage** — Whisper over a sine tone emits
hallucinated text or nothing at all. That is the content, not the flaw. It demonstrates, on a corpus
committed to git:

- **ADR-0018's never-clamp rule**, which otherwise appears only in prose and a unit fixture;
- **ADR-0017's runaway-decoding failure mode**, named there as *the likeliest failure on
  atypical or near-silent audio* and until now unseen;
- **ADR-0015's split contract** — the expensive stage ran once, and its output is now re-scorable
  forever at zero cost by anyone with a clone.

This is ADR-0009's own move. That ADR chose exactly one Recording below the `low_volume` knob so the
included-and-flagged policy would demonstrate itself, and ADR-0012 generalized it: *"a demo
displaying none of them would run clean and teach nothing."* A demo whose WER is a believable 4%
would be a demo that had quietly acquired speech from somewhere.

**The committed Run makes the example's evaluation half fully deterministic** — more so than its
build half, which still carries ADR-0005's cross-architecture caveat. The Record is frozen in git
and Scoring is byte-identical, so the Report is reproducible on every machine. The one stage that
ADR-0015 says can never be reproduced has been run once and retained, which is the Original/Normalized
relationship a third time.

### `transcribe` has no runnable example, and cannot

This is a **negative result**, recorded as such, and it is the first real consequence of the privacy
architecture meeting a feature that needs real speech.

`sdw transcribe` can be demonstrated over tones — that is how the committed Run is produced — but
there is no example that shows it doing its actual job, because doing its actual job requires speech,
and ADR-0002 makes captured audio external by construction while ADR-0009's allowlist keeps it out
of git. No amount of documentation closes this. The honest statement is that **the expensive half of
v0.2 is undemonstrable and the cheap half is fully demonstrable**, which is not a coincidence: it is
the same asymmetry ADR-0017 built the entire command surface on, showing up one layer out.

Synthesizing speech with TTS was the tempting escape — generated audio, so ADR-0009's allowlist would
permit it — and it is rejected in *Considered and rejected* below.

`examples/README.md` must say this plainly, in the register ADR-0009 established for *"the audio here
is generated tones, not speech"*: the reader is told before they meet the numbers that they are
about to see an Evaluation of non-speech, what that means, and why no better example can exist.

### Check 4 — the example Run matches the example dataset

ADR-0017 made `score` read **only** the Run, never the dataset — the property that makes purity
belong to the command. The consequence for `examples/` is that the committed Run is **fully
decoupled** from `examples/data-in`. Edit `examples/generate.py`, the tones change, every `id`
changes — and `sdw score --run examples/<run-dir>` still succeeds, still prints a well-formed
Report, and now teaches a dataset that does not exist.

Nothing in the repo catches this. ADR-0009's drift test regenerates and byte-compares WAVs and never
invokes evaluation. ADR-0012's Check 1 builds the examples and knows nothing of a Run. ADR-0025's
Scoring goldens run against `tests/fixtures/`, a different corpus. This is ADR-0012's Check 1
argument arriving one release later — *the demo still builds, and teaches the wrong thing* — so it
takes the same answer.

CI builds `examples/data-in/` and asserts, as **named assertions**:

- the set of `id`s in `hypotheses.jsonl` **equals** the set of `id`s across the built Manifest —
  the Run covers every Sample and no others
- for each `id`, the line's `reference` **equals** that Sample's `prompt_text`

The second is the one that earns its keep: a `recordings.csv` prompt edit changes no audio, so it
slips past ADR-0009's byte-compare entirely, and it changes the very text the example's WER is
measured against.

**Not `dataset_version`.** ADR-0012 declined to assert it in Check 1 because `tool_version` is in the
preimage, so every release would break the check for reasons unrelated to the example — *churn that
trains people to update goldens without reading them* — and #129 ratified that refusal. `run.json`
records the `dataset_version` it transcribed, and nothing compares it against today's; per #129,
unequal ids imply nothing, so an assertion would be false-positive machinery by construction.

**Named assertions, not a golden**, for ADR-0012's reason verbatim: `example_run_covers_every_sample`
failing says what broke; a diff says line 7 differs and invites regeneration.

The cost is that this check builds the examples, making it slower than the tones drift test, and it
makes `examples/`'s two halves editable only together. That coupling is the mechanism, not a side
effect — the same sentence ADR-0012 wrote about the audit recipe existing twice.

### Check 5 — the example Report says what the example teaches

Because the Run is committed and Scoring is byte-identical, a **golden is available here** in a way
it was not for the build half. It is declined.

ADR-0025 already goldens captured Report streams over `tests/` Run fixtures, and those goldens verify
**the scorer**. A second golden over `examples/` would cover the same code path a second time, add no
coverage, and churn on every release — ADR-0020 established the scoring `tool_version` is a third
occurrence and ADR-0022 puts it in the Report header, so the golden changes at every version bump.
ADR-0025 accepted that churn once, under a bounded-diff release rule, in exchange for pinning the
scorer. Buying it twice for nothing is the wrong trade, and ADR-0012 rejected precisely this artifact
— a golden `examples/summary.txt` — because *"a golden's failure names a line number, not a broken
claim."*

So CI runs `sdw score` against the committed Run and asserts, as named assertions, what the example
exists to **teach**:

- both Normalizer tiers appear with their identity strings, and the **B−A delta** is present —
  ADR-0018's headline argument made visible in the one place a reader will meet it
- the **N-of-M** line prints **even when N = M** — ADR-0022's fixed-shape rule demonstrating itself
  rather than being asserted about a fixture
- the per-Split Breakdown is present, with its group sizes

One assertion **cannot be specified here**: whether the headline Tier A Pooled WER exceeds 1.0.
Turbo over a sine tone may hallucinate a sentence (well past 1.0) or emit `""` (exactly 1.0, all
deletions). Which one happens is a fact about the model, discoverable only by running it. That
assertion is therefore **written from observed output**, which is ADR-0012's rule for
`examples/README.md` applied to the check that guards it — and it is the reason this ADR can fix the
demo's *shape* but not its *content*.

The ADR-0021 property that `score` writes nothing stays in `tests/` where ADR-0025 put it: it is a
property of the command, not of the example.

### The manual gate — once, before `v0.2.0`

ADR-0012 used a one-time gate and rejected a standing one as theater. Both halves of that hold here,
and the case for the gate is **stronger** than it was at v0.1.

The ticket proposed the gate as *"are these WER numbers plausible for this speech?"* — and after the
demonstration decision, that question **cannot be asked of anything in the repository**. The example
has no speech. Your own recordings are, by ADR-0002, not in git and never will be. So the question
has exactly one possible venue, and it is a human at a terminal.

What v0.2 ships without, stacked up:

- no CI job downloads weights or decodes (ADR-0025);
- Transcription is tested behind an internal seam **with a fake**, and ADR-0025 names as its sharpest
  residue that *the fake can diverge from the model and nothing can catch it*;
- the committed example Run is real model output over **tones** — it proves the model was invoked and
  the artifact is well-formed, and proves nothing whatever about recognition.

So the real-model-over-real-speech path — ADR-0016's seven decode constants, the pinned sha, the
explicit processor surface, the licence read from the fetched artifact, the preflight, the whole
chain — is exercised by **nothing, ever**, unless a human does it once. That is structurally the same
hole ADR-0012 found for image legibility, where *build-twice-diff proves two renders match and two
identically broken renders pass*, and it takes the same answer.

Before `v0.2.0` is tagged, a human runs `sdw transcribe` and `sdw score` against their own real
prompted recordings and confirms:

1. **`transcribe` completes end-to-end** and the Run directory is well-formed — the first and only
   occasion the real model, real weights, real decode constants and the real preflight run together.
2. **The headline Tier A Pooled WER is plausible** for careful read speech from an unmodified turbo.
   Deliberately not a threshold — a threshold is a knob, and ADR-0018 refused one for this reason.
   `0.0` means References leaked into Hypotheses; `1.5` means something is structurally broken.
   Neither is detectable by any check that ships.
3. **The worklist's top entries are legible** as either recognition error or speaker deviation. This
   is the map's named ceiling — WER against the Prompt conflates the two — inspected exactly once by
   the only instrument that can see it: a human who knows what they said. ADR-0022 deliberately
   declined to print a verdict about it, so nothing else will ever ask.
4. **The non-determinism floor is measured.** Transcribe the same corpus **twice** under identical
   provenance, `diff` the two Reports, and record the resulting delta as a scalar. See below.

The gate is **not standing**, for ADR-0012's reason unchanged: a gate someone is supposed to run
before every release is a gate that gets skipped, and a skipped gate is worse than none because the
document still claims it happened. v0.1's gate confirmed a spec produced a *legible artifact*; this
one confirms a spec produced a *believable number*.

It does not close ADR-0025's residue. It **inspects it once**, at the tag, after which the residue
stands and is listed below as such.

### The gate measures the non-determinism floor

ADR-0024 named an **unmeasured run-to-run non-determinism floor** and made it a debt on v0.3: a
cross-run delta is paired by Sample but *not* exact, because the Hypotheses differ both from the
model change and from the same model's own variance, so a delta beneath that floor means nothing
while looking like a result. Its stated recipe is to transcribe twice under identical provenance —
single-digit minutes at ~12 Samples.

That recipe has exactly one place it can run. CI never loads the model; the example has no speech;
ADR-0024 itself observed that a floor measured on synthetic tones *describes nothing*. The gate is
the only occasion in this project's life when the real model meets real speech, so the floor is
measured there or it is not measured at all — and the next opportunity after the tag is unscheduled.

The cost is one extra `transcribe`. The output is a scalar, not an utterance, so it carries none of
the privacy weight discussed below and may be recorded on the gate's issue. **This discharges the
debt ADR-0024 handed forward**, and ADR-0024 is amended to point here.

### Done delegates; it does not enumerate

v0.2 is **done** when:

1. **Everything ADR-0012 required still holds** — stated by reference, not restated. Its Checks 1–3,
   its structural constraint, and its release mechanic are unchanged except where amended below.
2. **CI is green across all three jobs** — `mise-config`, `check`, and ADR-0023's new `asr` job.
3. **Checks 4 and 5 pass**, and the four fixtures below exist.
4. **The manual gate has been walked once**, all four items.
5. **`v0.2.0` is tagged.**

There is deliberately **no ADR-indexed checklist** pairing ADR-0015–0025 with observables. ADR-0012
rejected one as *"a second source of truth that drifts from day one"*, and the objection is
**stronger** here: 0015–0025 amend each other more aggressively than 0001–0011 did — ADR-0017 amends
0006; ADR-0018 amends 0017; ADR-0020 amends 0010, 0016 and 0019; ADR-0022 amends 0017, 0018 and 0021;
ADR-0024 amends 0022 in three places. A table summarizing eleven documents that actively rewrite one
another would be wrong before it was committed, and nothing checks a checklist against its sources.

Behavioral completeness stays the ADRs' job to specify and ADR-0025's suite's job to verify. This
ADR's content is only what those two do not cover.

**Coverage claim:** every ADR 0015–0025 is exercised by ADR-0025's suite or by a check here, except
those named in *The unexercised list*.

### Release mechanic

`pyproject.toml` carries `version = "0.2.0"`; `tool_version` reads it, in all three of the
occurrences ADR-0020 identified. When every item above holds, **tag `v0.2.0`**. No PyPI and no
changelog, carried unchanged from ADR-0012.

**No new version string is introduced anywhere**, and this is written down so nobody reconciles it at
release time:

- `manifest_version` stays `"0.1"` — ADR-0017 established it does not move through v0.2.
- `record_version` stays `"1"` — ADR-0019 made it an opaque counter *deliberately decoupled from
  release cadence*, having found `manifest_version` to be a release-shaped string tracking no
  release. v0.2 is the first opportunity to get that wrong a second time.
- **`dataset_version` churn is expected and accepted.** #129 settled it: a rebuild after the tag
  mints a new id for byte-identical manifest bytes, the contract is one-directional (equal ids imply
  the same Dataset Version; unequal ids imply nothing), and the churn is a false *no* rather than a
  false *yes*.

### A Baseline is not required to exist

v0.2 is done when the tool **can** produce a Baseline, not when one has been produced and recorded.
The map calls the baseline the primary product and the gate produces one as a side effect, so the
pull toward requiring a recorded number is real. It is refused on two grounds.

**The tool already refuses it.** ADR-0021 writes no Report to disk and ADR-0022 never prints the word
"Baseline", because *Baseline is a reading an operator applies* and `score` cannot know the weights
were unmodified. A definition of done requiring the repository to hold a Baseline would make the
project assert exactly what its own tool spent two ADRs declining to assert.

**And committing one is a privacy breach.** This is the second consequence of the privacy
architecture meeting evaluation, and unlike the first it is a **trap rather than a limitation**.
ADR-0021 found that `hypotheses.jsonl` is the first artifact `sdw` produces containing *what a
speaker actually said* rather than the authored Prompt. ADR-0022 then put a **worklist of the Samples
that erred, with their normalized text**, into the digest. So committing the gate's Report — the
natural thing to do with a number you want to keep — puts real utterances into git. That is the one
failure ADR-0012 called irreversible, arriving through a door the allowlist did not watch, because it
is a `.txt` file and not a `.wav`.

### Check 2 grows to cover `hypotheses.jsonl`

ADR-0012's privacy allowlist asserts that tracked `*.wav` files are a subset of `examples/data-in/`
and `tests/fixtures/`. It is extended: **tracked `hypotheses.jsonl` files must be a subset of
`examples/` and `tests/fixtures/`.**

**ADR-0021 rejected this, twice**, and this ADR overturns that rejection rather than quietly working
around it. Its objections were that broadening is the format-policing ADR-0012 already refused, and
that it *"would forbid #138's committed `hypotheses.jsonl` Scoring golden on the day it landed, a gate
written and holed in one commit."*

Both objections assume the check is a **prohibition**. It is not — ADR-0012's Check 2 is an
**allowlist**, and under an allowlist a committed golden is not a hole, it is an entry. The
format-policing objection was aimed specifically at `.mp3`/`.m4a`: *input* formats the tool
hard-aborts on, where the check would conflate a privacy breach with a bad input. `hypotheses.jsonl`
is neither — it is an artifact `sdw` emits, whose privacy content ADR-0021 itself was the first to
identify. ADR-0021 reasoned about a shape the repository does not use; the shape it does use fits.

The change is not free of judgment, and the honest statement of what it buys is narrow: it catches
the **realistic accident** — someone commits a Run directory from the gate, or from their own corpus,
because it is a few kilobytes and looks like test data. Now that `examples/` holds a committed Run
too, the allowlist has two legitimate entries rather than one, which strengthens rather than weakens
the case: the rule has to be written down somewhere, and an allowlist is where the conversation
happens when someone has a legitimate reason to add a third.

What it does **not** catch is a redirected Report. ADR-0021 established the operator's
`> baseline.txt` is honestly **theirs**, so it has an arbitrary filename and no rule can distinguish
it from prose. That is unpoliceable by construction and is listed as an accepted exception below,
which is the honest form.

### The unexercised list

The substantive output, in ADR-0012's register. Writing it down is what revealed that four entries
were cheap enough to close.

**Closed on the spot — these become fixtures under ADR-0025's Scoring suite:**

- **`record_line_count` truncation.** ADR-0019 made it the *only* integrity check available to a
  stage forbidden to reach outside its Run, existing to prevent a Report silently scoring a subset.
  ADR-0025's fixture list derives from ADR-0018's degenerate-input table, which is about scoring
  math — so nothing currently hands `score` a truncated Record. One fixture.
- **The missing-`run.json` sentinel.** ADR-0019 spent its crash-safety argument establishing the
  write order; nothing exercises a Run that crashed before the sentinel landed, which is the exact
  state ADR-0021 then decided to let accumulate on disk. One fixture.
- **A non-zero `long_form` count.** ADR-0022 requires it printed even at zero, and every existing
  fixture prints zero — so the branch that *reports* an over-length Sample is unexercised while the
  branch reporting its absence is goldened. One fixture line.
- **A `hypothesis: null` failure reaching the N-of-M disclosure.** ADR-0017's policy exists because
  the Samples likeliest to fail are the quiet, atypical, hard ones, and ADR-0019 kept every attribute
  on a failed line precisely so the Report can say *which* Sessions lost Samples. One fixture that
  actually loses one.

**Accepted exceptions — named here rather than solved, so a future reader meets them as decisions
instead of rediscovering them as bugs:**

- **The fake can diverge from the real model, and nothing can catch it.** ADR-0025's own residue,
  restated because it is the largest thing v0.2 does not verify. No CI job downloads weights or
  decodes, so ADR-0016 in its entirety rests on the one-time gate. Unlike ADR-0012's exceptions, this
  one grows with the project: every future change to the transcribe path inherits it.
- **A redirected Report is unpoliceable.** See above. The privacy allowlist covers the artifact
  `sdw` names and cannot cover the one the operator names.
- **ADR-0020's comparability rule is human-applied.** By decision, not omission — ADR-0024 recorded
  that nothing enforces it, and that a tool declining to print numbers because it judged two Runs
  incomparable would be issuing a verdict on a rule whose own first line concedes that equal
  conditions do not promise equal output.
- **`pip`-on-Linux with CUDA torch is supported but untested.** ADR-0023 accepted it on the record:
  `[tool.uv.sources]` is uv-only, so CI proves a resolution no `pip` user performs.
- **ADR-0021's no-prune policy** — the absence of a feature; there is nothing to check.
- **ADR-0012's own accepted exceptions** carry forward unchanged: ADR-0005's cross-architecture
  caveat, ADR-0008/0025 being meta, and the `uv.lock` dependency convention.

### Ordering: everything here lands after the implementation

Every artifact this ADR specifies depends on a tool that does not yet exist. The committed Run must
be produced by the real `transcribe`; Checks 4 and 5 run against it; `examples/README.md`'s
evaluation section must be written from **observed output**, which is ADR-0012's rule applied to
itself for the third time; the gate runs the real model.

So this ADR specifies work that lands **after** the v0.2 implementation, in the same position #152's
documentation pass occupies — and `examples/README.md`'s evaluation section is **#152's**, since
ADR-0025's sibling decision already made that issue the owner of writing-from-observed-output and it
is blocked on the same thing. #144 parked `examples/README.md` on this ticket because its *"one
command, no downloads"* heading had gone false; the heading is now **true again** for `score`, which
needs neither the `asr` extra nor weights, and the file's repair belongs with the rest of the doc
pass.

## Consequences

- "v0.2 is done" becomes checkable rather than felt, and `v0.2.0` is the event that makes it so.
- `examples/` gains a second half and becomes a demonstration of **four** commands. Its evaluation
  half is byte-reproducible everywhere, which its build half is not.
- CI gains two checks; the privacy allowlist gains a second file type; ADR-0025's suite gains four
  fixtures; `pyproject.toml` gains a version. **No product behavior changes.**
- The two halves of `examples/` become editable only together — Check 4 is that coupling.
- The project acquires its first artifact that is *deliberately garbage*: an Evaluation whose numbers
  are meaningless by construction, committed because the meaninglessness is the lesson.
- **v0.3 inherits a measured non-determinism floor** rather than ADR-0024's open debt, and inherits
  the knowledge that measuring it again requires the same manual occasion.
- `CONTEXT.md` is unchanged; this ADR introduces no domain vocabulary — the fourth consecutive
  evaluation ADR for which that is true, and by now a signal rather than a coincidence.
- The wayfinding map is decision-complete: no open product, architecture, data-model or tooling
  decision stands between here and implementing v0.2.

## Considered and rejected

- **TTS-synthesized speech in `examples/`** — the tempting escape, and permitted on its face:
  ADR-0009's allowlist says captured audio never enters git while *generated* audio may. Rejected on
  three grounds. It buys a demo of `transcribe` at the price of a **new heavyweight dependency or a
  second committed binary artifact nobody can regenerate**, against a repo whose fixtures are
  synthesized in-repo precisely so they are reviewable (ADR-0008). It would produce a *plausible-looking*
  WER over speech that is clean, synthetic and unlike the atypical-speech population this product
  exists for — the same silent inversion that got ASR-as-dataset-QA ruled out, arriving as a
  flattering number instead of a flag. And `transcribe` would still need the `asr` extra and a
  1.6 GB weights download, so the demo it buys is **not** the one-command-no-downloads demo the
  example is for. The negative result is more useful than a misleading positive one.
- **Fabricated hypotheses committed as if scored** — the ticket's option 2. Honest about being fake,
  but demonstrates Scoring rather than Evaluation, and forfeits the one thing the real Run provides
  for free: proof that the model was actually invoked through the real surface.
- **No runnable evaluation example at all** — the ticket's option 3. Defensible, and strictly worse
  than the Run: it discards a demonstration that costs one commit and teaches three ADRs.
- **A golden Report for `examples/`** — available for the first time, since the Run is committed and
  Scoring is byte-identical. Rejected: it duplicates ADR-0025's coverage of the same code path while
  churning on every `tool_version` bump, and ADR-0012 already rejected this exact artifact.
- **Asserting `dataset_version` in Check 4** — looks like the strongest possible binding between Run
  and dataset. It is false-positive machinery: `tool_version` is in the preimage, and #129 established
  that unequal ids imply nothing.
- **A standing evaluation gate before every release** — theater, per ADR-0012, and now worse: the
  gate requires real speech that only one person has.
- **Requiring a recorded Baseline in the definition of done** — makes the project assert what
  ADR-0021 and ADR-0022 refuse to, and puts real utterances into git via ADR-0022's worklist.
- **Leaving ADR-0021's allowlist rejection standing** — the conservative option, and it costs one
  realistic accident going uncaught. Rejected because ADR-0021's argument was about a prohibition,
  not about the allowlist the repo already runs.
- **Broadening the allowlist to `run.json` as well** — `run.json` contains no speaker-derived text;
  adding it polices a file with nothing to protect and dilutes a rule whose force comes from
  covering exactly the artifacts that can leak.
- **An ADR-indexed checklist of 0015–0025** — rejected for ADR-0012's reason, which the amendment
  density of this arc makes considerably stronger.
- **Deferring the non-determinism floor to v0.3, as ADR-0024 assigned it** — correct on paper.
  Rejected because the measurement has exactly one venue, that venue is being visited once, and v0.3
  will need a v0.2-era number it will have no way to obtain.
- **Creating the v0.2 implementation issue set in this ADR** — the map's destination asks for a spec
  *and* an issue set, but decomposing eleven settled ADRs into `ready-for-agent` issues is execution,
  not a decision, and burying it here would make this ADR the place people look for a task list.
  It is the act that closes the map, taken next.
