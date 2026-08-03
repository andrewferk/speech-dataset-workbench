# Evaluation run provenance record (v0.2)

ADR-0016 fixed *which model, run how*; ADR-0017 fixed *the surface that runs it*; ADR-0018 fixed
*what the resulting numbers mean*; ADR-0019 fixed *the artifact between them* — including the file
this ADR fills in. `run.json`'s name, its position inside the Run directory, its write-order, its
byte format and two of its fields are already decided. What remains is its **content**: whether a Run
has an identifier at all, which facts it records, and the rule by which two Runs' numbers are
legitimately comparable. It resolves #134.

The question underneath all three is that `dataset_version` cannot be copied here. A build is a pure
function, so its id is a hash of its output and *equal ids ⟹ identical content*. Transcription is
not, and ADR-0015 already refused to call a Run a Version on ADR-0010's own three promises —
content-derived, identical-from-identical, recomputable from output alone — of which a
non-deterministic model satisfies none. This ADR spends itself on what replaces the id rather than on
finding a substitute for it.

It builds on ADR-0006 (no wall-clock, host or path-outside-the-tree facts in durable output),
ADR-0010 (`dataset_version`'s promises and `dataset.json`'s shape), ADR-0015 (a Run is not a
Version; the reserved `<Thing> Record` pattern), ADR-0016 (the mandated model-identity field set),
ADR-0017 (two commands, provenance-last as the sentinel, N-of-M disclosure), ADR-0018 (no scoring
configuration exists) and ADR-0019 (`run.json` itself). It consumes #129's rule that both
`tool_version` strings are recorded and neither assumed equal to the other, and its finding that
`dataset_version` is **one-directional**.

It **amends ADR-0016, ADR-0019 and ADR-0010**, each in one place, and each noted against the text it
corrects.

## Decisions

### A Run has no identifier

**No id is minted for a Run.** Its handle is its directory name, which is #135's to decide.
`run.json` carries provenance in place of an identifier, and this ADR says so on the record rather
than leaving the field absent for a later reader to "fix".

The ticket named three candidate schemes. All three are rejected, and the reasons are worth keeping
because each looks correct in isolation.

**Input-derived — hash what determines the Run.** Stable and meaningful in the abstract: the same id
would mean *the same question was asked*. Rejected because it is a **false-yes machine**, in a repo
that has just finished arguing the direction of error. #129 accepted `dataset_version` churn
specifically because churn is a false *no* — you look, you diff, you find they match — where a stale
id is a false *yes* you never look at, and eliminating false-yes is what ADR-0010 exists for. An
input-derived run id inverts that in a file *deliberately parallel to `dataset.json`* (ADR-0019),
carrying a `sha256:`-shaped string, in a repo whose readers have been trained on exactly one
hash-shaped id and its *equal ⟹ identical content* contract. It also cannot decide what to do with
`torch_num_threads` and `attn_implementation`, which ADR-0016 **records but deliberately does not
pin**: inside the preimage they make the id machine-dependent, and outside it two identical ids
differ in floating-point reduction order.

**Output-derived — hash the Hypotheses.** The honest one, and mechanically free, since `run.json` is
written last anyway. It even restores ADR-0010's three promises in full. Rejected on what it buys: a
new id every Run communicates only that the model is non-deterministic, which ADR-0015 already states
in prose. Its real value is **integrity**, which is a different concern with a different name — and
which is rejected separately below.

**Opaque or sequential — a timestamp or counter.** Rejected as a category error: this is a naming
scheme, and naming the Run directory is explicitly #135's. Deciding it here would reach across the
seam ADR-0019 had just drawn, to answer a question this ADR is not the one asking.

The positive case for silence is ADR-0015's. It declined to call a Run a Version so that *"the
identity question stays visible and open rather than silently answered."* Answering it "there is
none, and here is why" honours that; minting any of the three would close it with a field whose
guarantee a future reader would assume and not find.

