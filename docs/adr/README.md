# Decision records

Twenty-six architecture decision records — 0001–0014 shaped v0.1, and 0015 onward is v0.2. Each states
what was decided and why, and — usually at greater length — what was considered and rejected, so a
reader who disagrees can find out whether their objection was already answered.

They are **immutable once decided**. A decision that changes is not edited away; the correction is
written into the ADR *against the text it corrects*, so reading one top to bottom tells you both
what was decided and what has happened to it since. That is why this index has an amendment column
rather than a status field: nothing here is retired, and some of it has moved.

You do not need to read them in order. Arrive with a question and take the row that answers it.
Numbering is chronological, and 0001–0003 — identity, the stateless transform, the storage layout —
fix the foundations every later ADR assumes.

## Reading the `Amended by` column

| Cell | What it means |
| --- | --- |
| *blank* | The ADR stands as written. |
| `in place` | The ADR carries the correction itself, set against the text it corrects. Read it and you have the current decision. |
| `ADR-00NN` | That ADR amended this one. Read it for the reasoning behind the change — and, where `in place` is absent, for the current decision itself. |

Most amended ADRs carry both, because annotating the stale text where it sits is this repo's
practice. **ADR-0002 is the one that does not:** its refinement lives only in ADR-0009, so that row
is the one place where reading the ADR alone leaves you with a rule the repo no longer follows.

## The records

