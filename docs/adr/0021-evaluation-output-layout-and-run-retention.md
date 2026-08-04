# Evaluation output layout & Run retention (v0.2)

ADR-0017 fixed the commands and named `--eval-out` "the root that holds Runs"; ADR-0019 fixed the two
files a Run directory holds; ADR-0020 abolished the Run id and left its directory name as the Run's
**sole** handle. This ADR fixes what is left: whether Runs accumulate, what names a Run directory,
what sits at the `--eval-out` root, where the Report lands, how a crashed Run is treated, and whether
any of it is sensitive enough to need a gate. It resolves #135.

It builds on ADR-0002 (the stateless transform, and privacy as an architectural property of external
paths), ADR-0003 (single current build, the retention rule, the staging protocol, the completeness
sentinel), ADR-0012 (the privacy allowlist and its deliberate narrowness), ADR-0015 (Run, Evaluation
Report, Baseline), ADR-0017 (`--eval-out` as a root, incremental Record, provenance last, the
rejection of atomic staging for `transcribe`), ADR-0018 (neither evaluation command has any
configuration) and ADR-0019 (`hypotheses.jsonl` + `run.json`, and the resumption guarantees).

It **amends ADR-0017** in one place: that ADR calls a Run directory *"self-contained — Record,
provenance, Report"*, and the Report decision below removes the third member. The amendment is
written against that sentence where it sits, per this repo's practice. It also annotates
`CONTEXT.md`'s **Evaluation Report** entry, whose "emitted record" needs to stop reading as a file.

The whole ADR follows from noticing that **ADR-0003's retention rule is not overturned here — it is
applied.** ADR-0003 says *Originals: always retained, untouched. Derived: always regenerated,
replaced wholesale.* On the dataset side the expensive, irreproducible thing lives **outside**
`--data-out`, so everything inside it is derived and gets replaced. On the eval side the expensive,
irreproducible thing lives **inside** `--eval-out` — a Hypothesis the model will never produce
identically again — and the derived thing is the Report. Same rule, opposite-looking tree, because
the seam falls in a different place. Every decision below is that observation spent.

## Decisions

### Runs accumulate, and nothing prunes them

**`transcribe` mints a new Run directory inside `--eval-out` on every invocation and never touches
an existing one.** There is no `--keep-last`, no `sdw eval prune`, no garbage collection, and no
`latest` pointer. Removing a Run is `rm -rf <run-dir>`, which is ADR-0002's posture on deletion
unchanged: *deletion is the operator's own file-system action rather than a command.*

#135 asked this as *does ADR-0003's precedent transfer?* It does not, and each of ADR-0003's three
reasons for replacing wholesale fails here for its own reason:

- **Regenerability is inverted.** ADR-0003's load-bearing sentence is *"reproducibility is intrinsic,
  so hoarding builds isn't needed for it"* — a build is a pure function of `--data-in` and the
  constants, so discarding one costs the minutes to recompute it. A Transcription is a pure function
  of nothing: ADR-0016 declines to claim reproducibility and #127 found **no runtime documents it at
  all**. A discarded Run is not expensive to recreate; it is **impossible** to recreate. The thing
  ADR-0003 was free to throw away is the thing this directory exists to keep.
- **Unbounded growth is not the same quantity.** ADR-0003 was reasoning about a tree of Normalized
  WAVs and two PNGs per Recording. A Run directory holds **no audio and no images** — a Manifest line
  is ~350 bytes, so ADR-0009's ~12-Sample corpus is single-digit kilobytes of `hypotheses.jsonl`, and
  even a 100-Sample corpus is ~35 KB plus `run.json`. Unbounded growth in kilobytes per Run is not
  the objection ADR-0003 raised; it is a rounding error against the dataset it evaluates.
- **"Which one is current" was already removed.** ADR-0003 fled that machinery, and rightly. But
  ADR-0017 decided `score --run <run-dir>`, so the operator names the Run they mean. There is no
  current-pointer to maintain, nothing to disambiguate, and no rule that could go stale.

And the positive case is the destination's own: the map exists to produce *a number you can honestly
compare against a future fine-tuned model.* Wholesale replacement makes the primary use case
impossible — v0.3's Run would overwrite the Baseline it is supposed to be measured against.

