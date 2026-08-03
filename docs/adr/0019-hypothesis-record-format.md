# Hypothesis Record format (v0.2)

ADR-0016 fixed *which model, run how*; ADR-0017 fixed *the surface that runs it*; ADR-0018 fixed
*what the resulting numbers mean*. This ADR fixes the artifact between them: the files a Run
directory holds, the per-line schema of the Hypothesis Record, how a failure is written, what order
the lines are in, and what makes the file's *shape* deterministic even though its *content* is not.
It resolves #133.

The Record is the load-bearing seam of v0.2. It is the durable, expensive product of the
non-deterministic stage and — since ADR-0017 — the **sole** input to the deterministic one, so it
answers to two masters: rich enough that re-scoring never needs the model again, and clean enough
that Scoring is a pure function of it.

It builds on ADR-0001 (content-derived ids), ADR-0003 (the completeness-sentinel pattern), ADR-0006
(the canonical Manifest line, its `recording_id`-ascending order, and the shared JSON byte format),
ADR-0007 (`duration_out_of_range` as a *configurable* soft flag), ADR-0015 (Hypothesis, Reference as
a role, Hypothesis Record, Run), ADR-0016 (the over-length disclosure and the model-identity field
set) and ADR-0017 (self-contained Record, incremental write, provenance last, failures distinct from
empty Hypotheses). It consumes #129's rule that both `tool_version` strings are recorded and neither
assumed equal to the other. It **amends ADR-0017 in one place**: the hand-off of "the layout inside
it" to #135 is narrowed to the Run *directory*, not its contents. It also annotates `CONTEXT.md`'s
**Hypothesis Record** entry, whose "alongside" is now two files rather than one line.

Two questions the ticket asked are answered before the decisions begin, because upstream ADRs
already closed them and restating them as open would invite relitigating a settled thing:

- **Is the Record self-contained, or does Scoring re-read the dataset?** Self-contained. ADR-0017
  decided it, and this ADR only spends the field list that decision requires.
- **Is the Hypothesis normalized before it is written?** Never. ADR-0018 runs **two** Normalizers
  over it at Scoring time; baking either in would destroy the re-score payoff the seam exists for.

## Decisions

### The Run directory holds two files this ADR owns

```
<run-dir>/
  hypotheses.jsonl   # the Hypothesis Record — appended as Transcription proceeds
  run.json           # provenance, and the completeness sentinel — written last
```

`hypotheses.jsonl` names its contents rather than its role, following `quality.jsonl`'s precedent
(ADR-0003) — the report is the lines, so there is no `_record` suffix to add. `run.json` is
deliberately parallel to `dataset.json`: a descriptor beside the data it describes, written last, and
the thing whose absence means *incomplete*.

**ADR-0017 is amended here.** Deciding `score --run <run-dir>`, it wrote that pointing at a directory
"leaves the layout inside it to #135." That hand-off is narrowed to the Run **directory** — its name,
its position under `--eval-out`, retention across Runs, and #136's Report file, all of which remain
#135's. The two files above are named here instead, for one reason: ADR-0017's own crash-safety
decision couples their existence, their write-order and their semantics, so a spec that fixed the
Record's format while leaving its filename to a later ADR would hand #135 a decision it could only
rubber-stamp — and would leave this ADR unimplementable without reading one not yet written.

### One Record file, not one per Split

The Record covers the **entire Dataset Version** in a single file, with `split` on every line.

Mirroring v0.1's `train/val/test.jsonl` was the obvious move and is a false friend. Those three files
exist because ADR-0003 buckets `audio/<split>/` for Hugging Face `audiofolder` to auto-detect — a
physical constraint on the *dataset* with no analogue in a Run directory that contains no audio.

Against that, three costs. ADR-0017 refused a Scope flag on `transcribe` precisely so narrowing
happens at the free end of the seam; three files would re-materialize that same narrowing in the
filesystem, at the expensive end, one `ls` away from being mistaken for it. `score --split` is a
filter over a field either way, so per-Split files buy the operator nothing they don't already have.
And ADR-0017 bought "the entire Scoring path needs **one fixture file**" — three files make that
three, on the path whose whole claim is that it is cheap to test exhaustively.

