# Decision records

Fourteen architecture decision records, one per decision that shaped v0.1. Each states what was
decided and why, and — usually at greater length — what was considered and rejected, so a reader
who disagrees can find out whether their objection was already answered.

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
| [0006](0006-output-manifest-format.md) | Per-split JSONL is the canonical Manifest (NeMo-native), `audio/<split>/metadata.jsonl` is the zero-code Hugging Face view, and `dataset.json` describes the build. | ADR-0010, in place |
| [0007](0007-audio-validation-quality-checks.md) | Quality is measured and reported, never acted on: anything that decodes ships as a Sample carrying zero or more of exactly three advisory flags, over four configurable thresholds. | |
| [0008](0008-testing-strategy-and-synthetic-fixtures.md) | Fixtures are synthesized in-repo rather than recorded; exact goldens pin the artifacts that are stable across machines, and build-twice-and-diff pins the bytes that are not. | ADR-0009, in place |
| [0009](0009-seed-example-data.md) | `examples/` ships committed synthetic tones — 2 speakers, 4 sessions, ~12 recordings — shaped so the first run demonstrates splitting, the flag policy and speaker overlap, and labelled as tones rather than speech. | ADR-0012, in place |
| [0010](0010-dataset-version-and-provenance.md) | `dataset_version` is a `sha256` over a byte-exact preimage — domain separator, tool version, canonical effective config, and the three manifest files framed by name and byte length — making it recomputable from `--data-out` alone. | in place |
| [0011](0011-visualization-output.md) | Two PNGs per Recording as an operator inspection aid, on fixed absolute scales so the picture can never contradict the flag; the stage reads no config and states measurements, never verdicts. | |
| [0012](0012-v0-1-acceptance-criteria.md) | v0.1 is done when CI is green, three checks pass (examples build, privacy allowlist, audit recipe), a human has walked the example once, and `v0.1.0` is tagged — with no ADR-indexed checklist, which would be a second source of truth. | ADR-0014, in place |
| [0013](0013-recordings-csv-ingest-and-duplicate-resolution.md) | A fixed six-column `recordings.csv` is the authority on what the Dataset contains; paths stay relative and inside `--data-in`, and byte-identical Originals collapse when their metadata agrees and abort when it conflicts. | |
| [0014](0014-build-backend-and-installed-entry-point.md) | A `hatchling` build backend, so `uv sync` installs the package and the entry point is `sdw` — removing the four unchecked copies of `PYTHONPATH=src`. | |
