# Testing strategy for v0.2

ADR-0008 fixed how v0.1 is tested: fixtures synthesized in-repo by a single generator, unit-heavy
layering, exact goldens for the cross-machine-stable artifacts, build-twice-and-diff for the bytes
that are not stable, a table-driven abort suite, and no committed WAV or PNG goldens. It was written
for a tool with no model in it. This ADR decides how v0.2 is tested, given that its most expensive
stage cannot run in CI at all. It resolves #138.

It builds on ADR-0016 (the checkpoint is a source constant; *"no CI job reaches this code"*),
ADR-0017 (two commands; `score` reads a self-contained Record), ADR-0018 (the metric semantics and
the degenerate-input table these fixtures must hit), ADR-0019 (the Run's two files and the per-line
schema), ADR-0020 (`tool_version` has three occurrences), ADR-0021 (the Report is never written to
disk), ADR-0022 and ADR-0024 (the Report is byte-identical given the same Run, Scope and tool, and
its header quotes `run.json`), and ADR-0023 (the module split, the three import rules, and the three
CI jobs). It **amends ADR-0008** where it extends it, and takes one decision ADR-0023 explicitly
deferred here.

Two facts settle before any decision, because they change what the ticket was asking:

- **The Scoring fixture is a Run directory, not a hypotheses file.** ADR-0024 makes the Report quote
  `run.json`'s provenance into its header, so `score` reads both files ADR-0019 defines. A fixture
  carrying only `hypotheses.jsonl` cannot produce a Report at all.
- **The Scoring golden is a captured stream, not a file tree.** ADR-0021 never writes the Report to
  disk. ADR-0008's *"golden-file exact equality"* transfers intact, but the artifact compared is
  captured **stdout** — one golden per `--format`.

## Decisions

### The strategy splits on the reproducibility seam, and the halves share no mechanism

ADR-0015 named the seam and ADR-0017 built the tool on it: Transcription is attributed and not
reproducible; Scoring is a pure function of the Record. Testing inherits that split whole, and this
is the organising decision the rest follow from. The two halves do not share a fixture, a mechanism,
or a CI job's guarantees — and the temptation to unify them is the temptation to test Scoring through
something non-deterministic, which would give away the one property that makes it cheap to test
exhaustively.

### Scoring — ADR-0008 inherited wholesale, enabled by committed Run fixtures

Exact goldens, no tolerances, no per-field machinery. The enabler is **committed Run fixtures**,
which make the entire Text Normalization / metric / Breakdown / Report path testable with no model,
no weights, and no network.

**They are hand-authored, and generator-free.**

```
tests/fixtures/runs/<case>/
  hypotheses.jsonl
  run.json
  golden/
    report.txt     # captured stdout, --format text
    report.json    # captured stdout, --format json
```

ADR-0008's *"fixtures are code: parameterized, reviewable in a diff"* was an argument about **audio**,
where the alternative was an opaque binary. JSONL is already a diff, so the generator's advantage does
not carry, and its disadvantage does: a generated fixture computes its own expected values, and a
golden then proves only that the code agrees with itself.

**A fixture whose expected WER was computed by hand is a test of understanding, not of
self-consistency**, and on a learning project that is the point rather than a nicety. It is also the
only arrangement in which ADR-0018's arithmetic is checked by something other than ADR-0018's own
implementation.

**The cases are ADR-0018's degenerate-input table**, which is a specification of exactly which
fixtures must exist. At minimum: an empty normalized Reference against a non-empty Hypothesis
(per-Sample `null`, insertions pooled against a zero denominator); empty against empty (`null`, and
SER *correct*); a non-empty Reference against an empty Hypothesis (`1.0`); a WER above `1.0`,
unclamped; a `hypothesis: null` failure driving the N-of-M disclosure; a Sample where a Tier A rule
visibly fires and the Tier B delta is non-zero; and a Scope with zero total Reference tokens, which
must **refuse to emit**. The last belongs in the abort table below rather than the golden set.

**Costs, accepted.** There is no generator keeping the corner cases coherent, and a schema change
means hand-editing every fixture. Both are bounded by the fixtures being small and few — and a schema
change that is tedious to propagate is a schema change whose blast radius is visible, which is not
the worst property for a format that ADR-0019 has just frozen.