### The per-line schema

Fixed key order, one Sample per line:

```json
{"id":"rec_1a2b3c4d5e6f7081","reference":"The quick brown fox.","hypothesis":"the quick brown fox","error":null,"split":"train","session_id":"2026-07-14-quiet","speaker_id":"spk_a","prompt_id":"prm_9f8e7d6c5b4a3021","device":"iphone-15","environment":"quiet-room","duration":3.214,"long_form":false}
```

| Field | Value |
| --- | --- |
| `id` | the Sample's `id` from the Manifest — `= sample_id = recording_id` (ADR-0001/0006) |
| `reference` | the Reference text, **verbatim** — v0.1's `text`, the Prompt (ADR-0015's role) |
| `hypothesis` | the Hypothesis **as emitted**, raw and unnormalized; `null` iff Transcription failed |
| `error` | `null`, or a code from a closed vocabulary — v0.2 defines exactly one, `decode_failed` |
| `split` | `"train"` / `"val"` / `"test"`, carried from the Manifest line |
| `session_id`, `speaker_id`, `prompt_id`, `device`, `environment` | carried verbatim from the Manifest line |
| `duration` | seconds of the Normalized WAV, as the Manifest records it |
| `long_form` | `true` iff this Sample's frame count exceeds 480 000 (ADR-0016) |

**`reference`, not `text`.** ADR-0015 spent an amendment narrowing `Reference` from a rejected
synonym to an evaluation **role**, and this is the artifact that role exists for: `reference` and
`hypothesis` sitting side by side is the pair every scoring library and every paper is written in,
at the one seam ADR-0015 identified as the most expensive place to mistranslate. Reusing v0.1's
`text` would put the *dataset's* word on an evaluation artifact and leave the role unnamed exactly
where a Report has to state which text filled it.

**`speaker_id` and `duration` ride along beyond ADR-0017's mandated minimum.** ADR-0017 named four
Breakdown attributes and speaker is not one, because ADR-0009's corpus is effectively single-speaker
today. It is included anyway, on ADR-0017's *own* argument for transcribing every Split: *a
Hypothesis you did not generate costs a full model run to obtain; one you generated and did not score
costs nothing.* A **field** omitted from the Record costs exactly the same full model run to recover,
so the Record is a superset for the same reason the Run is. `duration` earns its place twice over —
it is what makes ADR-0016's over-length check answerable without opening a WAV, and it is the only
continuous attribute that could ever explain a Breakdown. Both are bytes; neither is a model run.

**What is deliberately absent**, each for its own reason:

- **`audio_filepath`** — Scoring has no audio by construction, and a dataset-relative path in a Run
  directory is an invitation to resolve it.
- **`content_hash`** — redundant. See *Binding*, below.
- **`lang`** — uniform across the Run (ADR-0016 reads it once from `[manifest].lang`), so it is
  run-level provenance, not per-line data.
- **`perceived_text`** — the firewall. ADR-0015 makes it bidirectional and ADR-0017 withdrew
  ADR-0006's prediction that v0.2 would populate it. A slot that exists is a slot that gets filled;
  the Record does not offer one.
- **Per-Sample wall-clock, decode time, or host facts** — forbidden by ADR-0006 in durable output,
  and precisely what would stop two Records of the same corpus from diffing to model variance alone.
- **Per-segment timestamps, token logprobs, confidence scores** — ADR-0016 already rejected these for
  v0.2. Nothing here reopens it.

### Binding to the dataset — recorded, and it needs no new field

The ticket asked how the Record records *what it transcribed* precisely enough that scoring it
against the wrong dataset is impossible or detectable. Two findings reshape the question rather than
answering it as posed.

**The guard is already structural.** ADR-0017 put the Reference on the line, so `score` never opens a
dataset. There is no second artifact for a mismatch to occur between — in ADR-0017's words, *"here
the question never arises."* Whatever the Record records about its source is therefore
**attribution**, not a safety check.

**The binding is already free.** ADR-0001 and ADR-0003 make `id` = `rec_` + the first 16 hex of
`sha256` over the **Original file bytes**. The identifier *is* a content hash: a line already names
the exact audio it transcribed, and two lines with the same `id` transcribed the same bytes.
`prompt_id` does the same for the Reference text. This is stated explicitly rather than left as a
property to be rediscovered, because a future reader adding a "binding field" would be adding a
second copy of something `id` already carries.