| ADR | Decision | Amended by |
| --- | --- | --- |
| [0001](0001-identifier-scheme.md) | Ids are content-derived where identity is the bytes or the text (`recording_id`, `prompt_id`, `dataset_version`) and human-assigned where only the operator knows it (`speaker_id`, `session_id`). | ADR-0010, in place |
| [0002](0002-stateless-data-in-data-out.md) | The tool is a stateless transform from a read-only `--data-in` to a fully regenerable `--data-out` — which is what makes privacy architectural, and deletion the operator's own file-system action rather than a command. | ADR-0009 |
| [0003](0003-storage-layout-naming-retention.md) | One current build per `--data-out`, files named by `recording_id`, `audio/` bucketed by split, committed atomically through a sibling staging directory with `dataset.json` written last as the completeness sentinel. | in place |
| [0004](0004-session-aware-splitting.md) | A whole Session lands in exactly one split, chosen by deterministic water-filling with a non-emptiness repair — so disjointness is session-level, not speaker-level. | ADR-0010, in place |
| [0005](0005-input-formats-and-normalization-target.md) | PCM WAV in; mono, 16 kHz, 16-bit PCM out, by fixed constants with no gain change and no config section. "Normalization" means format, never loudness. | |
| [0006](0006-output-manifest-format.md) | Per-split JSONL is the canonical Manifest (NeMo-native), `audio/<split>/metadata.jsonl` is the zero-code Hugging Face view, and `dataset.json` describes the build. | ADR-0010, ADR-0017, in place |
| [0007](0007-audio-validation-quality-checks.md) | Quality is measured and reported, never acted on: anything that decodes ships as a Sample carrying zero or more of exactly three advisory flags, over four configurable thresholds. | |
| [0008](0008-testing-strategy-and-synthetic-fixtures.md) | Fixtures are synthesized in-repo rather than recorded; exact goldens pin the artifacts that are stable across machines, and build-twice-and-diff pins the bytes that are not. | ADR-0009, ADR-0025, in place |
| [0009](0009-seed-example-data.md) | `examples/` ships committed synthetic tones — 2 speakers, 4 sessions, ~12 recordings — shaped so the first run demonstrates splitting, the flag policy and speaker overlap, and labelled as tones rather than speech. | ADR-0012, ADR-0026, in place |
| [0010](0010-dataset-version-and-provenance.md) | `dataset_version` is a `sha256` over a byte-exact preimage — domain separator, tool version, canonical effective config, and the three manifest files framed by name and byte length — making it recomputable from `--data-out` alone. | ADR-0020, in place |
| [0011](0011-visualization-output.md) | Two PNGs per Recording as an operator inspection aid, on fixed absolute scales so the picture can never contradict the flag; the stage reads no config and states measurements, never verdicts. | in place |
| [0012](0012-v0-1-acceptance-criteria.md) | v0.1 is done when CI is green, three checks pass (examples build, privacy allowlist, audit recipe), a human has walked the example once, and `v0.1.0` is tagged — with no ADR-indexed checklist, which would be a second source of truth. | ADR-0014, ADR-0026, in place |
| [0013](0013-recordings-csv-ingest-and-duplicate-resolution.md) | A fixed six-column `recordings.csv` is the authority on what the Dataset contains; paths stay relative and inside `--data-in`, and byte-identical Originals collapse when their metadata agrees and abort when it conflicts. | |
| [0014](0014-build-backend-and-installed-entry-point.md) | A `hatchling` build backend, so `uv sync` installs the package and the entry point is `sdw` — removing the four unchecked copies of `PYTHONPATH=src`. | ADR-0023, in place |
| [0015](0015-evaluation-vocabulary.md) | Evaluation's vocabulary: Transcription is attributed and emits a Hypothesis Record, Scoring is reproducible and derives Metrics; `Reference` narrows to a role, `Normalization` stays audio-only, and a Run is deliberately not a Version. | |
| [0016](0016-asr-backend-model-selection-and-pinning.md) | `transformers` against `openai/whisper-large-v3-turbo` pinned by commit sha, hard-coded not configurable, called through the explicit processor so no path ever reaches FFmpeg — greedy with no guards, CPU-only, language from the manifest, and every condition recorded rather than assumed. | ADR-0019, ADR-0020, in place |
| [0017](0017-evaluation-command-surface.md) | Two commands — `transcribe` covers the whole Dataset Version with no knobs, `score` picks the view from a self-contained Hypothesis Record — with structural checks preflighted before the model loads and the Run's provenance written last as the completeness sentinel. | ADR-0018, ADR-0019, ADR-0021, ADR-0022, ADR-0023, in place |
| [0018](0018-text-normalization-and-metric-semantics.md) | Two Normalizers always run and neither is configurable — a minimal Tier A as the headline, OpenAI's vendored normalizer as the labelled second pass — scored by our own Levenshtein into WER/CER/SER, Pooled everywhere, with empty References retained and undefined per-Sample rates emitted as `null`. | ADR-0020, ADR-0022, ADR-0023, in place |
| [0019](0019-hypothesis-record-format.md) | A Run holds `hypotheses.jsonl` and `run.json`; one Record file covers every Split, denormalizing the Reference and every Breakdown attribute onto lines ordered by content-derived `id` — with `hypothesis: null` the sole failure marker, and the sentinel carrying a line count `score` checks. | ADR-0020, in place |
| [0020](0020-evaluation-run-provenance-record.md) | A Run has **no id** — its handle is its directory name — and `run.json` carries provenance instead, in nested blocks drawn so the comparability rule reads off them: wall-clock and host facts belong here because the v0.1 exclusion was scoped to files that must diff clean, and `tool_version` turns out to have three occurrences, not two. | |
| [0021](0021-evaluation-output-layout-and-run-retention.md) | Runs accumulate under `--eval-out` and nothing prunes them, each in a `run-<UTC start>` directory that is a renameable handle rather than a record — while the Report is never written at all, making `score` read-only and a Run's bytes fixed at the end of Transcription. | ADR-0022, ADR-0026, in place |
| [0022](0022-evaluation-report-content-and-breakdowns.md) | One Report, two renderings of one stdout stream (`--format text\|json`) — a fixed-shape digest in percentages over a worklist sorted worst-first, and a JSON document carrying every per-Sample count, alignment and normalized text — with all five Breakdowns annotated by group size, no confidence interval, no Quality flags, and the word "Baseline" never printed. | ADR-0024, in place |
| [0023](0023-packaging-optional-dependencies-and-the-import-boundary.md) | The ASR dependencies sit behind a PEP 621 `asr` extra — a PEP 735 group could never work, since groups are absent from published metadata — with `sdw/transcribe/` and `sdw/score/` splitting the module tree exactly on the dependency line, `sdw.cli` importing no command module at module level, absence probed rather than caught, and the two boundaries that cannot be made structural enforced by an AST import-graph test under `pytest`. | in place |
| [0024](0024-cross-run-comparison-surface.md) | v0.2's cross-run comparison surface is a **header change**, not a command: the Report quotes the Run's Transcription provenance — `run.json` verbatim in JSON, tier-organised in the digest — so `diff` of two Reports applies every tier check of ADR-0020's rule and only its `dataset_version` escalation still needs both Records, and a cross-run delta is recorded as paired but **not** exact, resting on an unmeasured non-determinism floor. | ADR-0026, in place |
| [0025](0025-testing-strategy-for-v0-2.md) | Testing splits on the reproducibility seam: Scoring inherits ADR-0008 wholesale from **hand-authored Run fixtures** goldened as captured stdout, while Transcription is tested behind an internal seam with a fake in the torch-free `check` job — no CI job ever downloads weights or decodes, build-twice-and-diff does not transfer, and release-time golden churn is accepted under a bounded-diff rule. | ADR-0026, in place |
| [0026](0026-v0-2-acceptance-criteria.md) | v0.2 is done when ADR-0012's criteria still hold, three CI jobs are green, `examples/` ships a **genuine committed Run** whose garbage numbers over tones are the lesson, and a human has once run the real model on real speech — with `transcribe` recorded as **undemonstrable** by construction, no Baseline required to exist, and the privacy allowlist extended to `hypotheses.jsonl`. |  |