### No integrity hash over the Record

`record_line_count` (ADR-0019) remains the **only** integrity check, and no `sha256` over
`hypotheses.jsonl` is added.

ADR-0019 justified the line count narrowly and against a named failure mode: a Record truncated
*after* the Run is otherwise indistinguishable from a shorter corpus, and the outcome is *a Report
silently scoring a subset* — the one thing ADR-0017's N-of-M policy exists to prevent. A whole-file
hash defends a different class — hand-edits, bit rot — against, in ADR-0019's own words about
`content_hash` and about recomputing `prompt_id`, **a threat model this repo does not have**. That
ADR rejected two integrity mechanisms on exactly that ground; a third would be inconsistent with
both.

The second reason exists only because of the decision above: **a hash would be read as the id just
abolished.** A `sha256:`-shaped string in a file parallel to `dataset.json` *is* an identity to the
next reader, whatever key it sits under. Having decided a Run has no id, the most expensive
subsequent move is to put something id-shaped in the file.

The cost, stated: a Record whose lines were edited in place with the count preserved scores wrong,
silently. Accepted — it requires someone to open the file and edit it, and nothing in this project's
workflow does that.

### Wall-clock and host facts belong here — the exclusion was never global

v0.1 kept timestamps and host facts out of durable output, and evaluation has the opposite need:
attribution *requires* exactly the facts determinism forbade. The ticket asked for that inversion to
be stated explicitly and scoped, so that the two regimes stay legible side by side. They do, and no
truce is needed, because **the boundary is the file**.

ADR-0006 forbade wall-clock and path-outside-the-tree facts in durable output, and ADR-0019 restated
the rule *scoped to a file* — "no wall-clock, host, or path-outside-the-tree facts anywhere in
`hypotheses.jsonl`" — so that two Records of the same Dataset Version diff to model variance alone.
That property is exactly as strong when `run.json` carries what the Record may not. `run.json` was
never in the byte-diff game: ADR-0016 already put resolved library versions and a thread count in it,
both of which vary by machine.

So:

- **`started_at` and `finished_at`**, UTC ISO-8601 — **both, and not a duration**. Duration is
  derivable, and ADR-0019 refused to record derived numbers twice, *"a number recorded twice is a
  number that can disagree with itself."* *When did I run this* is the first question asked of a Run
  you did not just make, and the directory name is renameable and copyable where the file is not.
- **`platform_machine`, `platform_system`, `python_version`** — earned on the **numerics** argument,
  not the diary one. ADR-0016 records `torch_num_threads` because floating-point reductions are
  order-dependent; architecture is the other input to that same fact (arm64 against x86_64: different
  SIMD widths, different reduction trees). If thread count is worth recording for that reason,
  architecture is too — and the comparability rule below uses it.
- **No hostname, no username, no absolute paths.** No attribution value, and the one part of the
  excluded set that is genuinely identity-shaped rather than merely non-deterministic.

### `tool_version` has three occurrences, not two

#129 recorded *"one `tool_version` concept, two occurrences"* — the tool that **built** the dataset,
and the tool that **scored** it. ADR-0017 then split the seam into two commands, and the second
occurrence splits with it:

| Artifact | Written by | `tool_version` names |
| --- | --- | --- |
| `dataset.json` | `sdw build` | the tool that **built** the dataset |
| `run.json` | `sdw transcribe` | the tool that **transcribed** |
| the Report | `sdw score` | the tool that **scored** |

This is not a contradiction of #129 but a consequence of a decision taken after it: at the time #129
resolved, "the eval-time tool" was one event. Its conclusion survives untouched — record every
occurrence, assume no two match, split nothing, mint no new version string. Only the count changes.

The rule that falls out holds in all three files and is the one `dataset.json` already follows:
**top-level `tool_version` names the tool that wrote *this* file.**

