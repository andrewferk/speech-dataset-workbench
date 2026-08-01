# Evaluation command surface & the transcribe/score seam (v0.2)

ADR-0016 fixed *which model, run how*. This ADR fixes the surface that runs it: how an operator
reaches evaluation from a shell, where the split reproducibility contract becomes a visible fact of
the CLI rather than a promise in prose, and what happens when something goes wrong 39 minutes into
a 40-minute run. It resolves #130 — v0.2's spine, the analogue of #8 for evaluation.

It builds on #8 (the two-command spine, the defaults-plus-`--config` pattern, the hard/soft failure
split), ADR-0002 (stateless `--data-in` → `--data-out`), ADR-0003 (`--data-out` is replaced
wholesale; `dataset.json` written last as the completeness sentinel), ADR-0006 (the canonical
Manifest), ADR-0010 (`dataset_version` recomputable from `--data-out` alone), ADR-0015 (evaluation
vocabulary) and ADR-0016 (backend, model, decode constants). It amends **ADR-0006** in one place:
the expectation that v0.2 populates `perceived_text` is withdrawn.

The whole design follows from one observation. The map already split the reproducibility contract
in two and put a durable Hypothesis Record at the seam. That seam is **expensive on one side and
free on the other** — minutes of model time against milliseconds of string comparison — and
ASR evaluation's actual day-to-day work happens entirely on the free side (research #128 found the
normalization argument is where the value is, and that comparing two normalizations of the *same*
Hypotheses is exact and paired). Every decision below asks the same question: *does this put the
choice on the cheap side of the seam, where it can be made again?*

## Decisions

### Two commands — `sdw transcribe` and `sdw score`

The eval path is **two commands, not one**. There is no `sdw evaluate` wrapper; `Evaluation` stays
what ADR-0015 defines it as — the concept naming both stages — and is not a verb the CLI answers to.

#130 framed this as minimalism (one command, internal cache) against transparency (two commands).
It resolves for two commands on four arguments, in descending strength:

- **The artifact already exists; only its lifecycle was in question.** ADR-0015 makes the Hypothesis
  Record durable and *"retained unmodified so Scoring can be re-run against it"*. Under one command
  that artifact still exists, but the user reaches it through a cache-hit rule they must trust
  rather than a path they typed. Two commands make its existence a **consequence of the surface**
  instead of a guarantee in a document.
- **The import boundary becomes checkable by running the tool.** The map demands isolation that is
  *structural, not aspirational*. With `score` as its own command, "Scoring needs no torch" is
  verified by invoking `sdw score` in a venv without the eval extra installed. Under one command
  the claim retreats to lazy imports and test discipline — the thing ADR-0012 avoided by making
  recomputation *unwritable* rather than merely untested. #137 inherits this as a testable property
  rather than a design intent.
- **The vocabulary already chose the names.** ADR-0015 spent three terms where one would have been
  shorter, precisely because Transcription and Scoring carry different reproducibility contracts.
  `transcribe` and `score` mean the CLI, the ADRs and `CONTEXT.md` share one word list, with no
  translation at the boundary where mistranslation is costliest.
- **Re-scoring is the common path, not the rare one.** #128 put the 95% CI at 6–11 points wide at 12
  Samples, and identified paired re-scoring of one Hypothesis Record as the one comparison that
  survives it. That workflow should be the shortest command in the tool, not a cache hit.

Two costs are accepted on the record. The happy path is **two invocations**, not one. And #8's
"deliberate two-command spine" becomes four commands — though the two added are not peers of
`build`: they are the two halves of one act, which is a different kind of addition than the `verify`
command #8 rejected for serving *"an audit need a single technical user doesn't have."*

### Evaluation Scope — transcribe everything, choose the view at Scoring

**`transcribe` covers the entire Dataset Version. It has no Scope flag.** `score --split` (default:
every Split present) is the only place an Evaluation Scope is chosen.

#130 posed this as `test`-only against all-splits: a Baseline is only honest on `test`, because a
future fine-tuned model will have seen `train` — yet an *unmodified* model has seen none of it, so
evaluating everything is more informative today and useless for comparison tomorrow.

