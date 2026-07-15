# Stateless `--data-in` → `--data-out`, privacy, and deletion

The workbench is a **stateless, deterministic transform**: it reads an immutable input
directory (`--data-in`) and writes derived artifacts to an output directory (`--data-out`),
managing no state of its own. Privacy, the git boundary, and deletion semantics all follow
from this shape rather than being designed separately. Fixing it now because it constrains the
CLI surface (issue #8), the storage layout (issue #9), and every pipeline stage that reads input
or emits output.

## Decisions

- **Stateless in → out.** `--data-in` (external, read-only) holds raw Originals + capture
  metadata + the authoritative Prompts in use. `--data-out` (external, regenerable) holds all
  derived artifacts — Normalized audio, the manifest, Dataset Versions, waveform/spectrogram
  images, quality reports. The tool never writes to, modifies, or deletes anything in
  `--data-in`. A build is a pure function of `--data-in` + pinned pipeline params.

- **Privacy is architectural.** Raw audio never enters source control because it lives only in
  the two external directories the code repo never contains — not because a gitignore rule
  blocks it. The code repo holds code + *example* Prompts only.

- **Pseudonym-only metadata.** `speaker_id` is an opaque human-assigned handle (per ADR-0001);
  the tool stores no real names or consent records in v0.1. The manifest is therefore freely
  shareable — relative paths + content hashes + pseudonymous ids, no PII, no audio bytes.

- **`.gitignore` lives in the code repo only** and covers Python/tooling artifacts plus an
  optional local `config.toml` (with a committed `config.example.toml`). `uv.lock` is committed
  (ADR follows research #3). **No audio globs** (they would fight committed synthetic test
  fixtures); **no output-dir ignore** (`--data-out` is an explicit external path). The
  `--data-in`/`--data-out` directories carry no seeded `.gitignore` — they are unversioned by
  design.

- **No deletion command; no tool-managed state to delete.** Removing a Recording from the
  dataset means deleting its Original from `--data-in` (the operator's own file-system action)
  and re-running; the next build reflects the smaller input as a new `dataset_version`. Removing
  derived data means deleting or overwriting `--data-out`, which is safe because it is fully
  regenerable. Hard-delete on the working set holds — the working set is whatever Originals are
  present in `--data-in`, and the deleting hand is the operator's.

- **One Dataset = one `--data-in` set.** This refines CONTEXT.md's "one Dataset per workbench
  directory" framing: there is no managed workbench directory — the Dataset is defined by the
  contents of `--data-in`, transformed into `--data-out`. Does not affect ADR-0001 identifiers.

## Considered and rejected

- **A managed data-root with in-tool deletion** (`init` scaffolds a directory the tool owns;
  `delete recording/session/speaker` subcommands with dry-run + confirmation) — rejected as
  stateful complexity that puts irreplaceable raw captures at risk from tool actions and adds
  cascade/safety machinery a stateless transform doesn't need.
- **Seeding a `.gitignore` into the data directory** — inert unless that directory becomes a git
  repo, which the unversioned-external model rejects; speculative clutter.
- **Tombstones / a persistent deletion ledger** — extrinsic provenance bookkeeping, DVC-adjacent;
  contradicts the project's intrinsic-reproducibility substitute (content hashes + deterministic
  pipeline + manifest).
- **An exclusion / curation list** (drop a bad take from a build without deleting its raw
  capture) — contradicts the settled domain rule that in v0.1 *all attempts are data, no keeper
  selection*.
- **A real-identity / consent sidecar** — deferred to v0.2; v0.1 is pseudonym-only.