**Consequence: ADR-0018's two Normalizer identity strings do not go in `run.json`.** ADR-0019 handed
them here, before this split was visible. `run.json` is written by `transcribe`; Text Normalization
happens in `score`, later, possibly under a different installed tool version, and ADR-0018's whole
design is that one Record is scored repeatedly. A Normalizer identity in `run.json` would be a fact
about an event that had not happened when the file was written. **`sdw-tier-a/1` and
`whisper-english/b80bcf6`, and the scoring `tool_version` beside them, are Report-side provenance and
belong to #136.** This ADR decides *that* they are Report-side — the comparability rule below needs
them named — and leaves their rendering to #136.

### The file

Nested blocks, not ~20 flat keys. Canonical JSON per ADR-0019, written last.

```json
{
  "record_version": "1",
  "record_line_count": 53,
  "tool_version": "0.2.0",
  "dataset": { "dataset_version": "sha256:<64 hex>", "tool_version": "0.1.0", "manifest_version": "0.1" },
  "model": { "repo_id": "openai/whisper-large-v3-turbo",
             "revision": "41f01f3fe87f28c78e2fbf8b568835947dd65ed9",
             "license": "mit" },
  "decode": { "task": "transcribe", "do_sample": false, "num_beams": 1, "temperature": null,
              "condition_on_prev_tokens": false, "return_timestamps": false },
  "language": { "value": "en", "source": "declared" },
  "runtime": { "name": "transformers", "transformers_version": "5.14.1", "torch_version": "2.13.0",
               "python_version": "3.12.7", "device": "cpu", "dtype": "float32",
               "attn_implementation": "sdpa", "torch_num_threads": 8 },
  "host": { "platform_machine": "arm64", "platform_system": "Darwin" },
  "timing": { "started_at": "2026-08-03T14:02:11Z", "finished_at": "2026-08-03T14:07:48Z" }
}
```

**Nesting is chosen for the comparability rule, not for tidiness.** #134 asked for a rule *"a human
can apply by reading two files."* Drawn along the lines the rule cares about, the blocks make it
**"these must match; those two are a caveat; that one never matters"** — applicable by eye. Flat keys
make the same rule a twenty-item checklist. Nesting also follows the precedent ADR-0019 invoked in
calling `run.json` "deliberately parallel to `dataset.json`", which is itself a file of nested blocks.

**ADR-0016's mandated field set is intact and three keys are re-spelled** — `model_repo_id` →
`model.repo_id`, `model_revision` → `model.revision`, `model_license` → `model.license`. ADR-0016
mandated *"the model-identifying fields"*, a set rather than a spelling; the re-spelling is recorded
here so the two documents can be read against each other without an apparent conflict.

Three choices inside the file that are decisions rather than layout:

- **`language` is not in `decode`, despite ADR-0016 listing it among the seven constants.** ADR-0019's
  rule applies: a fact recorded twice can disagree with itself. `decode` holds the six genuinely
  fixed constants; the seventh is `language.value`, stated once beside its `source`. Written down so
  that nobody later "restores" it to `decode` for symmetry with ADR-0016's table.
- **`dataset` quotes `manifest_version` as well as both version strings.** The eval path parses the
  Manifest as a stranger (ADR-0017), so *which Manifest schema it read* is real provenance, and it is
  the field that would explain a future parse divergence.
- **No dataset path.** Tempting for attribution — *which directory was this?* — and precisely the
  path-outside-the-tree fact ADR-0006 excludes. `dataset_version` answers it one-directionally per
  #129, and that is the honest amount.

### The comparability rule

Given two Runs, their numbers are legitimately comparable under the following, applied by reading the
files.

**Headline, and the thing that separates this rule from `dataset_version`: comparability is a
property of the question asked, never a promise about the answer.** Total equality across every tier
below does **not** promise identical Hypotheses. #127 found that no ASR runtime documents
reproducibility at all, and ADR-0015 declines to claim it. `dataset_version` promises the answer;
this rule cannot, and does not.