The seam dissolves the dilemma rather than trading it off. **Narrowing at Transcription is lossy;
narrowing at Scoring is free.** A Hypothesis you did not generate costs a full model run to obtain;
a Hypothesis you generated and did not score costs nothing. So the expensive stage never makes the
narrowing decision. Concretely: because today's Run transcribes every Sample, `sdw score
--split test` against **today's** Hypothesis Record is, in v0.3, a pure zero-model re-derivation of
the honest comparable number. Both numbers — informative-today and comparable-tomorrow — come from
one Run, permanently.

The corollary is that a **Scope flag on `transcribe` would be a flag whose only function is to
defeat the argument justifying the design.** If narrowing at Transcription is available, the
superset property holds only when the operator declined the convenience, and the v0.3 payoff
evaporates exactly when it is needed. The wall-clock saving it buys is single-digit minutes on a
Dataset of 12–100 Samples of ≤20 s each.

When a Dataset does grow large enough for a full Transcription to hurt, the answer is **resumption** —
an append-safe Hypothesis Record where a re-run skips Samples already transcribed under identical
provenance — not Scope selection. That is a different mechanism, it belongs to the Record's format,
and building `--split` now would be paying for a worse version of it. Handed to #133.

**The headline is Pooled over the Scope actually scored, always labelled with that Scope**, and the
Report always carries a per-Split Breakdown beside the Session/Prompt/Device/Environment ones, so
the `test` number never requires a re-run to obtain. The comparability rule the Report states:
*compare only Runs of equal Scope; once a model has trained on `train`, only `test` is honest.*

Hard-coding `test` as the headline was rejected. At ADR-0004's 0.8/0.1/0.1 over ADR-0009's ~12
recordings, `test` is **one Sample**. #128 already put the CI at 6–11 points at twelve; a headline
of N=1 is not a Baseline.

### Flags and the input contract

```
sdw transcribe --dataset <built-dataset-dir> --eval-out <dir>
sdw score      --run <run-dir> [--config <path>]
```

**`--dataset`, not `--data-in` and not `--data-out`.** The built Dataset Version is evaluation's
input, but `--data-in` means *the operator's source recordings* throughout ADR-0002 and
`CONTEXT.md`, and reusing it would imply the evaluator can reach source audio — it cannot; it reads
Normalized audio through the Manifest, as a stranger. `--data-out` is worse: under ADR-0003 that
flag names *the directory about to be replaced wholesale*, the precise opposite of a read-only
input. `--dataset` names the thing rather than its role in an earlier command.

**`--eval-out`, the visible sibling of `--data-out`.** ADR-0015 rules that evaluation output never
lands in `--data-out`; making the flag its counterpart puts that rule in the operator's hands rather
than in a document. `--eval-out` is the **root that holds Runs** — `transcribe` mints one Run
directory inside it and prints the path. Naming a root rather than a Run leaves the internal layout,
naming and retention entirely to #135 without a later CLI change.

**`score --run <run-dir>` names a directory, not a file.** A Run is a first-class term (ADR-0015);
the directory is self-contained — Record, provenance, Report; re-scoring is the shortest possible
invocation; and pointing at a directory again leaves the layout inside it to #135.

### The Hypothesis Record is Scoring's only input

**`score` never opens the dataset.** It reads one Run directory and nothing else.

This imposes a real constraint on #133: each Hypothesis Record line must carry not only the
Hypothesis but the **Reference text and every Breakdown attribute** — `session_id`, `prompt_id`,
`device`, `environment`, `split` — a join performed once, at Transcription time, and denormalized
into the Record. Four reasons, and the last is the one that pays:

- It makes *"Scoring is pure, with no model and no audio"* a property **of the command**, not merely
  of an inner function. One file in, Metrics out.
- Pairing-by-identifier (#128's rule, ADR-0015's insistence that pairing is never by position)
  happens **once**, where the audio actually was.
- If the dataset is rebuilt between `transcribe` and `score`, Scoring **cannot** silently pair a
  Hypothesis against text that has since changed. #129 established that unequal `dataset_version`s
  are not evidence the data differs; here the question never arises, because the Reference travels
  with the Hypothesis.
- Golden-testing the entire Scoring path needs **one fixture file** — no dataset tree, no WAVs, no
  torch, no network. The map's CI claim reduces to a property of the command's inputs. Handed to
  #138.

The cost is a few kilobytes of duplicated text per Run — the same trade the Original→Normalized
retention already makes, for the same reason.

### `transcribe` takes no configuration

ADR-0016 hard-coded the model, the seven decode constants, CPU/float32, and made language read
`[manifest].lang` from the dataset being evaluated. Nothing remains to configure, so **`transcribe`
has no `--config` flag** — not an empty one for symmetry with `build`.

This is stated as a positive property rather than an omission: **the expensive, non-reproducible
stage has zero operator knobs, which is exactly what makes its output attributable.** Every input to
a Hypothesis is either a source constant this repo owns or a field of the dataset it read.

Scoring is where the knobs live, so `score` inherits #8's pattern unchanged — baked defaults plus an
optional `--config` TOML — with one new section, **`[scoring]`**, owned by #132 (Normalizer tier,
`merge_compounds`, which Metrics, CER whitespace semantics, SER, whether a CI is reported).

On whether the effective config feeds the Run's identity, this ADR hands #134 a **constraint, not an
answer**: the scoring config cannot work the way v0.1's config does, because one Hypothesis Record
is *designed* to be scored many ways. The Record's provenance attributes the **Transcription**; the
Report separately records the effective scoring config and the Normalizer's identity as attribution.
Whether either is an *id* remains #134's.

### Failure policy — preflight before the model loads

#130 asked whether #8's *abort on structural, include-and-flag on soft* survives when a retry costs
40 minutes. **It survives unchanged**, because the correct move is to make every structural abort
happen before the expensive part starts.

**`transcribe` preflights everything structural before the model is loaded.** Hard errors, all
reachable in seconds: `--dataset` is not a Dataset Version (no `dataset.json`), the Manifest will not
parse, any Sample's Normalized audio is missing or will not decode, zero Samples, or the pinned
weights cannot be resolved (ADR-0016's cold-cache-no-network row). This is ADR-0012's move a third
time — make the expensive thing *unreachable* until the cheap checks pass — and it inherits #8's
proven shape, where `validate` exists precisely because stages 1–4 hold all the hard gates.

The consequence is that the objection dissolves instead of being traded away: **nothing structural
can abort after minute zero**, so "abort on structural" never costs 40 minutes.

No eval-side `validate` command is added. The preflight belongs **inside** `transcribe`, where it
cannot be skipped, and #8's own reason for `validate` — *"show me everything wrong at once"* before
a long operation — is satisfied by running the preflight as one pass rather than aborting on first
contact.

**A per-Sample Transcription failure is soft, recorded as an explicit failure, and never aborts.**
A failure marker is **distinct from an empty Hypothesis**: an empty string is *the model's output*,
while a crashed decode is not the model saying nothing. Collapsing them would mix recognition error
with infrastructure error inside one number, against ADR-0015's insistence that a Metric measures
one thing.

**Scoring excludes failed Samples from Metrics, and the Report states "N of M".** This is the one
place the policy must be loud, because the failure mode is the map's own bogeyman: the Samples most
likely to fail are the quiet, atypical, hard ones, so silent exclusion **flatters the Metric by
discarding exactly the data this product exists for** — the same silent inversion that got
ASR-as-dataset-QA ruled out. A non-zero failure count is surfaced at the top of the Report, and a
Run carrying any Transcription failure **may not be labelled a Baseline** without that count beside
it. Handed to #136.

Scoring failed Samples as empty Hypotheses — penalising the Metric rather than flattering it — was
the serious alternative and is rejected below.

**`score`'s hard errors** are few, now that Transcription is all-or-nothing: the Run directory is
absent or incomplete, the Record will not parse, or `--split` names a Split with no Samples. The
"is this Split fully present?" check has no reason to exist.

**Exit codes are #8's, unchanged**: `0` success, `1` hard error, argparse's own code for usage
errors. Soft failures exit `0`, consistent with v0.1, where soft flags never gate.

### Crash safety — incremental Record, provenance written last

This is where the 40 minutes actually bites. ADR-0003 stages `build`'s output and swaps atomically;
applied to `transcribe`, that would mean a failure at minute 39 leaves **nothing**.

So the Hypothesis Record is **written incrementally as Transcription proceeds, and the Run's
provenance file is written last as the completeness sentinel** — ADR-0003's `dataset.json` trick,
reused for the opposite reason. `score` hard-errors on a Run with no sentinel, naming it incomplete.

Both properties survive: the expensive stage is crash-durable, and Scoring still only ever sees a
complete Record. It also leaves the natural seam for the resumption mechanism handed to #133 above.

### v0.1 is sufficient as-is

**No v0.1 emitted artifact changes.** Every field evaluation needs is already on the Manifest line
(ADR-0006): `id` for pairing, `text` as the Reference, `audio_filepath`, `split`, and all four
Breakdown attributes — `session_id`, `prompt_id`, `device`, `environment` — plus `lang` for
ADR-0016's language rule and `duration`, which means ADR-0016's over-length check is answerable
**without opening a WAV**. `dataset.json` supplies `dataset_version` and `tool_version`, satisfying
#129's requirement that both be recorded. `manifest_version` stays `0.1`.

This is a finding rather than a coincidence: #8 put Session metadata on the line for a diagnostic
purpose it could not yet name, and the map's claim that the Breakdown *is what makes v0.1's session
metadata earn its keep* now cashes out with no schema change at all.

Two rules are stated positively so they cannot be violated by accident:

- **The eval path parses `<dataset>/{train,val,test}.jsonl` and `<dataset>/dataset.json` itself and
  imports nothing from `sdw.manifest` or `sdw.provenance`** — including `SPLIT_ORDER` and the field
  list. That is the entire stranger-consumer dogfood: if the Manifest is under-specified, the
  evaluator is the code that finds out. Worth writing down because the shortcut is one import away
  and looks harmless.
- **Evaluation reads the canonical per-Split JSONL, never the Hugging Face view.**
  `audio/<split>/metadata.jsonl` exists and would half-work, which is why the choice is on the
  record.

**One stale prediction is withdrawn.** ADR-0006 lists *"emitting `perceived_text: null` per line
makes the dual-annotation schema literal, so v0.2 populates it in place with no schema change"*, and
`sdw/manifest.py` carries the matching comment that widening to `str | None` is *"v0.2's first
move"*. **v0.2 does neither.** The map rules `perceived_text` collection out of scope and forbids
machine output from occupying the slot; ADR-0015 makes the firewall bidirectional. Left standing,
that note reads as an instruction to an implementer. The slot stays `None` through v0.2, and
widening waits for actual human annotation.

## Consequences

- Four commands: `build`, `validate`, `transcribe`, `score`. #8's two-command spine is deliberately
  superseded, and the reason is on the record.
- One Transcription serves every future Scoring view of that Dataset Version, including views not
  yet conceived — the property v0.3's comparison depends on.
- `sdw score` runs in an environment with no eval extra installed, which makes #137's import
  boundary an executable check rather than a convention.
- The Hypothesis Record becomes a denormalized join, not a thin list of strings. #133 owns its shape
  and now has a mandated minimum: identifier, Hypothesis, Reference, the four Breakdown attributes,
  `split`, the failure marker, and ADR-0016's over-length flag.
- A Report is never silently computed over a subset: exclusions are counted and stated, and a Run
  with failures is not a Baseline on its own.
- Nothing here makes Transcription reproducible, and the surface says so by giving it no knobs.

## Rejected alternatives

**`sdw evaluate` with an internal cache** — the shorter surface, and genuinely the simpler happy
path: one invocation, one mental model, and #8's minimalism preserved. Rejected because it makes the
Hypothesis Record an implementation detail the operator must trust rather than a file they name;
because it puts Scoring and Transcription in one command, so "Scoring needs no torch" can only ever
be asserted by tests rather than demonstrated by running it; and because it makes re-scoring — the
most frequent operation in ASR evaluation — a cache hit instead of the obvious default.

**`sdw evaluate` as a convenience wrapper over both** — rejected as the worst of both: it restores
the one-invocation happy path but leaves three eval commands, and an operator who reaches for the
wrapper never learns the seam exists, which is the thing the surface is meant to teach.

**`--split` on `transcribe`, for cost control** — the flag most likely to be missed. Rejected
because its only effect is to produce partial Hypothesis Records, defeating the superset property
that makes the whole design work, in exchange for minutes on a Dataset of this size. Resumption is
the right instrument for the real problem and is handed to #133.

**Hard-coding `test` as the headline Metric** — the most defensible Baseline in the abstract, since
it is the only Scope that stays honest once a model has trained on `train`. Rejected on arithmetic:
at 0.8/0.1/0.1 over ~12 recordings, `test` is one Sample. The comparability rule is stated in the
Report instead, and the per-Split Breakdown keeps the `test` number one file-read away.

**`score` reading the dataset for its References** — avoids duplicating text into the Record and
keeps the Record minimal. Rejected because it re-couples the pure stage to a tree that may have been
rebuilt underneath it, makes pairing a step Scoring performs rather than one Transcription already
did, and drags a dataset fixture into every Scoring golden test.

**Scoring failed Samples as empty Hypotheses** — the honest-in-the-other-direction option: a failure
becomes a full deletion error and *penalises* the Metric instead of flattering it, eliminating the
selection bias with no disclosure required. Rejected because it makes the number wrong in a
**quantified-looking** way — the reader sees a WER, not a caveat — whereas exclusion makes it wrong
in a way the Report can state exactly, as a count. It also re-conflates infrastructure failure with
recognition error, which the failure marker exists to keep apart.

**An eval-side `validate` command**, mirroring v0.1's preflight — rejected because the preflight is
mandatory and belongs inside `transcribe`, where it cannot be skipped. A separate command would make
the cheap safety check optional in front of the expensive operation, which is backwards.

**Atomic staging for `transcribe`, mirroring ADR-0003** — the consistent choice, and rejected on the
one axis where the eval path genuinely differs from `build`: a `build` is cheap enough to repeat,
and a Transcription is not. The sentinel recovers ADR-0003's actual guarantee — no consumer ever
reads a half-written artifact — without discarding 39 minutes of model output.

**`--data-in` or `--data-out` for the dataset argument** — rejected on meaning, above. Reusing
either would make the flag a lie about what the evaluator may touch.

**A `--config` on `transcribe` for symmetry with `build`** — rejected because ADR-0016 left nothing
to put in it, and a config section with no knobs invites one.