### Transcription — an internal seam and a fake, never a model

**`sdw/transcribe/` imports `transformers` in exactly one leaf module.** The CLI's dispatch branch
(ADR-0023) constructs the model there and passes it in; every other module under `sdw.transcribe` is
importable in a venv with no `asr` extra. Reading the Manifest, ordering lines by content-derived
`id`, writing `hypotheses.jsonl`, the `hypothesis: null` failure path, the `long_form` frame-count
check, and assembling `run.json` are all model-free, and all of them are tested in the **torch-free
`check` job** against a hand-written fake.

This is the correct trade because **most of Transcription is plumbing, and plumbing is the part that
breaks silently**. The model call is one function that `mypy --strict` and ADR-0016's seven explicit
constants already constrain; the write path is where line order, key order, the failure marker and
the sentinel live, and every one of those is a durable-format claim.

**The seam is internal and unreachable from the CLI.** ADR-0019 wrote that *"a slot that exists is a
slot that gets filled,"* and that objection applies here with force: a seam that took a model
identifier would be checkpoint selection by the back door, which ADR-0016 refused as a *decision*
rather than as an ergonomic. So the seam is a parameter on an internal function, not an argument, not
configuration, and not a registry. Widening it is still an ADR change.

**Why not a real model, tiny or otherwise.** Running `whisper-tiny` in CI is not a testing choice; it
is an ADR-0016 amendment that reintroduces the selectability that ADR made a source constant — and it
would buy only structural assertions anyway, because `tests/synth.py` emits tones that contain no
speech. ADR-0016 already recorded the conclusion this ADR ratifies: *"No CI job reaches this code."*

**Why not monkeypatching instead of a seam.** Patching `transformers` symbols inside `sdw.transcribe`
keeps production code slot-free, but the tests can then only run where `transformers` is installed —
moving the entire plumbing suite behind a 200 MB install, and pinning it to private names that rot on
the first refactor. The seam costs one parameter and buys the plumbing tests a home in the job that
runs on every push.

### The dataset under test is a real `build`, not a hand-authored manifest

The transcribe tests build `tests/fixtures/reference/` through the existing pipeline into a tmpdir and
point `transcribe` at the result.

This is the only arrangement in which the map's *stranger-consumer of its own manifest* claim is
**tested** rather than asserted. A committed manifest fixture would be a second copy of the Manifest
contract, maintained by hand — ADR-0008's own second-source-of-truth failure mode — and it would go
stale silently, which is precisely the failure the dogfood claim exists to catch. Building it for real
means a field drifting in `manifest.py` turns the transcribe suite red.

The cost is a full `build` per test. It is seconds, it downloads nothing, and it is the same synthetic
tone corpus the rest of the suite already uses.

### No test needs audio with known content, and that is a finding rather than a gap

`tests/synth.py` produces tones, which contain no speech, so no real ASR model could produce
meaningful output from them. The ticket asked what stands in for *"audio with known content."*

**Nothing does, and nothing needs to.** Scoring never opens audio by construction (ADR-0017/ADR-0019).
Transcription's tests stop at the seam, where the assertions are that the loader yielded a `float32`
array of the expected shape and that every Manifest line became a Record line — claims about
plumbing, not about text. The only test that would need known content is one asserting a decoded
*string*, and no such test exists in v0.2 under any of the decisions above.

Stating this positively matters, because the alternative reading — that the tones are a limitation to
be worked around — leads directly to committing real speech, which ADR-0002 and ADR-0009 forbid.

### Build-twice-and-diff does not transfer to v0.2

ADR-0008 reached for it because ADR-0005 denies cross-arch bit-exactness for Normalized WAVs and
matplotlib PNGs are not naturally byte-stable: those artifacts **could not be goldened**, so
self-consistency was the strongest available claim.