| Tier | Blocks | Meaning |
| --- | --- | --- |
| **Must match** | `model`, `decode`, `language.value` | Otherwise the two numbers answer **different questions**, and no comparison is legitimate |
| **Must match *or* escalate** | `dataset.dataset_version` | Equal ⟹ the same data, settled. **Unequal ⟹ nothing** — do not conclude "not comparable"; apply the escalation below |
| **May differ, must be disclosed** | `runtime`, `host`, `tool_version` | The same question under different arithmetic — floating-point reduction order. Comparable with a stated caveat |
| **Never relevant** | `timing`, `record_version`, `record_line_count` | |

**The dataset clause needs its escalation, and the escalation is available without leaving the Run
directories.** #129 made `dataset_version` one-directional: equal ⟹ the same dataset, unequal ⟹
**nothing**, because a release bump alone mints a new id over byte-identical manifests. So a rule
reading *"same `dataset_version` ⟹ comparable, different ⟹ not"* would be wrong in its second half.
#129 named manifest-byte equality as the ground truth to escalate to. Better is available here:

> **Diff the two `hypotheses.jsonl` files with the `hypothesis` and `error` columns masked. If the
> remainder is identical, the two Runs scored the same data** — whatever `dataset_version` says.

ADR-0019 put `id` — `rec_` + 16 hex of `sha256` over the Original bytes — and the verbatim
`reference` on every line, alongside every Breakdown attribute. So the masked diff *is* manifest-byte
equality, restricted to exactly what evaluation consumes, and it works when the datasets themselves
are long gone. This is a payoff of the Record being a superset, not a new mechanism.

**The rule spans three artifacts, not one.** `run.json` is not sufficient, and reading it as
sufficient is the likely error:

