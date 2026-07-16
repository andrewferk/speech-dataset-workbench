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

1. Order Sessions by `sha256("<seed>:<session_id>")` (a stable hex sort key).
2. Walk that order, assigning each Session to the split currently **furthest below its target
   Sample-fraction** (water-filling). Ties resolve by the hash order.
3. **Non-emptiness guarantee:** when there are **≥ 3 Sessions**, val and test each receive **at
   least one Session** — if water-filling starves either, one Session is moved into it from train.
   Ratios are best-effort; non-emptiness is the promise whenever the Session count makes it
   achievable.
4. **< 3 Sessions** (a 3-way split is mathematically impossible): **produce-and-flag**. Assign what
   is possible, emit valid **empty** `val.jsonl` / `test.jsonl`, and raise an **unmissable warning**
   in the human summary and quality report. The build **never aborts** on split-emptiness.

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
  `val.jsonl` / `test.jsonl`, the `split` field on each manifest row, and the `audio/<split>/…`
  buckets (#5, ADR-0003). The Session→split mapping is fully derivable from the rows
  (`session_id` + `split`).
- **`dataset.json`** records the effective `seed` + ratios (part of the `dataset_version` input per
  #8) and the **realized per-split counts** (Samples and Sessions per split); the human summary
  echoes these so actual split sizes are visible without counting file lines.

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
  `split` field + audio buckets already encode the partition and it is derivable from the rows.
- **Exposing `group_by = "session" | "speaker"`** — broader than v0.1 needs (narrow > broad); the
  single-speaker reality fixes the choice to Session.