v0.2 produces no such artifact. `hypotheses.jsonl` is text with fixed key order; the Report is text
that ADR-0022 and ADR-0024 make byte-identical on any machine given the same Run, Scope and tool. Both
are goldenable, and a golden is strictly stronger — ADR-0012's *"two identically broken renders pass"*
is the whole objection to a self-diff where a golden is available. And `score` writes nothing at all
(ADR-0021), so *"is the eval output directory byte-comparable"* has no directory to ask about.

**So v0.2 adds no run-twice-and-diff of any kind.** ADR-0008's mechanism stays exactly where it is, on
the v0.1 build path, unchanged.

### The Transcription write path is pinned by a golden `hypotheses.jsonl`

The fake-backend test writes a Run into a tmpdir; `hypotheses.jsonl` is compared **byte-for-byte**
against a committed golden. That pins line order (ADR-0019's content-derived `id`, which is also
transcription order), the fixed key order, the per-line schema, and the `hypothesis: null` failure
marker — the four things a future refactor can break without breaking anything that reads them today.

**`run.json` is excluded from the golden and asserted field-wise instead.** It carries `started_at`,
`finished_at` and host facts, which are *observed* rather than read — ADR-0022's distinction, in the
one file where the tool is on the observing side of it. ADR-0020 already scoped the byte-diff
exclusion to files that must diff clean, and `run.json` was never one. Field-wise assertions cover the
sentinel's line count, the three `tool_version` occurrences, and that the nested blocks are present
and correctly shaped.

### Import-boundary enforcement, and what #138 adds to it

ADR-0023 decided the mechanism — an AST import-graph test under `tests/unit/`, parsing every module
under `src/sdw/`, tagging edges by node depth, and reporting the violating *path*. Nothing here
reopens that; it is a unit test, it lives with the unit tests, and it is structural analysis rather
than a structural impossibility, which ADR-0023 already argued is the best available for rules 1 and
3.

What this ADR adds is the condition that makes ADR-0023's **rule 2** real. That rule — `sdw.score`
imports nothing under `sdw.transcribe` — is supplied by the CI shape rather than by a check: it holds
because a module-level `import torch` under `sdw.score` is an `ImportError` in a job with no extra
installed. **That is only a guarantee if the `check` job actually runs the Scoring tests**, and until
this ADR there were none. The Scoring goldens are therefore load-bearing for an import rule as well
as for the metrics, which is a second reason they may never migrate to the `asr` job.

### CI is still three jobs, and `check` may never gain the extra

| Job | Installs | Runs |
| --- | --- | --- |
| `mise-config` | — | `mise ls` (unchanged) |
| `check` | `uv sync --locked` | the `sdw --help` smoke, `ruff`, **`pytest`** — including every Scoring golden and every fake-backend transcribe test |
| `asr` | `uv sync --locked --extra asr` | `mypy --strict`, **a leaf-module import smoke**, **the full `pytest` suite** |

ADR-0023's prohibition stands and is restated because this ADR is the one that gives it teeth:
**adding `--extra asr` to `check` would silently delete rule 2**, and now also silently delete the
proof that the Scoring path is model-free and torch-free in fact rather than in prose.

**The `asr` job gains two things, which is the decision ADR-0023 deferred here.**

- **A leaf-module import smoke** — `python -c "import sdw.transcribe.<leaf>"`. `mypy --strict` proves
  the types line up; it does not prove the import resolves, and `transformers` carries an
  `ignore_missing_imports` override (ADR-0023) that makes a wrong `from transformers import X`
  precisely the error mypy is least able to see. One line, no weights, no decode.
- **The full `pytest` suite** — because the extra-installed venv is the configuration the **operator's
  own machine is permanently in**, and no other job runs the tests there. A test that passes only in a
  torch-free venv would otherwise ship green and fail on the one machine that matters.

**Running `pytest` in `asr` does not weaken rule 2.** The guarantee comes from `check` running the
Scoring tests *without* the extra; the `asr` run is additive, and a module-level `import torch` under
`sdw.score` still reddens `check`.

**No job downloads weights and no job performs a decode**, in any configuration. ADR-0016's network
table is therefore exercised by nothing, which is named in the residue below.

### Golden churn on release is accepted, bounded by the shape of the diff