**No pruning mechanism is the deliberate half of this**, not an omission deferred. A prune needs a
policy (age? count? keep-if-complete?), a policy is a knob, and a knob on retention is the first
configuration either evaluation command would carry since ADR-0018 stripped both to zero. Against
kilobytes, `rm -rf` is not a missing feature.

### `--eval-out` holds Run directories and nothing else

No index file, no manifest of Runs, no `latest` symlink, no root-level marker of any kind. `ls
<eval-out>` is the complete listing, and its contents are the Runs.

The `latest` symlink is the one worth rejecting explicitly, because it is a small convenience and
would be added by reflex. It reintroduces exactly the *"which run is current"* concept the previous
section established does not exist here — and it introduces it as a **mutable pointer into immutable
artifacts**, so `sdw score --run <eval-out>/latest` would mean different numbers on different days
while looking like a fixed reference. ADR-0017 made the handle explicit for a reason.

`transcribe` creates `--eval-out` if it does not exist, parents included. Pointing `--eval-out` at a
directory holding unrelated files is not an error — the tool reads nothing at that level, in the
spirit of ADR-0003's *"files under `--data-in` not referenced by the CSV are silently ignored."*

**The dataset directory is never written to, and there is no default for either path.** Every byte
either evaluation command writes **to disk** lands under `--eval-out`, inside a Run directory — and
`transcribe` writes all of them, since `score` writes nothing anywhere and emits its Report to
stdout. `transcribe` opens `--dataset` read-only, and `score` (per ADR-0017) never opens it at all. So a Dataset Version is
read by evaluation exactly as `--data-in` is read by `build` — the input side of ADR-0002's
stateless transform — and the ADR-0010 property that `dataset_version` is recomputable from
`--data-out` alone survives evaluation untouched, because evaluation adds nothing there to recompute
over. Neither flag defaults: both are required and explicit, since ADR-0002 makes every path the
tool touches an operator-named external one, and a defaulted `--eval-out` would put a Run somewhere
the operator did not name.

### A Run directory is named `run-<UTC start timestamp>`

```
<eval-out>/
  run-20260803T142205Z/
    hypotheses.jsonl
    run.json
  run-20260811T091330Z/
    hypotheses.jsonl
    run.json
```

Basic-format ISO 8601, UTC, second resolution, `Z`-suffixed, `run-` prefixed. Minted from the clock
at the moment `transcribe` creates the directory — **not** at completion, because ADR-0017 writes the
Record incrementally into it and the directory must exist first.

Two constraints came down from ADR-0020, which rejected all three identity schemes and observed that
opaque/sequential was *"a category error — a directory-naming scheme, and naming the Run directory is
#135's."* Both bind here:

- **The name may not be hash-shaped.** ADR-0020's central objection to an input-derived id was that a
  `sha256:`-shaped string in this repo carries a known contract — *equal ⟹ identical content* — that
  a non-deterministic Run cannot honour, in *"a repo whose readers know exactly one hash-shaped id."*
  A hash-shaped **directory name** smuggles the same false-yes in through the filesystem, where it is
  seen more often than the file's contents. A timestamp promises only what it says.
- **The name is the Run's sole handle**, so it must be legible without a decoder ring. A timestamp
  sorts chronologically in `ls`, tells the operator which of two Runs is newer without opening
  either, and needs **no read of sibling directories** to compute — which a counter does, and which
  would be the same directory-scanning move the previous two sections removed.

**The name is a handle, not a record — and the Run directory is freely renameable.** ADR-0019 stated
that a Run is self-contained and that nothing inside it refers to anything outside; nothing inside it
refers to the directory's own name either. An operator who renames `run-20260803T142205Z` to
`baseline-v0.2` has broken nothing, and is doing the sensible thing with the artifact the map calls
a Baseline.

That property is what answers the obvious objection: **ADR-0020 already records `started_at` in
`run.json`, and ADR-0019 forbids recording a number twice** on the grounds that *"a number recorded
twice can disagree with itself."* The rule survives because the name is not a second record of the
start time — `run.json` is authoritative and always was. The name is a **default label**, chosen from
the one fact about a Run that is guaranteed available at creation, distinct between invocations, and
meaningful to a human. It is allowed to disagree with `started_at` — that is what renaming *is* — and
nothing reads it back.