- **`run.json`** — the tiers above.
- **the Hypothesis Record** — the same **Evaluation Scope**, which is the term ADR-0015 minted for
  exactly this clause (*"without it the comparability rule between two Runs is unstatable — two Runs
  over the same Dataset Version are not comparable if one covered `test` and the other covered
  everything"*). Under ADR-0017's N-of-M policy, two Runs with different failure counts also Pool
  over different denominators; and a Run with failures is not an unlabelled Baseline.
- **the Report (#136)** — the same Normalizer identity. Metrics under ADR-0018's Tier A and Tier B
  are not comparable to each other, and that string is Report-side per the decision above.

### No `CONTEXT.md` change, and the reserved name goes unclaimed

No new domain terms. In particular, **ADR-0015's reserved `<Thing> Record` pattern is deliberately
not taken up as "Run Record".** Naming `run.json`'s contents would assert a second artifact at the
exact point ADR-0016 (*"not a second artifact"*) and ADR-0019 (*"neither is readable as a Run without
the other"*) spent effort denying one. The **Hypothesis Record** is the artifact; `run.json` is its
provenance file and its completeness sentinel. ADR-0015 left the slot open for this ADR to fill or
dissolve, and it dissolves.

That no vocabulary is needed is the same retrospective signal ADR-0018 recorded: the terms #126
settled were the right ones.

## Amendments to earlier ADRs

- **ADR-0016** — its model-identity table is ratified as a field *set*; three keys are re-spelled by
  nesting, and its *"#134 owns its shape and where it sits"* is now fully closed.
- **ADR-0019** — its hand-off of ADR-0018's two Normalizer identity strings to `run.json` is
  **redirected to #136's Report**, because `run.json` is written by `transcribe` before any scoring
  exists.
- **ADR-0010** — #129's amendment inside its `tool_version` section reads *"one `tool_version`
  concept, two occurrences."* That is now three. The amendment's conclusions are unchanged; only the
  count is, and only because ADR-0017 split `transcribe` from `score` after #129 resolved. The text
  is annotated where it sits, because as written it will otherwise be read as settling a question it
  predates.

Nothing here changes `dataset.json`, the `dataset_version` preimage, or any v0.1 emitted artifact.

## Consequences

- A Run is identified by where it sits, and says so. Every downstream reader — #135's retention,
  #136's Report, the fog's cross-run comparison — inherits *"there is no id"* as a decided fact
  rather than as an absence to be filled.
- `run.json` is the designated home for the facts v0.1 excluded from durable output, and
  `hypotheses.jsonl` keeps that exclusion entirely. The two regimes are separated by a file boundary,
  not by a compromise.
- The comparability rule is applicable by eye against two files, and its escalation path needs
  neither dataset to still exist.
- **#136 inherits** the scoring `tool_version` and ADR-0018's two Normalizer identity strings as
  Report-side provenance, plus the rule's third clause: a Report states which Normalizer produced its
  numbers, or the numbers cannot be compared to anything.
- **#135 inherits** the Run directory's name as the *sole* handle for a Run — a slightly heavier job
  than before, since nothing inside the directory names it.
- Anyone comparing two Runs is told, in the rule's first line, that equality of conditions does not
  promise equality of output. That is ADR-0015's attributed-not-reproducible contract restated where
  it is most likely to be forgotten.

## Rejected alternatives

**An input-derived run id** — the option the ticket leads with, and the one that looks most like the
rest of this repo. Rejected above as a false-yes machine, on #129's own direction-of-error argument,
and because `torch_num_threads` and `attn_implementation` have no correct side of the preimage to sit
on.

**An output-derived run id** — honest, free, and the only candidate that satisfies ADR-0010's three
promises. Rejected on utility: a different id every Run states only what ADR-0015 already states in
prose, and the integrity use it would actually serve is rejected separately and on its own terms.

**An opaque or sequential run id** — simple and promising nothing. Rejected as #135's decision
wearing a different hat: it is a directory-naming scheme, and this ADR is not the one naming
directories.

**A `sha256` over `hypotheses.jsonl` as an integrity field** — one line of code, catching the whole
class of post-hoc corruption that `record_line_count` misses. Rejected on ADR-0019's own threat-model
argument, used there twice, and because an id-shaped string would be read as the identity this ADR
declines to mint.

**Recording a duration instead of, or alongside, `started_at`/`finished_at`** — the number an
operator actually wants when judging whether resumption is worth building. Rejected as derived: two
timestamps yield it, and ADR-0019's rule against recording a number twice applies exactly.

**Recording hostname or username** — the completion of "attribution requires what determinism
forbade", and genuinely useful on a shared machine. Rejected because this project has one operator,
so it attributes nothing, and it is the one excluded fact that is identity-shaped rather than merely
non-deterministic.

**Flat keys matching ADR-0016's table spellings exactly** — no re-spelling to explain, and trivially
greppable. Rejected because the comparability rule is the file's main consumer and a rule stated over
named blocks is applicable by eye where a twenty-item checklist is not.

**Keeping the Normalizer identity strings in `run.json`, as ADR-0019 handed them** — the literal
reading of the hand-off. Rejected because `run.json` is written by `transcribe` and Normalization
happens in `score`: the field would describe an event that had not occurred, and would be wrong the
first time one Record was scored under a later tool version — which ADR-0018's design makes the
expected case, not an edge one.

**Taking up ADR-0015's reserved name as "Run Record"** — the slot was left open for exactly this
ticket, and the symmetry with **Hypothesis Record** is attractive. Rejected because naming it asserts
the second artifact ADR-0016 and ADR-0019 both went out of their way to deny.

**A comparability rule stated over `dataset_version` alone** — one field, one comparison, and what
the ticket's framing invites. Rejected because #129 made the id one-directional, so the rule would be
correct in its first half and wrong in its second — the precise trap #129 closed by naming
manifest-byte equality as ground truth.

**Leaving the identity question unanswered** — the leanest ADR, and defensible since nothing in v0.2
needs an id. Rejected because an absent field reads as an oversight: the next reader adds one, most
likely the input-derived variant, which is the one option that actively misleads.