So: **no new per-line field.** `dataset_version` and the *build-time* `tool_version` are read from
the dataset's `dataset.json` and recorded run-level in `run.json`, per #129 — both strings, with the
eval-time `tool_version` beside them, and **neither assumed equal to the other**. Nothing is checked
at score time.

### Failures — `hypothesis: null`, and one closed-vocabulary code

ADR-0017 fixed that a per-Sample Transcription failure is soft, recorded explicitly, and kept
**distinct** from an empty Hypothesis. This ADR fixes the shape.

**The line is present.** A failure is never an absent line. Beyond ADR-0017's wording, absence is
load-bearing for resumption below: if a failure were written as absence, a resumed Run could not
distinguish *not yet attempted* from *attempted and failed*, and would either retry failures forever
or never retry a genuine gap.

**`hypothesis: null` is the sole marker.** `""` is the model's output — the model saying nothing —
and `null` is the absence of an output. This is ADR-0018's argument one ticket later and unchanged:
*a `null` propagates as an absence where `0.0` or `inf` propagates as a lie.* A separate boolean or
`status` enum was available and is rejected: a second field that must agree with the first is a
drift hazard with no compensating information, and the distinction ADR-0017 demanded is already
total.

**`error` carries a code from a closed vocabulary, never free text.** v0.2 defines exactly one,
`decode_failed`, because ADR-0017 moved every other failure — unreadable audio, unparseable Manifest,
unresolvable weights, zero Samples — into the preflight as a hard error before the model loads. What
remains soft is the model call raising. The vocabulary is closed for a determinism reason, not a
tidiness one: ADR-0006 records that `quality.jsonl` is byte-stable exactly because *"every field is
hash-derived or drawn from a fixed ASCII vocabulary"*, and forbids "path-outside-the-tree facts" in
durable output. An exception's `str()` carries absolute paths and sometimes addresses, which would
make two Records of the same corpus undiffable — destroying the property the whole *Determinism*
section below exists to protect. The exception's detail goes to stderr and to the Report's N-of-M
disclosure, where it is read once and not retained.

**A failed line carries every other field** — Reference, all five attributes, `duration`,
`long_form`. ADR-0017 requires the Report to state N of M loudly and warns that the Samples likeliest
to fail are the quiet, atypical, hard ones; a Report that cannot say *which Sessions and devices lost
Samples* has disclosed a count and hidden the pattern.

### Line order, and how it survives incremental append

**Lines are ordered by `id` ascending, globally across all Splits — and that is also the order
Transcription processes them in.**

Determinism of the file's *shape* and ADR-0017's incremental write are in tension only if the final
order differs from the append order. Making them the same order dissolves it, and pays three times:

- **No sort pass** at the end of an expensive stage.
- **A crashed Record is a valid prefix**, not an unordered fragment — which is what makes the
  resumption below free rather than a rewrite.