ADR-0022's header item 5 prints the **scoring** `tool_version` — ADR-0020's third occurrence, the
running tool's own version, read from `__version__`. It appears in every Report golden, so a release
bump reddens all of them.

This is #129's churn again, in a second artifact, and it is accepted for #129's reason: the churn is a
false *no* you look at, not a false *yes* you trust. v0.1 already lives with it — `golden/dataset.json`
carries `"tool_version":"0.1.0"` and `dataset_version` hashes over it.

**The release checklist gains one step with one guard**: bump `__version__`, regenerate the eval
goldens, and **the resulting diff must touch only the version-bearing lines**. A wider diff is a real
behavioural change to investigate before tagging.

The guard is the whole decision. Regeneration is unavoidable; regeneration becoming *reflexive* is
what would hollow the goldens out, and a stated expectation about the diff's shape is what keeps a
human reading it. This is also why **no `--update-goldens` flag is provided**: making the regeneration
one keystroke makes *"the golden changed"* a keystroke rather than a decision.

Two rejected alternatives, for the record. **Goldening the body and unit-testing the header** removes
the churn but splits one artifact across two mechanisms, and ADR-0022 spent its argument on the header
being unconditionally present and fixed-shape *precisely so a diff reads* — excluding it tests the
shape of the part that was never in doubt. **Substituting the version at compare time** reintroduces
exactly the per-field tolerance machinery ADR-0008 rejected for `quality.jsonl`, and costs the one
clean rule that *goldens are exact*.

### The abort table extends; the layer split does not change

