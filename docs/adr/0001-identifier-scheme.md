# Identifier scheme for v0.1 entities

We fix how each core entity's id is formed, and what makes it stable, because ids are referenced
by storage layout, the manifest, and reproducibility — changing the scheme later would break all
three. Two kinds of id coexist: **content-derived** (intrinsic, reproducible) where an entity's
identity is its bytes or text, and **human-assigned** (declared at import) where identity is a fact
only the operator knows.

## Decisions

- **`prompt_id` — content-derived from the Prompt text.** A hash/slug over the normalized prompt
  text. The same sentence yields the same id across Sessions and rebuilds, so Prompts deduplicate
  naturally. Identity of a Prompt *is* its text.

- **`recording_id` — content hash of the Original audio.** The Recording's identity is the captured
  bytes. Consequences: two Attempts of the same `(Session, Prompt)` differ in audio and so get
  distinct ids automatically (Recording needs no separate attempt counter for identity), and
  byte-identical files collapse to one Recording. `(Session, Prompt)` is deliberately **not** a key.

- **`speaker_id` — human-assigned.** A stable handle the operator declares at import (e.g.
  `spk_andrew`). Not derivable from audio; the mapping of voice → person is external knowledge.

- **`session_id` — human-assigned.** A stable handle declared at import (e.g. a date/label). A
  Session groups Recordings sharing one Speaker, Device, and Environment on one occasion.

- **Dataset — no id.** One Dataset per workbench; the directory is the identity.

- **`dataset_version` — content-derived.** A hash over the emitted manifest, the effective config,
  and the tool version. Identical inputs always produce the same version id, making a build
  intrinsically reproducible with no external version registry.

  > **Amended by ADR-0010.** This originally read "a hash over the sorted Sample content-hashes plus
  > the normalization params and tool version". Both terms have since been superseded. The
  > content-hashes alone cover only the Original *audio bytes*, so a metadata-only edit in
  > `recordings.csv` (a prompt typo, a relabelled `session_id`) produced a colliding id across two
  > different manifests — the CSV sidecar did not exist when this was written. And "normalization
  > params" is now an empty set: ADR-0005 made normalization fixed constants with no config section,
  > and they ride in via the tool version. ADR-0010 pins the byte-exact preimage; the decision here —
  > content-derived, no registry — stands unchanged.

- **`sample_id`.** In v0.1 Samples map 1:1 to Recordings, so a Sample is identified by its
  `recording_id`.

## Considered and rejected

- **Composite readable `recording_id`** (`{speaker}/{session}/{prompt}/{attempt}`) — human-readable
  and stable under re-import, but requires tracking an attempt ordinal and does not dedupe identical
  files. A separate `content_hash` field remains available for integrity where a readable path is
  also wanted (a storage-layout concern, not identity).
- **Sequential/labeled `dataset_version`** (`v1`, `v2`, timestamps) — rejected as extrinsic: it
  needs a registry or human bookkeeping and breaks the "identical inputs → identical output"
  guarantee this project treats as its reproducibility substitute for DVC-style tooling.
