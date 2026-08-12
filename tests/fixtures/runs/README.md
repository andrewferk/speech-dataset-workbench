# Hand-authored Run fixtures

One directory per case, each an `sdw transcribe` Run as ADR-0019 defines it: `hypotheses.jsonl`
(the Hypothesis Record, `id`-ascending, fixed key order) and `run.json` (the provenance, and the
completeness sentinel). Nothing here is generated.

**They are hand-authored deliberately** (ADR-0025). ADR-0008's "fixtures are code" argument was
about *audio*, where the alternative to a generator is an opaque binary; JSONL is already a diff, so
the generator's advantage does not carry and its disadvantage does — a generated fixture computes
its own expected values, and a golden then proves only that the code agrees with itself.

The text is synthetic and no part of it derives from a real speaker, which is what makes committing
a Record legitimate: `tests/fixtures/` is one of the two entries in the privacy allowlist that
ADR-0026 extended to cover tracked `hypotheses.jsonl` (see `tests/unit/test_privacy_allowlist.py`).

Each case's `golden/report.txt` is the captured `sdw score --format text` stream over it, compared
byte-for-byte by `tests/e2e/test_score_goldens.py` (ADR-0025). ADR-0025's second golden per case,
`golden/report.json`, arrives with the JSON rendering (#163); nothing here emits one yet.

| Case | What it is for |
| --- | --- |
| `clean` | Four Samples across all three Splits, none failed, none over-length — the N = M Report, where the disclosure still prints, and the zero-error digest whose every rate is `0.00%`. |
| `disclosures` | Three Samples carrying one `hypothesis: null` Transcription failure and one `long_form` Sample, so the header's non-zero counts are exercised rather than only their absence. The failure also empties its own Prompt group and halves its Split group, so a Breakdown losing a Sample to a failure is goldened rather than assumed. |
| `normalization` | Tab / newline / non-breaking-space in one Reference (ADR-0018's 200% trap), combining marks in another, and `Don't stop, Mr. O'Brien.` — where the two tiers genuinely disagree, so the B − A delta is pinned by a fixture rather than by zero. |
| `degenerate` | ADR-0018's edge-case table: an empty Reference against a non-empty Hypothesis, empty against empty, and a Reference (`Um, uh.`) that Tier B normalizes to `""` while Tier A keeps two tokens. |
| `errors` | A WER above `1.0`, an equal-cost alignment pinning the backtrace tie-break, and two Samples tied at 25% so the worklist's `id` tie-break is exercised. |
| `single` | A Scope of one Sample: every Breakdown is one group, so each Macro is that group's own rate and the standard deviation is a true `0.0` rather than a second `null` (ADR-0018 as annotated by #161). |

The four refusals are not committed as fixtures. A truncated Record, a missing `run.json`, a
`--split` selecting no Samples and a Scope with zero Reference tokens are produced in
`tests/e2e/test_aborts.py` by breaking a copy of `clean` a single way, which is that suite's own
idiom: the same good input, made bad.

## The values were checked against an oracle once, then frozen

ADR-0025 addresses this to #138 by name: check the hand-computed goldens against a dev-only oracle
on first authoring, and stop there. Every per-Sample WER and CER above was compared against `jiwer`
over the *normalized* strings each tier produces — **no disagreements**. `jiwer` is not a test
dependency, is installed by no CI job, and appears in no `pyproject.toml`; our own scorer is the
long-term source of truth.

One difference is real and is ours by contract. On `errors`' `north south` / `south north` both
sides agree the WER is `1.0`, and the S/D/I split is ambiguous because two alignments cost the same:
`jiwer` reports one insertion and one deletion, we report two substitutions. ADR-0018 fixed our
backtrace tie-break — diagonal, then deletion, then insertion — as *a contract obligation, not an
implementation note*, precisely so this case has one answer; the fixture exists to hold it.