ADR-0008's table-driven abort suite gains the v0.2 refusals, each asserting a non-zero exit: a
`--run` directory with no `run.json` (incomplete Run — ADR-0017's sentinel), a `--split` selecting no
Samples, and ADR-0018's Scope with zero total Reference tokens. These are Scoring aborts, so they run
in `check` with the rest.

The two-layer split is unchanged and needs no decision: metric math, Text Normalization, the Levenshtein
scorer, the Breakdown grouping and the import graph are units; a `score` invocation captured as a
stream and a `transcribe` invocation writing a Run are e2e, because a captured stream is only well
defined through the CLI.

### Layout

Extending ADR-0008's tree:

```
tests/
  synth.py                    # unchanged — audio only
  unit/                       # + Text Normalization tiers, Levenshtein, metrics, Breakdowns, imports
  e2e/                        # + score goldens, the fake-backend transcribe run
  fixtures/
    reference/                # unchanged — the committed --data-in
    runs/                     # hand-authored Run fixtures, one directory per case
      <case>/hypotheses.jsonl  run.json  golden/report.txt  golden/report.json
    transcribe/
      golden/hypotheses.jsonl # the fake-backend Run's expected Record
```

`tests/fixtures/runs/` is kept **separate** from `tests/fixtures/transcribe/golden/` for ADR-0008's
own reason for keeping the reference tree separate from `examples/`: they optimise for different
things. The hand-authored Runs optimise for hitting ADR-0018's degenerate cases; the transcribe golden
is whatever the fake produced, and encoding the edge cases into the fake to unify them would put the
expected values back inside a generator.

### `CONTEXT.md` is unchanged

Testing introduces no domain vocabulary — ADR-0008's finding, and it still holds. Fake, seam, golden
and fixture are testing terms, not domain terms.

## What v0.2 claims that nothing exercises

Named here in ADR-0012's register, as consequences of the decisions above rather than as defects.
**#139 owns the release-level unexercised list**, which is broader than testing; these are the
entries this ADR's own choices create.

- **No real decode happens anywhere in CI.** ADR-0016's seven decode constants, its greedy path, its
  language resolution and its over-length disclosure are exercised only by types and by the operator
  running the tool. This is the direct cost of the seam, and it is the cost that bought plumbing
  coverage on every push.
- **The fake can diverge from the model, and nothing can catch it.** A fake that returns strings is a
  claim about the model's interface, not its behaviour. The seam's narrowness is the only mitigation:
  the less the fake stands in for, the less there is to diverge.
- **ADR-0016's network table is unexercised.** Cold cache, warm cache, and the offline hard error are
  three decided behaviours that no job reaches.
- **No test involves real speech**, so no test can establish that a WER number is *plausible*. That is
  #139's manual-gate question, and it is the first real consequence of the privacy architecture
  (ADR-0002, ADR-0009) meeting a feature that needs speech.
- **ADR-0005's cross-architecture caveat** remains unasserted by design, inherited unchanged from
  ADR-0012's exception list.
- **This ADR is meta**, as ADR-0008 was: it *is* the suite, and there is nothing outside it to check
  it with.

## Consequences

- **`sdw/transcribe/` acquires a shape before it acquires code**: one leaf module owns
  `transformers`, the CLI branch wires it, and the rest is pure. That is a design constraint on
  unwritten code, and ADR-0012's rule applies — if an implementer finds a better factoring that
  keeps the plumbing importable without the extra, **this ADR should lose the argument, not the
  code**.
- **The Scoring goldens are load-bearing twice**: for the metrics, and for ADR-0023's rule 2, which
  exists only while they run in a job with no extra installed.
- **Releases gain a step.** Bump, regenerate, read the diff. Unenforced by CI, and named in the
  checklist so it is not rediscovered as a red suite.
- **`examples/` is untouched by this ADR.** Whether the example corpus grows an eval story is #139's
  question 2, which asks it with the privacy-architecture framing that makes the answer worth
  recording. What this ADR supplies is its inputs: hand-authored Runs are a demonstrated artifact,
  `check` is torch-free, and no CI job downloads weights.
- **Nothing here changes a Metric, a byte `transcribe` writes, or any decision of ADR-0016 through
  ADR-0024.**

## Amendments to ADR-0008

- **The fixture-generator rule is scoped to audio.** ADR-0008's *"`tests/synth.py` is the sole home
  for all fixture creation"* stands for every WAV the suite uses. Text fixtures — Hypothesis Records
  and Run provenance — are hand-authored, because the argument for a generator was that binaries
  cannot be reviewed in a diff, and JSONL can.
- **"Golden files are exact" now covers a captured stream.** ADR-0008's goldens are files on disk;
  ADR-0021 makes the Report a stdout stream, so the Scoring goldens compare captured output. The rule
  is unchanged — exact equality, no tolerances — only the capture is new.
- **Build-twice-and-diff does not extend to the eval path**, and this is deliberate rather than an
  omission. See the section above.
- **The CI section gains a second job and a prohibition.** ADR-0008 describes one suite in one job;
  ADR-0023 split CI into three, and this ADR fixes what runs in each. `check` may never install the
  `asr` extra.
- **Coverage stays measured, not enforced**, unchanged.

## Rejected alternatives

- **A `tests/hypsynth.py` Run generator**, mirroring ADR-0008's single-generator rule — rejected: it
  would compute the expected values it is meant to check, converting every golden from a test of the
  arithmetic into a test of the code's agreement with itself.
- **Capturing fixtures from a real `transcribe` run** — rejected: the tones contain no speech, so the
  captured Record could not contain a WER above 1.0, a firing Text Normalization rule, or any case chosen
  rather than observed; and re-capturing would need a 1.6 GB download.
- **A tiny model in CI with structural-only assertions** — rejected: it requires ADR-0016 to
  reintroduce checkpoint selectability, adds weights to every run, and still asserts nothing about
  content because the audio has none.
- **No transcription tests at all, as a documented gap** — rejected as the genuine runner-up. It is
  the most literal reading of ADR-0016's *"no CI job reaches this code"* and costs nothing. It was
  rejected because the write path it leaves uncovered is pure, cheap to test, and the sole
  implementation of a format ADR-0019 has just frozen.
- **Monkeypatching `transformers` with the tests in the `asr` job** — rejected; see above.
- **Reusing the fake-backend Run as the Scoring fixture** — rejected: one artifact cannot optimise for
  both *"whatever the plumbing produced"* and *"the exact degenerate cases ADR-0018 enumerated."*
- **A `--update-goldens` pytest flag** — rejected: it makes a golden change a keystroke rather than a
  decision.
- **Excluding the header from the Report golden** — rejected; it tests the shape of the part that was
  never in doubt.
