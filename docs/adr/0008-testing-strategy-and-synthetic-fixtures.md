# Testing strategy & synthetic audio fixtures (v0.1)

We fix how v0.1 is tested: how deterministic audio fixtures are synthesized without shipping real
recordings, how the suite is layered, how the reproducibility contract is asserted, and how each
pipeline stage's success/abort behavior is covered. Testing is where the guarantees the other ADRs
promise — deterministic normalization (ADR-0005), the atomic `--data-out` commit (ADR-0003), the
two-outcome quality model (ADR-0007), the byte-identical-artifact reproducibility contract (#8) — are
actually held to account. This ADR builds on research #3 (pytest, `uv`, `mypy --strict` CI gate,
src-layout), ADR-0002 (`.gitignore` carries no audio globs, so synthetic WAVs are committable), and
ADR-0004/0005/0006/0007/#8/#9 for the behavior under test. It plans the strategy; it writes no test
code (that is an implementation session's job).

## Decisions

### Fixtures are synthesized in-repo (hybrid, synth-primary)

All fixtures originate from a single in-repo generator, **`tests/synth.py`**, backed by **one small
committed reference `--data-in`** for the headline end-to-end test. No external audio, ever.

- **`tests/synth.py`** is the sole home for *all* fixture creation — well-behaved signals, signals
  that deliberately trip a quality flag, and the degenerate abort inputs. Fixtures are therefore
  *code*: parameterized, reviewable in a diff, and the generator is itself a tested unit.
- The **committed reference tree** (`tests/fixtures/reference/`) is a single small `--data-in` — a
  handful of synthetic WAVs across a couple of Sessions plus its `recordings.csv` — generated once by
  the synth helper and committed. It anchors the golden end-to-end test and doubles as a
  human-inspectable worked example. It is deliberately **kept separate** from the demo/example data
  of the seed-data ticket (#15): the test tree optimizes for "small + trips a flag + covers a Split,"
  #15's data optimizes for "realistic worked example."

**Synth helper surface.** A core generator writes a tone whose properties are known by construction:

```
write_wav(path, *, freq_hz, amp_dbfs, duration_s, sample_rate, bit_depth, channels, seed=None)
```

- `amp_dbfs` aims `active_rms_dbfs` to trip / clear `low_volume`;
- `duration_s` to trip / clear `duration_out_of_range`;
- `sample_rate` / `bit_depth` / `channels` drive normalization (48 kHz→16 kHz resample, stereo→mono
  downmix, 24-bit→16-bit, and the already-16 kHz-mono passthrough path);
- `seed` yields reproducible white noise for a non-tonal case.

Named shortcuts build on it: **`silence`** (all-zero / sub-threshold — exercises the silence metrics
and the wholly-silent → `low_volume` floor), **`clipped`** (a genuine ≥3-sample flat-top run at
≥0.99 FS, emittable at multiple bit depths — trips `clipping`, measured on the Original pre-resample),
and **`leading_trailing_silence`** (a tone padded head/tail — exercises the 0.2 s guard and
active-region trimming). The **abort inputs** live here too: **non-WAV bytes** (a `.wav` that is
actually text/PNG → decode-fail) and a **zero-frame WAV** (valid header, no samples).

### Two test layers, unit-heavy

The bulk of assertions are pure/near-pure **unit tests**, pushed as far down as each behavior will go:
normalization (downmix-mean, soxr 16 kHz, `PCM_16`, passthrough, idempotence), quality-metric math
against signals with known peak/RMS/duration and deliberate flag-tripping, id and `dataset_version`
hashing, session-water-fill split determinism (same seed → same partition, the ≥3-sessions rule, the
<3 produce-and-flag path), manifest rows and both consumer views, and `recordings.csv` parsing
(absolute/`..` path rejection, unlisted-files-ignored). A **thin end-to-end layer** runs full
`build`/`validate` invocations for the things only a whole run reveals: exit codes, the atomic commit,
cross-artifact consistency, and artifact byte-stability. Metric math is never tested through an e2e
run when a unit test will do.

### Reproducibility contract — golden files where cross-machine stable, build-twice-diff for bytes

ADR-0005 guarantees normalization is byte-identical *within* a fixed architecture but **not**
cross-arch bit-exact (soxr FFT ULPs). That splits the contract's artifacts by testability:

- **Golden-file exact equality** for the cross-machine-stable artifacts — `train/val/test.jsonl`,
  `dataset.json`, `quality.jsonl`, `summary.txt`, and an exact committed `dataset_version` string.
  These are Original-derived + structural + config: even manifest `duration` is `num_frames / 16000`,
  and the output frame count is a deterministic function of input length × resample ratio, not a ULP
  quantity. Committed goldens double as readable documentation of the output format.
- **Build-twice-and-diff** for byte-identity of the *whole* `--data-out` (Normalized WAVs **and**
  PNGs): build the same input+config into two tmp dirs and assert the trees are byte-for-byte
  identical. This asserts the "byte-identical artifacts" clause without committing arch-fragile
  binaries. **No golden WAVs and no golden PNGs are committed.**
- **`quality.jsonl` stays an exact golden** despite carrying four Normalized-derived float metrics
  (`active_rms_dbfs`, `leading_silence_s`, `trailing_silence_s`, `silence_ratio`) by **parking the
  reference fixtures away from rounding cliffs** — the synth helper chooses amplitudes/durations whose
  rounded values sit comfortably between cliffs. This keeps one clean rule ("golden files are exact")
  with no per-field tolerance machinery.

### Stage success / abort coverage

- **Table-driven abort suite**, one synth fixture per case, each asserting a **non-zero exit AND no
  durable `--data-out`**: non-WAV decode-fail, zero-frame WAV, malformed `recordings.csv` (missing
  column), a `path` that is absolute or contains `..`, and split ratios ≤0 or not summing to 1.
- **Atomicity (in scope for v0.1):** a pre-existing `--data-out` is byte-preserved when a build
  aborts (pre-populate it, trigger a hard abort, assert the old tree is unchanged); stale `.tmp`/
  `.old` siblings are cleaned on start; and `dataset.json` is the last artifact written (the sentinel).
- **Soft-flag pass-through:** a `--data-in` that trips a quality flag still yields the flagged Sample
  in the manifest and in `quality.jsonl`, and `validate` exits 0 despite the flag.

### Images — byte-reproducible now, pixel goldens deferred

The generated PNGs (`images/<recording_id>.{waveform,spectrogram}.png`) are part of `--data-out`, so
the build-twice-diff reproducibility test holds them to **byte-identity across two builds**. Because
matplotlib/Agg embeds metadata (software/timestamp chunks) by default, satisfying this **requires the
image stage to write deterministic PNGs** — no timestamps, no software metadata, fixed figure size and
DPI. A byte-identity failure on an image is a real determinism bug to fix, not an exemption. Beyond
that, e2e tests only smoke-check that the expected image files **exist and are valid PNGs**; the
render spec is still unspecified, so any **pixel/content golden is deferred to the
visualization-spec** work, which inherits "PNGs must be deterministic" as a hard constraint.

### CI

The suite is a **required CI gate** alongside `ruff` and `mypy --strict`; a red suite blocks merge
(cheap — no models, tiny synth fixtures). **Coverage is measured, not enforced** (`pytest-cov`,
reported without a pass/fail percentage): the explicit coverage this ADR enumerates — every stage, the
abort table, the reproducibility contract, atomicity, soft-flag pass-through — is the gate, not a
gameable number. CI runs single-OS on the pinned Python floor (`>=3.13`); the cross-arch caveat is
documented, not CI-enforced, and the reproducibility tests are self-consistent build-twice-diffs that
pass on any single arch.

### Layout

```
tests/
  synth.py                    # the sole fixture generator (well-behaved, flag-tripping, abort inputs)
  conftest.py                 # shared pytest fixtures (tmp --data-in/--data-out builders)
  unit/                       # normalization, metrics, hashing, splitting, manifest, csv
  e2e/                        # full build/validate runs
  fixtures/
    reference/                # the single committed reference --data-in
      recordings.csv
      *.wav
      golden/                 # committed expected text artifacts (no golden WAVs, no golden PNGs)
        train.jsonl  val.jsonl  test.jsonl
        dataset.json
        quality.jsonl  summary.txt
```

## Consequences

- The synth helper is a load-bearing test asset and a tested unit in its own right; its determinism is
  a precondition for every downstream golden and diff.
- The reproducibility test suite passes on any single architecture without committing binary goldens,
  so it survives ARM-dev / x86-CI splits — at the cost of not pinning exact WAV/PNG bytes across
  machines (which ADR-0005 says is impossible anyway).
- A new cross-cutting constraint falls out for the (future) visualization-spec work: **the image stage
  must produce deterministic PNGs** (stripped metadata, fixed size/DPI) to satisfy #8's byte-identity
  contract.
- Testing introduces no domain vocabulary, so `CONTEXT.md` is unchanged (it is a domain glossary with
  no implementation detail; synth/golden/reference-tree are testing terms).

## Rejected alternatives

- **Pure committed WAV corpus (no synth)** — rejected; opaque binaries drift into magic files, can't
  be reviewed in a diff, and duplicate what parameterized synth code already expresses. A single small
  reference tree is kept only to anchor the golden e2e test.
- **Committed golden Normalized WAVs / golden PNGs** — rejected; normalization is not cross-arch
  bit-exact (ADR-0005) and matplotlib PNGs aren't naturally byte-stable, so such goldens would be
  flaky across machines. Byte-identity is asserted by build-twice-diff instead.
- **Per-field float tolerance on `quality.jsonl`** — rejected in favor of parking fixtures away from
  rounding cliffs, which preserves plain exact-file golden comparison with no tolerance machinery.
- **A hard coverage-percentage gate** — rejected for a solo learning project; it invites gaming and
  busywork. Coverage is measured and visible; the enumerated behaviors are the real gate.
- **Sharing the test reference tree with #15's demo data** — rejected; the two optimize for different
  things (minimal-flag-tripping vs. realistic worked example). Kept separate.
