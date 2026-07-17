# v0.1 acceptance criteria (#18)

We fix what "v0.1 is done" means: the observable conditions under which the workbench ships, and
the checks that establish them. This is the last decision on the v0.1 map — every behavioral ADR
(0001–0011) is settled, and this one says how we know they came true.

It consumes all eleven, and amends ADR-0009 (see below). It adds no product behavior: no new
command, no new config, no new output. Everything here is a check, a document, or a constraint on
how existing code is factored.

## Decisions

### The DoD delegates; it does not enumerate

v0.1 is **done** when all of the following hold:

1. **CI is green** — `ruff`, `mypy --strict`, and the full suite of ADR-0008.
2. **The three checks below pass** — examples build, privacy allowlist, audit recipe.
3. **A human has walked `examples/README.md` once** on a clean clone (see *The manual gate*).
4. **`v0.1.0` is tagged.**

There is deliberately **no ADR-indexed checklist** — no eleven-line table pairing each ADR with its
observable. The ADRs already amend one another (0001 by 0003 and 0010; 0006 by 0010; 0008 by 0009;
0004 by #19; 0009 by this ADR), and that was true before a line of code existed. A checklist
mirroring a set of documents that actively rewrite each other is a **second source of truth that
drifts from day one**, and the drift is silent, because nothing checks a checklist against the
documents it claims to summarize.

Behavioral completeness is therefore the ADRs' job to specify and ADR-0008's suite's job to verify.
This ADR's own content is only what those two do **not** cover.

**Coverage claim:** every ADR 0001–0011 is exercised either by ADR-0008's suite or by a check below,
except those named in *Accepted exceptions*.

That exception list is the substantive output of this decision. Writing it down is what revealed
that three of the five entries were cheap enough to close.

### Check 1 — the examples build

ADR-0009's example exists to teach; every element of its shape is justified by a claim it
demonstrates. Those claims are what break **quietly** when someone edits `examples/generate.py`: the
demo still builds, and teaches the wrong thing. Nothing else catches this — ADR-0008's golden test
runs against `tests/fixtures/reference/`, a *different* corpus with different Sessions, so it says
nothing about what `examples/` shows. ADR-0009's own drift test regenerates and byte-compares the
WAVs, and **never invokes `build`**.

CI builds `examples/data-in/` and asserts, as **named assertions**:

- `build --data-in examples/data-in --data-out <tmp>` exits **0**
- no produce-and-flag warning appears (ADR-0004: ≥3 Sessions)
- **12 Samples** total; realized split **6 / 3 / 3** (ADR-0004's worked example, as amended by #19)
- all three splits non-empty
- **24 PNGs** (ADR-0011: `images/` is a 1:1 mirror of the manifest, 2×N)
- **exactly one** `low_volume` flag, and that Sample is **present in a manifest** (ADR-0007:
  included + flagged)
- a **non-emptiness repair line** appears (ADR-0004, as amended by #19)
- the **speaker-overlap note** appears (ADR-0004: two speakers is why ADR-0009 has two speakers)

Assert **that** a repair fired and the counts are 6/3/3 — **not** that Session `h1` specifically
moved. Which Session moves is a function of hash ordering over Session ids; pinning it couples the
test to a naming detail with no teaching value, and the counts already prove the repair did its job.
The README may name `h1` in prose.

**Not a golden file.** A named assertion's failure message *is* the documentation of what broke:
`exactly_one_low_volume_flag` failing says ADR-0009's deliberate quiet take stopped tripping. A
golden diff says *line 7 differs*, and the fix a tired person reaches for is to regenerate it —
which is precisely how a pedagogical claim dies. A named assertion cannot be "fixed" without being
read. This is also why the check does not assert `dataset_version`: the preimage includes
`tool_version` (ADR-0010), so every version bump would break it for reasons unrelated to the
example — churn that trains people to update goldens without reading them.

### Check 2 — the privacy allowlist

ADR-0002's strongest claim is that privacy is **architectural** — audio lives only in the two
external directories, therefore **the manifest is shareable**. That entire argument rests on a rule
nothing enforced. ADR-0009 then gave the rule an exception ("captured audio never enters git;
**generated audio may**"), and rules with exceptions erode, because the next person to commit a WAV
has a precedent to point at.

CI asserts: tracked `*.wav` files are a **subset of `examples/data-in/` and `tests/fixtures/`**. The
check *is* ADR-0009's allowlist, made literal.

This is the one exception whose failure is **irreversible**: real captured speech merged into git
history is fixed by a history rewrite, not a revert. Every other item on the exception list fails
softly and recoverably. That asymmetry, not the check's cost, is the argument.

Scoped to **WAV only**, deliberately. ADR-0005 makes v0.1 WAV-only ingest, so a stray `.mp3` is not
a privacy breach — it is a file the tool would hard-abort on. Checking for it conflates two
unrelated concerns and puts this check in the position of policing formats, which is the ingest
stage's job.

When someone has a legitimate reason to commit audio, they edit the allowlist. That edit is where
the conversation happens; it is a feature of the design, not friction in it.

### Check 3 — the audit recipe

ADR-0010's central property is that `dataset_version` is **recomputable from `--data-out` alone** —
the property it restructured `dataset.json` to make real rather than hollow. It then declined a
`verify` command, on the grounds that ADR-0008's two-command spine should not grow a third for an
audit need a single user does not have. That call stands. But it leaves the map's most carefully
argued property demonstrated **nowhere**: the recipe is prose, and prose nothing runs is prose that
is wrong within two releases.

A test follows the documented recipe: read `dataset.json`, take `tool_version` and the `config`
block's bytes, frame `train`/`val`/`test.jsonl` as `<name> <byte-length>\n<raw bytes>`, prepend
`sdw-dataset-version/1\n`, sha256, compare against the recorded `dataset_version`.

**It imports nothing from `src/`.** A test sharing the tool's hashing code computes `f(x) == f(x)`
and passes forever — including when `f` is wrong, and including when the documented recipe describes
something `f` does not do. The point is to check the **documentation against the tool**, so the
recipe must be independently reimplemented from its documented steps. A shared-code version is
*worse than no test*, because it reads as verified on the CI dashboard while asserting nothing.

Its failure mode is a feature: when it fails, it is genuinely ambiguous whether the code or the
document is wrong, which **forces a human to decide** rather than auto-update a golden. That is the
correct failure mode for a provenance claim.

ADR-0010 rejected the command and thereby made documentation load-bearing. You do not get to reject
the command *and* leave the recipe unchecked.

### A constraint made structural instead of tested

ADR-0011 requires that the image title's peak/RMS are **taken verbatim from the quality stage, never
recomputed** — preventing the collision it spent its longest paragraph on (`peak -3.2` printed
beside `quality.jsonl`'s `-3.0`, both correct, neither explained). ADR-0008 commits no golden PNGs,
so verifying the rendered title against `quality.jsonl` would need OCR. As stated, it is
unassertable.

A formatter unit test would check the wrong link in the chain: it proves the formatter formats, not
that the image stage **obtained** those numbers from quality rather than recomputing them on the
plotted Normalized.

So the constraint moves from prose into a signature. **The render function takes the quality record
as a parameter, and the image module does not import the quality math.** Recomputation becomes
*unwritable*; an exception that cannot occur needs neither a test nor an exception-list entry. This
is ADR-0011's own advisory constraint ("quality computes peak/RMS once, the image stage consumes
them") made binding, by moving it from a sentence an implementer might skim into the one thing they
cannot avoid reading: the function they must call.

It also makes the stage dependency explicitly one-way — images depend on quality, never the reverse
— which matches pipeline order and keeps `validate` (stages 1–4, renders nothing) trivially
coherent.

This is a design constraint on unwritten code. If the implementer finds a better factoring that
preserves "never recomputed" by construction, **this ADR should lose the argument, not the code**.

### The manual gate — once, at v0.1

Before `v0.1.0` is tagged, a human walks `examples/README.md` on a clean clone and confirms:

- every command runs **as written**, in order, and prints what the prose claims
- the PNGs are **legible** — readable spectrogram, labelled axes, a title that renders without
  clipping
- the flagged Recording's waveform **visibly hugs zero**

None of this is automatable at reasonable cost, and all of it matters. ADR-0011's build-twice-diff
proves two renders match — **two identically broken renders pass**. ADR-0008 deliberately commits no
golden PNGs. So nothing establishes that the image is *readable*, and ADR-0011's entire rationale —
an image is an operator inspection aid — is void if it is not.

The gate is **not standing**. A manual gate that one person is supposed to run before every release
is a gate that gets skipped, and a skipped gate is worse than none, because the document still
claims it happened. v0.1 is the one release where this genuinely cannot be inherited: the README
will be written from a specification rather than from observed output, so v0.1 is when a human first
confirms the spec produced a legible artifact. After it, CI carries the weight.

**Consequence for authoring:** `examples/README.md` cannot be written from this ADR. Its "what you
should see" section must be written from **observed output** — which is the same argument, applied
to itself.

### The example's first run is noisy, and that is the content

ADR-0009 chose 4 Sessions partly so the first run prints no produce-and-flag warning. #19 then made
clearing that floor **visible**. The demo's first run now shows four signals:

1. configured **80/10/10**, realized **50/25/25** — a 30-point miss
2. a non-emptiness repair line (`moved session h1 from train to test`)
3. the speaker-overlap note
4. one `low_volume` flag

ADR-0009's letter is threatened; its intent is not. The warning it dodged was **produce-and-flag** —
an unmissable signal that the dataset is *unusable*, splits are empty, the build is broken. #19's
disclosures are the opposite kind of object: a build that **worked**, being honest about how.
Treating them as the same thing reads ADR-0009's words over its reasoning.

The four signals are precisely the four things this tool knows that a naive one does not: ratios are
best-effort at Session granularity; the non-emptiness guarantee costs something and says so;
disjointness is session-level, not speaker-level; a bad take is flagged but kept. **A demo
displaying none of them would run clean and teach nothing.**

`examples/README.md` therefore **predicts each signal before the reader meets it** — "you will see a
30-point miss; here is why that is arithmetic, not a bug." The risk is that a skimmer reads four
disclosures as four problems; that is a writing problem, and prediction is its fix.

### Release mechanic

`pyproject.toml` carries `version = "0.1.0"` (PEP 621, per the tooling research); `tool_version`
(ADR-0010) reads it. When every item above holds, **tag `v0.1.0`**. No PyPI, no build backend, no
changelog — the tooling research chose no build backend unless a packaged CLI is needed, and #8 runs
the tool as `python -m <package>`.

The tag gives "done" a referent that is not a mood. That matters more here than usual: the only
thing distinguishing v0.1 from v0.2 in this repository is a set of scope decisions recorded on the
wayfinding map. **The tag is where the map's Out-of-scope section becomes a fact.**

### Accepted exceptions

Named here rather than solved, so a future reader meets them as decisions instead of rediscovering
them as bugs:

- **ADR-0005's cross-architecture caveat** — unasserted *by design*. The ADR accepts that soxr's FFT
  ULPs deny cross-arch bit-exactness rather than claiming otherwise; reproducibility leans on pinned
  versions plus content hashes.
- **ADR-0008 itself** — meta. It *is* the suite; there is nothing outside it to check it with.
- **ADR-0010's dependency convention** — "committed `uv.lock` + a lock change ships a version bump"
  is enforced by nothing. A `soxr` bump without a version bump silently changes Normalized bytes
  while `dataset_version` claims continuity. ADR-0010 already reasoned this is **forced, not
  defective**: the id identifies the *manifest + config*, audio enters only via `content_hash` of
  Originals (bytes at rest, exact everywhere), and ADR-0005 already denies Normalized-byte cross-arch
  stability — so an id covering them could never be cross-machine stable.
- **Pre-tag `dataset_version` instability** — during development every build reads
  `version = "0.1.0"` while behavior changes underneath it, so equal ids do not imply equal
  semantics. Accepted: ADR-0003 replaces `--data-out` wholesale each build, nothing is distributed,
  and no one compares ids across development builds. **The id's contract begins at the tag.**

## Amendment to ADR-0009

Two changes, made in ADR-0009 rather than held here, so that a reader asking "why 4 Sessions?" finds
the whole answer where the question is asked:

1. **Heading corrected** — `Shape — 2 speakers × 2 sessions, ~12 recordings` contradicted its own
   body ("**4 sessions** clears ADR-0004's ≥3-session floor"), the map, and its own rationale: at 2
   Sessions the first run would trip exactly the produce-and-flag warning the body says a demo must
   not show. The body was right; the heading was a stale draft artifact.
2. **Amendment note added** — recording that #19's disclosures grew the shape's consequences: the
   first run now shows a repair line and a 30-point ratio miss, both deliberate and report-only.

The rationale is **not** rewritten. ADR-0009 did not choose 4 Sessions to trigger a repair — it
chose 4 to clear the floor, and the repair is a consequence that landed later. Retconning would make
the ADR read as more foresighted than it was, and the honest record of why we chose this is worth
more than a tidy one. Anyone revisiting the shape needs to know the repair was **discovered, not
designed** — that tells them it is a fact about 4-Session corpora, not a property someone wanted.

## Consequences

- "v0.1 is done" becomes checkable rather than felt, and `v0.1.0` is the event that makes it so.
- CI gains three checks; `pyproject.toml` gains a version; the image module gains a signature
  constraint. **No product behavior changes.**
- The privacy allowlist is this repository's first piece of *policy* enforcement — until now CI only
  tested the tool's own behavior. Deliberate: the policy it enforces is the one whose breach cannot
  be undone.
- The recipe in ADR-0010 now exists twice — as prose and as an independent test — and the two must
  be edited together. That coupling is the mechanism, not a side effect.
- `examples/README.md` is specified here but **written by the implementer**, from observed output.
- `CONTEXT.md` is unchanged; this ADR introduces no domain vocabulary.
- The wayfinding map is complete: no open decision stands between here and implementing v0.1.

## Considered and rejected

- **ADR-indexed checklist** (one line per ADR with its observable) — self-contained and auditable at
  a glance, but a mirror of documents that amend each other, drifting silently from day one.
- **Golden `examples/summary.txt`** — one comparison covering the table, repair line, overlap note
  and flag, with nothing to enumerate. Rejected: a golden's failure names a line number, not a broken
  claim, and invites regeneration over reading.
- **Full golden for `examples/`** (exact `dataset_version` + manifest bytes) — churns on every
  `tool_version` bump for reasons unrelated to the example, and duplicates ADR-0008's goldens over a
  tree built for that purpose.
- **Pure smoke for the examples check** (exit 0 only) — catches total rot, misses every claim the
  example exists to make.
- **Broadening the privacy check to `.mp3`/`.m4a`/`.flac`** — looks strictly better; conflates a
  privacy breach with a hard-abort input and makes the check police formats.
- **Audit-recipe test sharing the tool's hashing code** — cheap and reads as coverage; computes
  `f(x) == f(x)` and cannot fail for any reason we care about. Worse than no test, because the
  dashboard says verified.
- **Unit-testing the image title formatter** — checks that the formatter formats, not that the image
  stage obtained its numbers from quality rather than recomputing them. Wrong link in the chain.
- **A standing manual gate** — theater on a single-user project: skipped in practice while the
  document still claims it happened.
- **No manual item at all** — would let v0.1 ship with unreadable images and a typo in the README's
  second command, everything green.
- **Reworking the example to ≈10 Sessions** so 80/10/10 is nearly expressible — buys tidier
  arithmetic by making the data less honest (12 Recordings over 10 Sessions means singleton
  Sessions, misrepresenting what a Session is, and ADR-0009 needs one prompt recorded twice within a
  Session). Reopens settled shape to do it.
- **Shipping `examples/config.toml` with `[split]` at 50/25/25** — the prettiest first run: targets
  hit exactly, no repair, target == realized. Self-defeating: it hides best-effort ratios behind a
  config that happens to be exactly expressible, so the first reader to point the tool at their own
  data with default ratios meets the 30-point miss with no preparation — the demo having deprived
  them of the one lesson that would have helped. Also teaches "tune your ratios to your Session
  count," which is backwards.
- **A ticket for version/release mechanics** — the dev-build collision is the ticket's entire
  content, and it resolves in one sentence (accept; the contract begins at the tag). Ceremony.
- **Rewriting ADR-0009's rationale** so 4 Sessions is justified by the repair it triggers — retcons
  discovery as design and destroys the information that the repair was not foreseen.
- **Writing `examples/README.md` now** — it documents code that does not exist, and its "what you
  should see" section must come from observed output. Writing it from spec is the exact failure the
  manual gate exists to catch.
