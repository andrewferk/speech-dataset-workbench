# Session-aware train/val/test splitting

We fix how a build partitions its Samples into **train / validation / test** splits, and how that
partition is made reproducible, because the splitter is a `build` stage (#8) that feeds the manifest
(#12) and the on-disk layout (#9, ADR-0003). This ADR builds on ADR-0001 (identifiers), ADR-0002
(stateless `--data-in` → `--data-out`), and ADR-0003 (storage layout); it does not reopen them.

No model ever runs in this tool, so a bad split cannot be caught here or downstream — the split is a
promise ("these buckets are leakage-safe") that pays off only in a later, external training/eval
step. That makes correctness-at-the-source the governing constraint.

## Decisions

### Guarantee and grouping unit

- The atomic grouping unit is the **Session**: a whole Session is assigned to exactly one split and
  is **never torn across splits**.
- The disjointness guarantee is **session-level**, chosen because v0.1 data is expected to be
  **single-speaker**. A Speaker may therefore appear in every split — expected, not a defect.
  Speaker-level ("speaker-independent") splitting is **not** v0.1's guarantee.
- `group_by` is **fixed to Session** in v0.1 (not a config knob). Speaker-level grouping is a
  possible future option, deliberately not exposed now.

### Interface and defaults

- Ratios default to **80 / 10 / 10** (train / val / test), overridable via the `[split]` config
  section. The ratio targets **Sample count** (kept Recordings, 1:1 with Samples).
- Which Recordings participate: the splitter runs after normalize + validate (#8), on all
  Samples that survive to that stage — **soft-flagged Samples are included** (all attempts are
  data); a hard/malformed error aborts the whole build *before* splitting.
- `[split]` config (all keys optional; omitting the section uses the defaults):

  ```toml
  [split]
  seed  = 0      # integer; re-roll for a different reproducible draw
  train = 0.8
  val   = 0.1
  test  = 0.1
  ```

- **Ratio validation:** the three ratios must each be **> 0** and **sum to 1.0** (small tolerance).
  A violation (missing key, zero/negative, wrong sum) is a **structural config error → abort**
  (#8), not a soft flag. There is **no 2-way / `test = 0` mode** in v0.1.

### Assignment algorithm (deterministic)

> Steps 2 and 3 were **sharpened in place** (see *Amendment: closing the determinism gaps* below).
> As originally written, two faithful implementations could produce **different splits** on the same
> input, which would have made the byte-identical claim below — and ADR-0010's `dataset_version`,
> which rests on it — false.

Let `N` be the total Sample count over all Recordings that survive to this stage. `N` is known
**before** the walk begins: the splitter runs after normalize + validate on a fixed set, so no
Session is added or dropped mid-assignment. Define, for each split `i`:

```
target_i  = ratio_i × N            # absolute Sample count, a float; never rounded
deficit_i = target_i − assigned_i  # how many Samples split i still wants
```

`SPLIT_ORDER` is the fixed constant `("train", "val", "test")`.

1. Order Sessions by `sha256("<seed>:<session_id>")` (a stable hex sort key).
2. Walk that order, assigning each Session to the split with the **maximum `deficit_i`**
   (water-filling). **Ties between splits resolve by `SPLIT_ORDER`** — leftmost wins.
3. **Non-emptiness guarantee:** when there are **≥ 3 Sessions**, val and test each receive **at
   least one Session**. If water-filling starves either, repair them **in `SPLIT_ORDER`** (val, then
   test), **recomputing all state between moves**. For each starved split:
   - **Donor** = the split with the **minimum `deficit_i`** (the largest surplus) that holds
     **≥ 2 Sessions**; ties resolve by `SPLIT_ORDER`.
   - **Session** = the donor's Session with the **fewest Samples**; ties resolve by hash order
     (first wins).

   Ratios are best-effort; non-emptiness is the promise whenever the Session count makes it
   achievable — so the repair buys that promise at the **least ratio cost** available.
4. **< 3 Sessions** (a 3-way split is mathematically impossible): **produce-and-flag**. Assign what
   is possible, emit valid **empty** `val.jsonl` / `test.jsonl`, and raise an **unmissable warning**
   in the human summary and quality report. The build **never aborts** on split-emptiness.

Every input to every rule above — Sample counts, deficits, hash order, `SPLIT_ORDER` — is a pure
function of `--data-in` + the effective config. No RNG, no wall-clock, no host state.

#### Worked example (the committed example data, ADR-0009)

12 Samples / 4 Sessions × 3 Samples / default 80-10-10 → targets **9.6 / 1.2 / 1.2**. Sessions are
labelled by hash-order position `h1..h4`.

| step | deficits (train / val / test) | assign | train | val | test |
| ---- | ----------------------------- | ------ | ----- | --- | ---- |
| 1    | 9.6 / 1.2 / 1.2               | train  | 3     | 0   | 0    |
| 2    | 6.6 / 1.2 / 1.2 — tie → val   | val    | 3     | 3   | 0    |
| 3    | 6.6 / −1.8 / 1.2              | train  | 6     | 3   | 0    |
| 4    | 3.6 / −1.8 / 1.2              | train  | 9     | 3   | 0    |

`test` is empty and there are ≥ 3 Sessions → the repair fires for `test`. Deficits are now
`0.6 / −1.8 / 1.2`: **val** has the largest surplus but holds only **1 Session**, so it is
ineligible; **train** (3 Sessions) donates. All three of train's Sessions hold 3 Samples, so the
size tie falls to hash order → **h1** moves.

Final: **6 / 3 / 3** — the counts [#18](https://github.com/andrewferk/speech-dataset-workbench/issues/18)'s
`examples/` CI check asserts.

### Amendment: closing the determinism gaps

Resolves [#19](https://github.com/andrewferk/speech-dataset-workbench/issues/19), surfaced while
writing #18's acceptance criteria: the criteria wanted to assert the example's per-split counts, and
this ADR did not determine them. Three defects, fixed above:

- **The deficit was undefined at the first Session.** "Furthest below its target Sample-fraction"
  reads as a *fraction* (`ratio_i − assigned_i / assigned_total`), which is `0/0` when every split
  holds 0 of 0. Because `N` is known up front, the deficit is now an **absolute Sample count**
  against an absolute target, which is total-order-stable from the first Session onward and needs no
  special-case seed rule. Deficits go **negative** on overshoot — deliberately, so an overshot split
  stops attracting Sessions. Fraction-deficit and clamped ("remaining capacity") variants were
  rejected: the first needs a bolted-on rule just to place Session 1, the second multiplies ties once
  several splits clamp to zero.
- **"Ties resolve by the hash order" was incoherent.** Hash order is a total order over **Sessions**;
  the tie at step 2 is between **destination splits**, and the Session being placed is the same one
  either way. `SPLIT_ORDER` replaces it — total, stable, seed-independent, and readable off the
  config. (Hashing the split *name* was rejected: it makes tie-breaks seed-dependent and the table
  unreadable by hand, for no gain.)
- **"Moved into it from train" was a default-config assumption stated as a universal rule.** Ratios
  are operator-configurable and constrained only to be `> 0` and sum to `1.0`, so `train = 0.2`,
  `val = 0.4`, `test = 0.4` makes train the *smallest* split — and with 3 Sessions, "always train"
  can strip train to **empty** while repairing test, inverting the guarantee it exists to serve. The
  largest-surplus donor rule reduces to "train" under the default 80-10-10 (so the original intent
  survives) while staying correct under any legal config. The **≥ 2 Sessions** filter is load-bearing,
  not decoration: in the worked example the largest-surplus split (val) holds exactly one Session, and
  donating it would merely **relocate** the emptiness. Pigeonhole guarantees an eligible donor exists
  whenever there are ≥ 3 Sessions and a split is empty, so the repair can never fail to find one.

**Smallest-Session-wins** is this ADR's own logic applied to the repair: the repair is a deliberate
ratio violation in service of non-emptiness, so it should cost the least ratio fidelity available.
Taking the *first in hash order* was rejected — it is blind to size and can move a 9-Sample Session
where a 1-Sample one was available, damaging both splits to satisfy a guarantee one Sample would meet.
Taking the *largest* was rejected as the worst case for ratio fidelity, optimizing for a
"usable test-set size" goal this ADR never set.

### Reproducibility

- Same `--data-in` + same effective config → **byte-identical** split. The ordering key is `sha256`
  only, so there is no RNG-portability caveat (`random.shuffle` can drift across Python versions).
- `seed` supplies a different *reproducible* draw (re-roll if a split lands unluckily); it does not
  add reproducibility, only choosability.
- **No cross-version split stability.** Adding or removing a Recording may reshuffle which split
  existing Sessions land in. Acceptable because any `--data-in` change already produces a new
  `dataset_version` (ADR-0003) — old and new versions never shared a partition to begin with.

### Recording the split

- **No separate splits file.** The partition lives entirely in the per-split `train.jsonl` /
  `val.jsonl` / `test.jsonl`, the `split` field on each manifest line, and the `audio/<split>/…`
  buckets (#5, ADR-0003). The Session→split mapping is fully derivable from the lines
  (`session_id` + `split`).
- **`dataset.json`** records the effective `seed` + ratios (part of the `dataset_version` input per
  #8) and the **realized per-split counts** (Samples and Sessions per split); the human summary
  echoes these so actual split sizes are visible without counting file lines.

  > **Amended by ADR-0010.** `seed` + ratios moved into `dataset.json`'s `config` block (its single
  > home); the `split` block reduces to **realized counts only**. This ADR's substance is unchanged —
  > both facts are still recorded, in one place rather than two.

### Ratio disclosure (added by #19)

`summary.txt` prints the **configured target beside the realized count**, on every build, with no
threshold and no conditional:

```
split      target        realized
train       9.6 (80%)     6 (50%)
val         1.2 (10%)     3 (25%)
test        1.2 (10%)     3 (25%)
```

An operator who configures 80-10-10 and receives 50-25-25 is looking at **arithmetic, not a bug** —
whole Sessions are indivisible, and 80-10-10 is inexpressible across 4 equal Sessions. But nothing
previously *told* them the realized split missed the target by 30 points; this completes a comparison
the section above already half-made ("so actual split sizes are visible without counting file lines").

**Each repair move gets one report-only line**, in the same non-blocking register as the
speaker-overlap disclosure below:

```
non-emptiness repair: moved session sess_01 from train to test
  (≥3 Sessions → val & test must be non-empty; ratios are best-effort)
```

The realized counts alone show the repair's *outcome* but not its *mechanism* — an operator seeing
`test = 3` cannot tell whether water-filling chose it or the repair rescued it, and those mean
different things about their data. With the moves disclosed, water-fill arithmetic plus the move list
accounts for every Sample, and the split is fully explicable from `--data-out` alone.

Both are **deterministic text** (no timestamps, no host facts), so ADR-0008's exact golden-file
comparison on `summary.txt` still holds.

### Speaker-overlap disclosure

- When the dataset has **more than one distinct Speaker** and a Speaker lands in more than one
  split, emit a **report-only, non-blocking** note ("Speaker `spk_02` appears in train and test —
  test set is not speaker-independent") in the quality report / summary. It does not alter the split
  or the exit code. **Suppressed entirely for single-speaker data.**

## Considered and rejected

- **Speaker-level guarantee (speaker-independent splits)** — the ASR gold standard, but impossible
  on a single-speaker dataset (1 Speaker cannot fill 3 disjoint splits), which is exactly v0.1's
  expected shape. Session-level + the multi-speaker disclosure keeps the tool usable now while
  surfacing leakage honestly if speakers are ever added.
- **Splitting by Session count or by duration** — session-count gives unpredictable data volumes
  when Sessions vary in size; duration is the most rigorous but the most machinery and least
  intuitive. Sample-count matches what "how big is my test set" means, at trivial cost.
- **`random.shuffle(seed)` then slice** — familiar, but the shuffle can drift across Python versions
  (breaking byte-identical reproducibility) and a raw `session_id` sort would make "test" always the
  newest Sessions. The `sha256("<seed>:<session_id>")` key is portable and decorrelates from any
  ordering baked into the id.
- **Hash-bucketing for cross-version stability** (assign by `hash % 100 < ratio`) — keeps existing
  Sessions put when data changes, but can't target Sample-count ratios and buys a property we don't
  need (a changed `--data-in` is already a new version).
- **Abort when too few Sessions to fill 3 splits** — blocks building *any* dataset during the early
  bootstrapping phase (1–2 Sessions). Produce-and-flag keeps the tool usable from the first Session
  while making emptiness impossible to miss.
- **A dedicated splits file / session→split map artifact** — redundant; the per-split manifests +
  `split` field + audio buckets already encode the partition and it is derivable from the lines.
- **Exposing `group_by = "session" | "speaker"`** — broader than v0.1 needs (narrow > broad); the
  single-speaker reality fixes the choice to Session.
- **A configurable ratio-deviation warning threshold** (`[split].deviation_warn`, warn when realized
  misses target by more than X points) — rejected on **ADR-0010** grounds. The preimage hashes the
  **effective config with all defaults materialized**, and `summary.txt` is deliberately *excluded*
  from it — so a knob that only ever changes summary text would mint a **new `dataset_version` for
  byte-identical manifest bytes**. This is exactly the argument ADR-0011 used to reject an `[images]`
  section. Unconditional target-beside-realized needs no knob at all.
- **A fixed-constant deviation threshold** (warn only when off by > 10 points) — knob-free, so it
  dodges the `dataset_version` problem, but invents an arbitrary constant and a **cliff**: 9.9 points
  stays silent, 10.1 warns, and silence then means two different things ("close enough" vs. "not
  measured"). Showing both numbers always lets the operator draw their own line.
- **Staying silent and teaching the gap in `examples/README.md`** — rejected; it leaves every operator
  with few Sessions to re-derive the arithmetic themselves, and the README (#18/ADR-0009) reaches only
  readers of the *example*, not operators of their own data. A teaching note there remains welcome —
  it just isn't a substitute for the tool being legible.
- **A `split_repaired` quality flag** — rejected on **ADR-0007** grounds: the flag vocabulary is
  exactly three **audio-quality** flags (`clipping` / `low_volume` / `duration_out_of_range`), and a
  split-shape event is a category error there — the Sample's audio is fine. Same reasoning ADR-0011
  used to reject `render_failed`. The fact belongs in the summary, which is where split facts already
  live.
