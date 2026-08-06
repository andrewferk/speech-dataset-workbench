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

| Case | What it is for |
| --- | --- |
| `clean` | Four Samples across all three Splits, none failed, none over-length — the N = M Report, where the disclosure still prints. |
| `disclosures` | Three Samples carrying one `hypothesis: null` Transcription failure and one `long_form` Sample, so the header's non-zero counts are exercised rather than only their absence. |

The two Record-integrity refusals — a truncated Record and a missing `run.json` — are not committed
as fixtures. They are produced in `tests/e2e/test_aborts.py` by breaking a copy of `clean` a single
way, which is that suite's own idiom: the same good input, made bad.