- **The eval path never needs a Split order.** ADR-0017 states as a positive rule that the evaluator
  "imports nothing from `sdw.manifest` or `sdw.provenance` — including `SPLIT_ORDER`", and notes the
  shortcut "is one import away and looks harmless." A single total order over `id` means there is
  nothing to import: the evaluator merge-reads the three per-Split Manifests, each already sorted by
  `recording_id` (ADR-0006 as amended by #28), and never has to decide which Split comes first.

Grouping by Split first was the human-scannable alternative and is rejected on that last point: it
puts `SPLIT_ORDER` back on the critical path to buy an ordering `score --split` already provides.

### Determinism of the file, given non-deterministic content

The *content* of `hypothesis` is not reproducible — ADR-0015 says so, ADR-0016 declines to claim
otherwise, and nothing here changes that. The file's **shape** is, so that a diff between two Runs
over the same Dataset Version shows model variance and nothing else:

- **Fixed key order**, the table above, not alphabetical.
- **Lines ordered by `id`**, ascending, as decided.
- **Canonical JSON bytes** from `sdw.serialization` — compact separators, `ensure_ascii=False`, no
  `sort_keys`, LF-terminated, no trailing whitespace.
- **No wall-clock, host, or path-outside-the-tree facts** anywhere in `hypotheses.jsonl`.
- `duration` reproduces the Manifest's rounding (3 decimals, ADR-0006) rather than recomputing it.

**The eval path imports `sdw.serialization`, and this does not weaken ADR-0017's boundary.** That
rule forbids reaching into `sdw.manifest`/`sdw.provenance` to *interpret the dataset* — the
stranger-consumer dogfood, whose point is that an under-specified Manifest gets caught by the code
reading it. Byte-formatting the eval path's **own output** is not that, and re-deriving the format
would recreate the exact failure ADR-0006 was written to stop: writers had already drifted on
`ensure_ascii` before anyone noticed, and *"that drift could not fail a test — each artifact has its
own golden, so two files disagreeing about how to spell a character reads as two intentional
baselines rather than as a bug."* The Record carries verbatim Prompt text, which is the artifact
where that bites hardest. `sdw.serialization` is a dependency leaf importing only stdlib `json`, so
it costs the torch-free Scoring path nothing.

### `long_form`, and why it is not `duration_out_of_range`

ADR-0016 requires the evaluator to compute per Sample whether the frame count exceeds 480 000, record
it on the line, and warn at Run level with the count. The field is **`long_form`**.

Reusing v0.1's `duration_out_of_range` was the tempting consistency and is rejected because the two
flags are not the same fact. ADR-0007's flag fires against a **configurable** threshold that defaults
to 20 s and expresses an opinion about dataset quality. `long_form` fires against Whisper's **fixed**
30 s window boundary and expresses which decode regime produced this Hypothesis. A dataset built with
`duration_max_s = 45` makes them disagree routinely, in both directions. One name for two thresholds
would assert an identity that does not hold, in an artifact whose job is disclosure.

`over_length` was the other candidate. `long_form` is preferred because it names the regime — the
thing actually being disclosed, and the term Whisper's own documentation uses — rather than implying
the Sample is too long for something, which ADR-0016 explicitly denies by including it.

### `run.json` — the sentinel, plus two facts about the Record

`run.json` is written **last**, in canonical JSON, and is ADR-0017's completeness sentinel: `score`
hard-errors on a Run directory without one, naming it incomplete.

ADR-0016 wrote that `CONTEXT.md` "places the provenance of a Run on the **Hypothesis Record**, which
carries it alongside each Hypothesis" and that the provenance record is "not a second artifact." Both
readings survive, and the second is worth stating precisely: ADR-0017 had already made provenance a
*file* when it made it the sentinel, and this ADR only names it. `hypotheses.jsonl` and `run.json`
are one Run directory and one artifact in the sense ADR-0016 meant — neither is readable as a Run
without the other, and `score` refuses a Record whose sentinel is absent. What is rejected is only
the *placement* ADR-0016's wording suggests, per-line or header-line, and it is rejected on
ADR-0017's own crash-safety argument rather than on preference. `CONTEXT.md`'s **Hypothesis Record**
entry is annotated accordingly.

**#134 owns its content** — the model-identity table ADR-0016 mandates, #129's version strings,
ADR-0018's two Normalizer identity strings, and whether a Run has an *id* at all.

> **Amended by ADR-0020 (#134): the Normalizer strings do not go here.** `run.json` is written by
> `sdw transcribe`; Text Normalization happens later, in `sdw score`, possibly under a different
> installed tool version — and ADR-0018's design is that one Record is scored repeatedly. A
> Normalizer identity in `run.json` would describe an event that had not happened when the file was
> written. `sdw-tier-a/1` and `whisper-english/b80bcf6`, and the *scoring* `tool_version` beside
> them, are **Report-side provenance and belong to #136**. The same split makes #129's "two
> occurrences" three: built, transcribed, scored. ADR-0020 also answers the last item — **a Run has
> no id**; its handle is its directory name, which stays #135's.

This ADR fixes only
the file, its write-order, its byte format, and two fields that are properties of the **Record's
format** rather than of the Run's provenance:

- **`record_version`: `"1"`** — the per-line schema's version, incremented only when that schema
  changes. It is an opaque counter, **deliberately decoupled from the tool's release cadence**.
  The dotted, release-shaped alternative was available and is rejected on evidence already in the
  repo: `manifest_version` is `"0.1"` and ADR-0017 records that it **stays** `"0.1"` through v0.2 —
  a string shaped like a release that does not track releases, and therefore a question ("shouldn't
  this be 0.2 now?") that gets asked repeatedly and answered wrong once. Declaring a version at all
  follows v0.1's own precedent, which put `manifest_version` beside `tool_version` in one file rather
  than making a reader map tool version to schema through a table that does not exist.
- **`record_line_count`: an integer** — the number of lines `hypotheses.jsonl` is expected to hold,
  which is the number of Samples in the Dataset Version, failures included. `score` **hard-errors
  when the file disagrees with it**, naming the Record truncated. The name says *lines of the
  Record*, not *Samples transcribed*, because the two diverge the moment a resumption mechanism
  exists and only the first is checkable without leaving the Run directory.

That last one is the only integrity check available to a stage that may not reach outside its Run
directory, and it upgrades the sentinel from *the writer reached the end* to *the file is complete
and here is the check*. Without it, a Record truncated **after** the Run finished — a full disk, a
partial copy, an editor — is indistinguishable from a shorter corpus, and the failure mode is a
Report that silently scores a subset. That is the one outcome ADR-0017's N-of-M policy exists to make
impossible, so leaving the loophole open on the other side of the seam would be inconsistent.

Failure and `long_form` counts are **not** duplicated into `run.json`. `score` derives them from the
Record, and a derived number recorded twice is a number that can disagree with itself.

### Resumption — the format guarantees it; v0.2 does not build it

ADR-0017 handed resumption here as the right instrument for a Dataset large enough that a full
Transcription hurts, in preference to a `--split` flag on `transcribe`. **v0.2 builds no resumption
mechanism.** ADR-0017 mints a fresh Run directory per invocation, so there is no entry point, and
ADR-0009's corpus of ~12 Samples at ADR-0007's ≤20 s is single-digit minutes of model time.

What this ADR does is guarantee the format never has to change to gain it. Four properties, all
decided above for their own reasons and none added for this one:

1. Append order **is** final order, so an interrupted Record is a valid prefix.
2. `id` is a **total order over content-derived ids**, so "what is already done" is a set-read of the
   prefix, requiring no index and no second file.
3. The sentinel already distinguishes an **incomplete** Run from a complete one.
4. A failure is a **present line**, so "not attempted" and "attempted and failed" are distinguishable
   — the distinction a resumption policy is built on.

**One gap is named rather than left to be discovered.** ADR-0017's phrasing — *"a re-run skips
Samples already transcribed under identical provenance"* — is **unsatisfiable as the artifacts now
stand**, because `run.json` is written last, so an incomplete Run carries no provenance to compare
against. The fix is a durable start-time provenance file promoted to `run.json` on completion, or an
equivalent. It is recorded here because it costs nothing to state and would otherwise be found late,
and because it changes **no per-line field** — the Record's schema is not what stands in the way.

## Consequences

- A Run directory is self-describing and self-contained: two files, one of which is the sentinel, and
  neither referring to anything outside the directory.
- Scoring's entire input is one file. ADR-0017's single-fixture golden test (#138) is now concrete:
  one `hypotheses.jsonl` plus one `run.json`, no dataset tree, no WAVs, no torch, no network.
- The Record is a **superset** in both dimensions — every Sample, and every attribute a Breakdown
  could want — so any Scoring view conceived later is a re-read, never a re-run.
- Two Records of the same Dataset Version diff to model variance alone. That is a property of the
  format, and every rule in *Determinism* is load-bearing for it.
- Adding a per-line field later is a `record_version` bump, and #136's Report gains nothing it must
  re-derive: the failure and `long_form` counts it discloses come from the Record itself.
- **#134 inherits a narrowed job**: the provenance record's content, in a file whose name, position,
  write-order, byte format and two Record-describing fields are already fixed.
- **#135 inherits a narrowed job**: the Run directory's name, its position under `--eval-out`,
  retention across Runs, and where #136's Report lands — with the two files inside a Run given.
- Nothing here makes Transcription reproducible, and the Record says so by carrying the provenance
  instead.

## Rejected alternatives

**Per-Split Record files, mirroring v0.1** — the consistent shape, and the one an operator familiar
with `--data-out` would predict. Rejected because the constraint that produced v0.1's three files
(HF `audiofolder` bucketing) is absent here, because it re-materializes at the expensive stage the
Scope narrowing ADR-0017 deliberately moved to the cheap one, and because it triples the Scoring
golden's fixture count on the path whose central claim is that it is cheap to test exhaustively.

**A provenance header line inside `hypotheses.jsonl`** — one file per Run, maximally self-contained,
and the shape several ASR toolchains use. Rejected outright: a header line cannot be written **last**,
so it forfeits ADR-0017's completeness sentinel — the single mechanism standing between a crashed
40-minute Transcription and a Report computed over a truncated Record.

**Repeating run-level provenance on every line** — makes any single line fully attributable, which is
genuinely useful when lines get grepped out of context. Rejected on the sentinel again (repetition
still cannot be written last), and because ADR-0016's provenance table is a dozen fields including
resolved library versions and seven decode constants — multiplying it by every Sample to avoid one
file open.

**`content_hash` on the line** — mirrors the Manifest, takes the audio binding from 64 bits to 256,
and reduces surprise for anyone diffing Record against Manifest. Rejected as redundant: `id` is
already `sha256(Original bytes)` truncated, so this hardens a binding that is sufficient at 12–100
Samples, in an artifact where nothing checks it, for ~70 bytes per line.

**Recomputing `prompt_id` from `reference` at score time, as an integrity check** — the sharpest
version of "detectable if wrong," and pure: it needs no dataset, no audio and no model, and would
catch a hand-edited Record. Rejected because it requires re-implementing v0.1's `prompt_id` recipe
(NFC, trim, whitespace-collapse, `sha256`) on the far side of ADR-0017's import boundary — a second
copy of a hash whose divergence would present as a spurious hard error — to defend against a threat
model this repo does not have.

**A `status` enum or a `failed` boolean beside `hypothesis`** — explicit, greppable, and immune to
anyone misreading `null` as "empty". Rejected because it is a second field that must agree with the
first, and `hypothesis: null` vs `hypothesis: ""` already carries ADR-0017's distinction totally.
Two encodings of one fact is how they come to disagree.

**Free-text exception detail in `error`** — the operator sees exactly what raised, months later, in
the durable file rather than in a terminal that has scrolled. Rejected because it puts absolute paths
and sometimes addresses into an artifact whose diffability is a decided property, and because the
audience that needs the traceback is the one running the command, who has stderr.

**Absent lines for failed Samples** — the smallest Record, and defensible since Scoring excludes them
anyway. Rejected because it collides head-on with resumption, where absence must mean *not yet
attempted*, and because it deletes the Breakdown attributes the Report needs to say *which* groups
lost Samples rather than merely how many.

**Sorting the Record at the end of the Run** — frees Transcription to process in any order (batching,
retry-at-end, longest-first). Rejected because it turns a crashed Record from a valid prefix into an
unordered fragment, which is the property resumption is built on, in exchange for a scheduling
freedom ADR-0016's fixed, guard-free decode does not ask for.

**Re-deriving the JSON byte format inside the eval path**, for the strictest possible reading of
ADR-0017's import rule — rejected above: that rule is about interpreting the dataset, and a second
copy of ADR-0006's format is the exact drift that ADR-0006 exists to prevent and that no golden test
can detect.

**Building resumption in v0.2** — the most literal reading of ADR-0017's hand-off. Rejected because
it requires solving the pre-completion-provenance gap, adding a flag or an auto-detect rule, and
setting a policy for provenance mismatch, to save single-digit minutes on a corpus of ADR-0009's
size. The format keeps the door open at zero cost, which is what the hand-off actually needed.

**Saying nothing about resumption** — the leanest ADR. Rejected because the four enabling properties
were chosen deliberately, and a later reader with no record of that could trade one away — sorting at
the end, or writing failures as absence — for a local convenience, and discover the cost only when
the corpus has grown.
