# Auditing a build — recomputing `dataset_version`

`dataset_version` is a `sha256` you can recompute from a `--data-out` tree **alone**, without the
`--data-in` that produced it ([ADR-0010](adr/0010-dataset-version-and-provenance.md)). That is what
makes the id useful to someone who receives a Dataset and not its inputs: the tree carries
everything needed to check that its bytes and its recorded id agree.

There is no `verify` command — the two-command spine (`build`, `validate`) stands — because the
recipe below is all it would be. Follow it by hand, or in ~15 lines of any language.

## The recipe

1. **Read `dataset.json`.** Take the `tool_version` string and the entire `config` object.
2. **Re-serialize `config` canonically:** keys sorted, no whitespace between tokens
   (`,`/`:` separators), UTF-8, non-ASCII left as-is. These are the exact bytes `dataset.json`
   already stores for that block, so a canonical dump of the parsed object reproduces them.
3. **Build the preimage** — a byte string, in exactly this order, with `\n` as shown:

   ```
   sdw-dataset-version/1\n
   tool_version\n<tool_version>\n
   config\n<canonical config JSON>\n
   train.jsonl <byte-length>\n<raw bytes of train.jsonl>
   val.jsonl <byte-length>\n<raw bytes of val.jsonl>
   test.jsonl <byte-length>\n<raw bytes of test.jsonl>
   ```

   `sdw-dataset-version/1` is a domain separator whose `/1` versions the scheme. Each split file is
   framed by its **name and exact byte length** before its **raw bytes read from disk** (never
   re-serialized), in the fixed order `train`, `val`, `test`. An empty `val`/`test` frames cleanly
   at length `0`.
4. **`sha256` the preimage**, hex-encode it, and prefix `sha256:`. That string must equal
   `dataset_version` in `dataset.json`.

## What a mismatch means

The tree's bytes and its recorded id disagree — either the Dataset was tampered with, or this
recipe and the tool have drifted. Which one it is cannot be decided from the mismatch alone, and
that is deliberate: see *How this recipe is kept honest* below.

A **match** says less than it might appear to. `dataset_version` identifies the three inputs the
preimage above hashes — the **Manifest, the effective config, and the tool version** — and not the
Normalized audio bytes, which derive from resampled floats that
[ADR-0005](adr/0005-input-formats-and-normalization-target.md) establishes are not cross-arch
bit-exact, so an id covering them could not be stable across machines at all. Audio is covered
instead through each Sample's `content_hash` — a `sha256` of the **Original**, bytes at rest and so
byte-exact on every machine.

That coverage is inherited, not recomputable here. The Originals live in `--data-in`, which this
recipe deliberately does not need, so nothing in a `--data-out` tree can recompute a `content_hash`;
and the **Normalized** WAVs under `audio/` are hashed by nothing at all. Verifying audio bytes means
going back to the inputs, and this recipe never touches them.

`dataset.json`'s `hashing.dataset_version` field carries a one-line summary of this same recipe, so
the artifact explains its own id standalone — a reader holding only the tree learns what the id
covers without finding this file.

## How this recipe is kept honest

This recipe is checked in CI by `tests/e2e/test_audit_recipe.py`, which reimplements it
**independently — importing nothing from `src/`** — and runs it against the committed reference
build at `tests/fixtures/reference/golden/`. A test sharing the tool's own hashing code would
compute `f(x) == f(x)` and pass even when both the code and this prose are wrong; the two are kept
honest only by being written twice and edited together
([ADR-0012](adr/0012-v0-1-acceptance-criteria.md) Check 3).

That test is also the worked example this document does not print. A hash quoted here would be a
third copy of the answer that nothing checks — stale the moment the golden is re-baselined — whereas
the golden tree plus its independent recomputation is a worked example that fails loudly when it
stops being true. Read the test to see the recipe as ~15 lines of Python; run it against
`tests/fixtures/reference/golden/` to watch it come out equal to that tree's recorded
`dataset_version`.