**A name collision is a hard error.** If the directory already exists, `transcribe` aborts in the
preflight naming it, rather than suffixing `-2` or overwriting. Two Runs starting in the same UTC
second requires two concurrent invocations of a multi-minute stage on a single-operator tool; the
cheap, loud failure is correct, and a silent suffix would produce two directories whose names imply
an ordering relationship they do not have.

### The Report is not written to disk

**`sdw score` writes nothing, anywhere.** The Report goes to stdout. A Run directory holds exactly
ADR-0019's two files for its entire life, and `--eval-out` never acquires a third kind of thing.

The obvious answer was `<run-dir>/reports/`, mirroring v0.1's `--data-out/reports/{quality.jsonl,
summary.txt}`. It is rejected, and the same principle that decided the retention section decides this
one in the opposite direction: **retain what is expensive and irreproducible, regenerate what is
cheap and pure.** ADR-0018 left `score` with no configuration at all, so a Report is a deterministic
function of the Record and `--split` — recomputable in milliseconds with no model, no audio, no
network and no torch. It is the derived side of the seam, and ADR-0003's rule for derived output is
that it is regenerated, never hoarded.

Two things make a persisted Report actively worse than a regenerated one:

- **It is stale by design.** ADR-0020's sharpest finding is that `tool_version` has three occurrences
  — built, transcribed, scored — and that the scoring one *routinely* differs from the others,
  because ADR-0018 built the Record to be scored repeatedly under later tool versions. A Report on
  disk is therefore a file whose numbers came from a tool the reader may no longer have, sitting
  beside a Record that would answer under the tool they do. Re-scoring is not merely as good as
  reading it; under ADR-0020's comparability rule it is **strictly more comparable**, because both
  sides of a comparison get scored by one tool version instead of two.
- **It would make `score` a writer.** ADR-0019 made the Run self-contained and put its existence,
  write-order and sentinel semantics entirely under `transcribe`. If `score` writes into the Run
  directory, the expensive artifact mutates every time anyone looks at it, and ADR-0020's escalation
  path — *diffing two `hypotheses.jsonl` files with the `hypothesis` and `error` columns masked* —
  acquires a "did someone score into this?" caveat it currently does not have.

So **`score` is read-only**, and that is ADR-0003's *"`commit` is the only writer of `<data-out>`"*
discipline reused: a Run's bytes are fixed at the end of Transcription and never change again, with
one writer and one auditable enforcement point.

The operator who wants a durable Baseline writes `sdw score --run <run-dir> > baseline.txt`. That
file is honestly **theirs** — a note they chose to keep, at a path they chose — rather than an
artifact the tool implies it maintains. It also sidesteps a naming problem that would otherwise
appear immediately: `--split` makes several Reports possible per Run, so a written Report needs the
Scope in its filename, and the first thing that would go stale is the un-scoped default's name.

**What the Report contains and how it renders stays #136's.** This ADR decides only where it lands.
If #136 concludes it needs both a human rendering and a machine-readable one, that is a rendering
question about one stream — not a reason to write files.

### No staging; the Run directory is created in place

`transcribe` creates `<eval-out>/run-<timestamp>/` at its final name and writes into it. There is no
sibling `.tmp`, no rename-on-success, and no swap.

This is derived rather than newly decided, but it is stated because ADR-0003's protocol is the
repo's default and would be reached for. ADR-0017 already rejected atomic staging for `transcribe`
on the one axis where eval differs — *"a `build` is cheap enough to repeat, and a Transcription is
not"* — and the second half matters as much: ADR-0003's staging arrives bundled with *"stale
`*.tmp`/`*.old` from a crash are cleaned at the next run's start."* Applied here, that sweep would
**delete the 39 minutes** ADR-0017 chose incremental writing to save. The two halves of ADR-0003's
protocol cannot be taken separately, and neither belongs here.

`run.json` written last remains the sole completeness mechanism, exactly as ADR-0017 and ADR-0019
decided. Nothing in this ADR adds a second one.

### A crashed Run is kept forever

A Run interrupted before completion leaves a directory with a partial `hypotheses.jsonl` and **no**
`run.json`. Nothing ever removes it. `score` hard-errors on it, naming it incomplete — already
decided by ADR-0017 and ADR-0019, and it needs no addition here.

Under wholesale replacement this could not arise; under accumulation, **incomplete Runs accumulate
too**, and the tidy instinct is to sweep them. That is rejected, and stated positively so it is not
re-added as a convenience:

- The incomplete Run **is** the model output. It is the thing ADR-0017's incremental write exists to
  produce, and an auto-clean would delete on the next invocation precisely what two ADRs arranged to
  survive a crash.
- It is the input a resumption mechanism reads. ADR-0019 guaranteed the format admits resumption for
  free — valid prefix, total order over content-derived ids, failures present-not-absent — and named
  the one missing piece as a durable start-time provenance file. A sweep would remove the artifact
  those guarantees are *about*.
- The sentinel already labels it. An operator running `ls` sees a directory without `run.json`, and
  `score` refuses it by name. Nothing is silently mistaken for a finished Run.

A startup warning naming sentinel-less Runs was the middle option and is also rejected: it requires
`transcribe` to read sibling directories — the one thing the timestamp naming was chosen to avoid —
to produce a notice `ls` already gives.

### Privacy: no new mechanism, and one finding on the record

**ADR-0012's allowlist is untouched, `.gitignore` gains nothing, and no CI check is added.**

> **Amended by [ADR-0026](0026-v0-2-acceptance-criteria.md) (#139).** The allowlist **is** extended,
> to `hypotheses.jsonl` ⊆ `examples/` + `tests/fixtures/`. Both rejections below assume the check
> would be a **prohibition**; ADR-0012's Check 2 is an **allowlist**, under which a committed golden
> is an entry rather than a hole. The format-policing objection was aimed at `.mp3`/`.m4a` — *input*
> formats the tool hard-aborts on — where the check would conflate a privacy breach with a bad input;
> `hypotheses.jsonl` is an artifact `sdw` emits, whose sensitive-text class this section was the first
> to identify. The finding below is unchanged and is what ADR-0026 acts on. `.gitignore` still gains
> nothing, and `run.json` is deliberately **not** covered.

On its own terms this is quick: evaluation emits **no audio**, so a check asserting that tracked
`*.wav` files are a subset of `examples/data-in/` and `tests/fixtures/` has nothing to say about a
Run directory. And `--eval-out` is an explicit external path exactly as `--data-out` is, so it needs
no ignore rule for the reason `.gitignore` already records in a comment: *"No output-dir ignore:
`--data-out` is an explicit external path."* ADR-0002's claim that privacy is **architectural**
extends to the eval path unchanged.

**But a finding belongs on the record, because it is new to this repo.** `hypotheses.jsonl` is the
first artifact `sdw` produces that contains a transcript of **what a speaker actually said**. Every
v0.1 artifact carries *intended* text — the Prompt, authored by the operator in `recordings.csv` and
copied through the Manifest. A Hypothesis is the model's reading of the audio, and on the
atypical-speech population this product exists for, a speaker who departs from the Prompt yields a
Hypothesis that is unprompted personal utterance. `perceived_text` is the human version of that
same class and is deferred out of scope; the machine version arrives in v0.2 whether or not anyone
names it. It changes no mechanism, because the mechanism — external paths, never in git — already
covers it. It is written down so the next person to ask *"is anything here sensitive?"* finds the
answer rather than the reasoning.

**Broadening the CI check to eval output is rejected on two grounds.** ADR-0012 already rejected
broadening once, as *conflating a privacy breach with a hard-abort input* and making the check
*police formats*; a rule about `hypotheses.jsonl` is the same shape. The second ground is concrete
and immediate: ADR-0019 handed #138 a Scoring golden that is **a committed `hypotheses.jsonl`** of
synthetic text, so a check forbidding tracked Records would need `tests/fixtures/` carved out of it
on the day it landed — a gate written and holed in one commit.

### Neither evaluation command gains configuration

ADR-0018 stripped `score` to zero configuration and left one conditional open: *"If #135 finds that
output layout or Run retention needs configuration, `score` grows `--config` back carrying a
different section."*

**It does not fire.** Retention has no policy to tune because there is no prune; the directory name
is derived from the clock; the Report is not written, so there is no output path to configure. The
surface is `sdw transcribe --dataset <dir> --eval-out <dir>` and `sdw score --run <run-dir>
[--split <name>]`, and ADR-0018's symmetry holds exactly as stated: **neither evaluation command has
any configuration.**

> **Amended by ADR-0022 (#136): `sdw score --run <run-dir> [--split <name>] [--format
> text|json]`.** The paragraph above holds as reasoning — retention has no policy, the name comes
> from the clock, the Report is not written — and ADR-0022 adds no *configuration*: `--format`
> selects a rendering of one Report, changing no number. It is the direct consequence of the
> sentence three sections above, which pre-authorised it: *"if #136 concludes it needs both a human
> rendering and a machine-readable one, that is a rendering question about one stream — not a reason
> to write files."* It concluded exactly that, and no file is written.

### `CONTEXT.md` gains one annotation

**Evaluation Report** reads *"The emitted record of a Run: its Metrics, its Breakdowns, and the
provenance attributing them."* Written before this ADR, "emitted record" is now ambiguous in exactly
the wrong direction — it reads as a file, beside two entries (**Hypothesis Record**, **Evaluation
Run**) that genuinely describe files. The entry is annotated: a Report is **emitted to stdout and
never persisted by the tool**; a Run directory contains no Report; the operator's redirected copy is
their artifact, not `sdw`'s.

No other entry changes, and no term is added. This ADR names no new domain concept — a Run directory
already *is* the Run (ADR-0015), and `--eval-out` is a flag, not a thing in the domain. That the
annotation was needed at all is worth noting against ADR-0020's *"No `CONTEXT.md` change"* — the
only such section in the v0.2 sequence, since ADR-0018 annotated two entries itself. One clarifying
line is a smaller correction than a missing term, so the vocabulary is still holding.

## Consequences

- `--eval-out` is an append-only shelf of immutable Run directories. Nothing the tool does ever
  modifies or removes one after `transcribe` finishes it.
- A Run's bytes are written by exactly one command and read by every other. `score` is not merely
  pure, it is **read-only**, which is what lets ADR-0020's masked-diff escalation be stated without
  qualification.
- The Baseline survives v0.3 by construction: a later Run lands beside it, not on top of it.
- Comparing two Runs is `sdw score` twice — both under today's tool, which is the comparison
  ADR-0020's rule actually endorses. The map's cross-run fog now inherits a shelf of Runs to compare
  and no persisted numbers to reconcile.
- v0.2 ships with no fifth command and no configuration on either evaluation command.
- An interrupted Transcription leaves a durable, labelled, self-describing partial Record — the exact
  input a resumption mechanism needs, kept at no cost.
- The one growth risk left is a shelf of Runs an operator never prunes. At ~35 KB per Run at the top
  of ADR-0009's corpus range, that is the intended trade.

## Rejected alternatives

**Replacing `--eval-out` wholesale, mirroring ADR-0003** — the consistent choice, and the one an
operator familiar with `--data-out` would predict; it also keeps a single tree shape across the
tool and needs no retention reasoning at all. Rejected because ADR-0003's justification is
*intrinsic reproducibility*, which the eval path does not have and cannot get: the Run it would
discard is the one artifact in this repo that no amount of recomputation brings back. It would also
make comparing two Runs the operator's filing problem — two `--eval-out` paths, remembered by hand —
which is the *entire point of a Baseline* pushed outside the tool.

**Accumulate with an explicit prune (`--keep-last N`, or an `sdw eval prune`)** — the responsible
middle, and the shape most tools of this kind ship. Rejected on quantity and on cost: a prune needs
a retention policy, a policy is a knob, and it would be the first configuration on either evaluation
command since ADR-0018 removed the last one — bought to manage kilobytes that `rm -rf` already
manages. A fifth command is worse still, on #8's own standard for `verify`.

**A `latest` symlink or a root-level index of Runs** — one less path to type, and a natural
`score --run <eval-out>/latest`. Rejected because it is a mutable pointer into immutable artifacts:
the same command means different numbers on different days while reading like a fixed reference. It
also restores the *which-one-is-current* concept ADR-0017 removed by making `--run` explicit, and an
index file at the root would be a second source of truth about a directory `ls` already describes.

**Sequential Run names (`run-0001`)** — shortest to type, unambiguous ordering, no clock dependency.
Rejected because computing the next number requires reading sibling directories — the directory-scan
this design avoids everywhere else — and because it breaks the moment a Run is deleted or renamed,
both of which are supported operations. It also carries no information: `run-0007` tells the operator
nothing `ls` did not already order for them.

**A content- or input-derived Run directory name** — the shape ADR-0001 uses everywhere else in this
repo, and superficially the consistent move. Rejected on ADR-0020's argument, restated at the
filesystem level: a hash-shaped name asserts *equal ⟹ identical content*, which is precisely the
guarantee a non-deterministic Run cannot make, in the place a reader sees most often.

**A `--name` flag on `transcribe`, defaulting to the timestamp** — lets the operator label a Run
`baseline` at creation, which is a real thing they will want. Rejected because `mv` already does it,
with no flag, after the fact, when the operator knows whether the Run deserves the name — and because
it would put the first knob on the command ADR-0017 deliberately gave zero, where the zero *is* the
argument that the output is attributable.

**Writing the Report into the Run directory (`<run-dir>/reports/`)** — mirrors v0.1 exactly, makes a
Run directory tell its whole story in one place, and gives the operator a file to commit or attach.
Rejected above on staleness and on making `score` a writer; and it would need the Scope in every
filename, since `--split` makes several Reports possible per Run, leaving the default's name as the
first thing to go wrong.

**Writing the Report anywhere else the tool chooses** — a sibling `<eval-out>/reports/`, or a
`--report-out` flag. Rejected for the same reason plus a flag: `>` is the shell feature that already
does this, and a path knob on `score` reopens the configuration ADR-0018 closed to buy nothing.

**Staging the Run directory and renaming on success, mirroring ADR-0003** — the repo's default
protocol, and it would guarantee no partial Run is ever visible. Rejected because ADR-0017 already
weighed it and because the protocol is indivisible: its stale-`.tmp` sweep would delete the partial
Record that the same ADR's incremental write exists to create. Visible-but-labelled-incomplete is
strictly better than invisible-then-deleted when the invisible thing took 39 minutes.

**Auto-cleaning sentinel-less Run directories at the next `transcribe`** — keeps the shelf tidy with
no operator effort, and defensible since `score` refuses them anyway. Rejected as the same deletion
wearing a different hat, and because it removes the resumption input ADR-0019 spent four guarantees
keeping viable.

**Warning about incomplete Runs at `transcribe` startup** — costs nothing to the artifacts and
surfaces a crash the operator may have forgotten. Rejected because it makes `transcribe` read sibling
directories to produce a notice `ls` already gives, adding the one filesystem dependency this design
otherwise has none of.

**Extending ADR-0012's CI check to forbid tracked `hypotheses.jsonl`** — makes the new sensitive-text
class enforced rather than documented, on the strongest available precedent. Rejected because it is
the format-policing ADR-0012 already refused, and because it collides on day one with #138's
committed Scoring golden, which is exactly a tracked `hypotheses.jsonl`. A gate that must be holed
before it lands is not the mechanism this needs.

> **Overturned by [ADR-0026](0026-v0-2-acceptance-criteria.md) (#139).** *Forbid* is the error in this
> entry: ADR-0012's check allowlists rather than prohibits, so the Scoring golden is an entry in it
> and no hole is required. ADR-0026 extends it to `hypotheses.jsonl` ⊆ `examples/` +
> `tests/fixtures/` — two legitimate entries now, since `examples/` gains a committed Run of its own.

**A `.gitignore` entry for a conventional eval output path** — cheap insurance against an operator
running the tool inside the repo. Rejected because it invents a conventional path where the design
has only an explicit external argument, contradicting the reasoning `.gitignore` already states in a
comment for `--data-out`, and offering protection only to the one path anyone happened to guess.
