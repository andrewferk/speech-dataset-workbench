# `recordings.csv` ingest, path resolution, and duplicate resolution

We fix how the first pipeline stage turns the hand-authored `recordings.csv` at the `--data-in`
root into resolved, content-identified Recordings, and — the one open question this ticket must
close (#24) — what happens when two rows carry byte-identical Originals but conflicting metadata.
This builds on ADR-0001 (identifiers), ADR-0002 (stateless `--data-in` → `--data-out`), ADR-0005
(WAV-only ingest gate), and ADR-0006 (manifest fields); it does not reopen them, only makes their
ingest consequences concrete.

## Decisions

### The index — one fixed-name CSV, RFC-4180, the exact six columns

- `recordings.csv` is read from a **fixed name at the `--data-in` root** — not configurable. It is
  RFC-4180 and must have at least one data row.
- Columns are exactly `path, speaker_id, session_id, prompt_text, device, environment`. A missing
  column aborts; an unexpected column aborts too (it is almost always a typo'd required column, and
  silently ignoring it would drop metadata from the Manifest). Column *order* in the file is free —
  RFC-4180 does not fix it.
- A ragged row (more or fewer fields than the header declares) aborts.

### Paths — POSIX, relative, within `--data-in`

- `path` is POSIX and relative within `--data-in`. An **absolute path or a `..` component aborts**,
  so a `--data-in` set stays self-contained and portable — it can be moved or copied whole and every
  Original still resolves. A backslash aborts as non-POSIX (on POSIX it is a literal filename byte,
  so a Windows separator would not resolve as intended).
- A listed Original that is **not on disk aborts** — the CSV is a claim about the corpus, and a
  broken claim is structural, not advisory.
- Files present under `--data-in` but **absent from the CSV are silently ignored** — not an error,
  not a warning. `--data-in` is the operator's external drop; the CSV, not the directory, is the
  authority on what the corpus contains.

### Identity — content-derived, hashing bytes and text

- `recording_id` = `rec_` + first 16 lowercase hex of `sha256(Original file bytes)`; `content_hash`
  = `sha256:` + the full 64 hex. Same bytes.
- `prompt_id` = `prm_` + first 16 hex of `sha256` over the prompt text NFC-normalized, trimmed, and
  whitespace-collapsed — **no case or punctuation folding**, so `"Hello."` and `"hello"` are
  distinct Prompts (ADR-0001/0006).
- Ingest **does not decode** the audio. It reads bytes to hash them; the WAV-decodability gate
  (ADR-0005) is the normalization stage, a later ticket.

### The open question — byte-identical Originals collapse; conflicting metadata aborts

ADR-0001 says byte-identical Originals collapse to one Recording. Two rows with byte-identical audio
but a different `session_id`, `prompt_text`, `speaker_id`, `device`, or `environment` collapse to
one `recording_id` and one audio path, yet imply **two conflicting Manifest rows**. No prior ADR
resolves this.

- **Byte-identical Originals whose metadata agrees collapse to one Recording** (ADR-0001) — the same
  file listed twice, or copied to two paths, is one true Recording seen twice. `path` is deliberately
  *not* part of this comparison: two different paths pointing at identical bytes is exactly the
  collapse case.
- **Byte-identical Originals whose metadata conflicts abort.** This is the ADR-consistent read:
  the input is ambiguous, and silently picking one row would break the Manifest being a total
  function of what decoded. The abort names both paths, the shared `recording_id`, and the field
  that disagrees.

## Considered and rejected

- **Silently picking the first (or last) conflicting row** — makes the Manifest depend on CSV row
  order, an extrinsic fact the content-derived identity scheme exists to eliminate; a relabelled
  duplicate would silently shadow real metadata.
- **Warning and continuing** — the conflict has no non-arbitrary resolution, so a warning just
  defers an unanswerable question to the operator after the fact; a hard abort surfaces it up front,
  consistent with the stateless "abort with no durable output" contract (ADR-0002/0003).
- **Aborting on *every* duplicate, even agreeing ones** — contradicts ADR-0001's byte-identical
  collapse and would reject a corpus that merely lists the same take under two paths.
- **Treating an unexpected extra column as advisory** — a mis-named required column would then be
  dropped silently and its metadata would vanish from the Manifest; strict is safer.
- **Policing `--data-in` for files missing from the CSV** — the drop is the operator's; the CSV is
  the authority, so unlisted files are ignored, not flagged (#24).
