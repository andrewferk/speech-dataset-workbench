# Seed / example data sourcing

v0.1 ships an **example dataset** so a reader who clones the repo can run the workbench
immediately, and a **documented path** for pointing it at their own recordings (#15). This ADR
decides where that example audio comes from, what physically lands in git, and what shape the
example takes. It builds on ADR-0002 (stateless `--data-in` → `--data-out`; privacy), ADR-0003
(input contract & storage layout), ADR-0005 (WAV-only ingest & normalization target), and
consumes ADR-0004 (splitting), ADR-0006 (manifest) and ADR-0007 (quality flags) as the behaviors
the example must exhibit. It amends ADR-0008 (testing) with one additional test.

The ticket framed three candidate sources — own recordings, synthetic/generated audio, or
licensed public-domain data. The answer is **synthetic**, plus documentation for bring-your-own.
Licensed public-domain speech is rejected outright: it would require a network fetch step or a
committed third-party corpus, and buys a realism this example does not need.

## Decisions

### Source — synthetic tones, committed, loudly labelled

- `examples/data-in/` holds a committed `recordings.csv` and ~12 committed WAVs. A reader clones
  and runs `build --data-in examples/data-in --data-out /tmp/out` with **no downloads, no
  recording, and no prerequisites**.
- The audio is **generated tones, not speech**, and `examples/README.md` says so plainly and up
  front. Prompts remain honest English sentences.
- **The demo teaches the *shape* of a dataset, not its content — and admits it.** A row whose
  `text` is a real sentence while its WAV is a sine tone is a mismatch we state rather than
  disguise. Every mechanical thing the workbench does — hashing, normalization, quality checks,
  session-aware splitting, manifest emission, image rendering — is exercised faithfully.

### Privacy — refining ADR-0002

ADR-0002's "audio never enters git" was argued from **privacy**: captured human speech and the
speaker identity it carries. Generated tones carry no such payload, and ADR-0008 already commits
fixture WAVs under `tests/fixtures/reference/` on exactly this reasoning. The rule is therefore
refined to:

> **Captured audio never enters git; generated audio may.**

`examples/data-in/` is a normal input tree — **no `.gitignore` entries**, honoring ADR-0002's
no-audio-globs rule. At mono/16 kHz/16-bit (~32 KB/sec), ~12 clips of a few seconds is well under
a megabyte; size is not an argument either way.

### Shape — 2 speakers × 2 sessions, ~12 recordings

The shape is driven by what the example must demonstrate, not by taste:

- **4 sessions** clears ADR-0004's **≥3-session floor** with room to spare, so `val` and `test`
  each receive a real session and the first run prints **no produce-and-flag warning**. A demo
  whose first run warns teaches the wrong lesson.
- **One prompt recorded twice within a session**, making `(Session, Prompt)`-is-not-unique and
  **all attempts are data** (ADR-0001 / #2) visible in the data itself rather than asserted in
  prose.
- **Two speakers** triggers ADR-0004's report-only multi-speaker overlap note — which is how the
  reader learns disjointness is **session-level, not speaker-level**.
- **Exactly one recording generated below −30 dBFS**, tripping `low_volume` (ADR-0007). The
  reader sees `reports/quality.jsonl` and the summary do real work on the first run, and sees the
  flagged Sample **still present in the manifest** — ADR-0007's *included + flagged* policy
  demonstrating itself. One flag keeps the signal clean; three would read as a broken corpus.

### Generator — `examples/generate.py` imports `tests/synth.py`

- Both the generator **and** its committed output ship. ADR-0008 named `tests/synth.py` the
  **single source of fixture truth**; the example reuses that generator rather than duplicating
  tone-writing code. ADR-0008's separation of the example data from `tests/fixtures/reference/`
  was about the **fixtures**, not the **generator**, so reuse does not contradict it.
- Requires `tests/__init__.py`; `generate.py` runs from the repo root. `examples/` depending on
  `tests/` is an odd-looking arrow, but both are dev-time-only trees — nothing shipped depends on
  it, and the alternative (promoting a tone generator into `src/`) would widen the product
  surface for no user benefit.
- **Sync is enforced, not remembered** — see the ADR-0008 amendment below.

### Bring-your-own — `examples/README.md`

One document carries both halves: run the demo as-is, then copy `examples/data-in/` elsewhere,
replace the WAVs with your own (**WAV-only**, ADR-0005), edit `path` / `speaker_id` /
`session_id` / `prompt_text`, and run `validate` first.

**The demo CSV *is* the template.** There is no separate prompts file — ADR-0003 / #8 fixed the
input contract as a single `recordings.csv` with `prompt_text` as a column, so "example prompts"
and "example CSV" are the same artifact (which is what ADR-0002's *code repo = code + example
prompts only* permits). Nothing needs keeping in sync, and no committed CSV hard-aborts if built
as-is.

## Amendment to ADR-0008

A test regenerates the examples into a tmpdir and **byte-compares against the committed
`examples/data-in/*.wav`**. Drift between the generator and its committed output becomes a CI
failure rather than a maintenance chore, and the generator's determinism becomes a checked claim.

This is safe to assert **exactly**: ADR-0005's within-arch-only bit-exactness caveat stems from
soxr's FFT ULPs, and `examples/generate.py` writes 16 kHz mono directly and **never resamples** —
its output is plain numpy arithmetic and is cross-machine stable.

## Consequences

- A new user has a one-command path from clone to a real `--data-out`, and a documented path to
  their own corpus.
- ADR-0002's privacy rule is sharpened (captured vs. generated), not weakened. The privacy
  guarantee — no real speech, no real identity in git — is untouched.
- ADR-0008's suite gains one test; `tests/` gains an `__init__.py`.
- The example is **not** a believable speech corpus, and is not meant to be. Anyone wanting
  realism follows the bring-your-own path.
- `CONTEXT.md` is unchanged — the example data introduces no domain vocabulary.

## Rejected alternatives

- **Licensed public-domain speech (LibriVox / Common Voice PD)** — rejected; needs either a
  network fetch (non-hermetic, plus a licensing surface) or a committed third-party corpus. Buys
  realism the example does not need.
- **Own recordings** — rejected; real captured speech in git is exactly what ADR-0002 forbids,
  and the privacy rationale genuinely binds here.
- **Bring-your-own only (no committed audio)** — rejected; nothing runs out of the box, so the
  reader must work before seeing any output.
- **Generator script only (WAVs untracked)** — rejected; costs a second command and forces an
  output-dir gitignore entry that ADR-0002 explicitly ruled out.
- **Offline TTS at authoring time** — rejected; would make the demo real speech, but adds an
  authoring-time dependency and voice licensing, and produces WAVs nobody can regenerate without
  it. Honest labelling is cheaper than manufactured realism.
- **Prompts that describe the tone** (`text: "440 hertz sine tone"`) — rejected; nothing would
  lie, but it reads as a toy and teaches a wrong mental model of what a Prompt is.
- **Standalone duplicate generator in `examples/`** — rejected; ADR-0008's "single source of
  fixture truth" would quietly become false.
- **Sharing the demo tree with `tests/fixtures/reference/`** — already rejected in ADR-0008 and
  reaffirmed: the test tree optimizes for small + trips-a-flag + covers-a-split, the demo for a
  realistic worked example.
- **No example data at all** — rejected; a workbench a new user cannot run is a poor artifact.
