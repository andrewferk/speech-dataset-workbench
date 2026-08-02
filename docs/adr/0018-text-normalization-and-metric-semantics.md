# Text Normalization & metric semantics (v0.2)

ADR-0016 fixed *which model, run how*; ADR-0017 fixed *the surface that runs it*. This ADR fixes
what the resulting numbers **mean**: which text is compared, after what shaping, by what arithmetic,
aggregated how, and what every degenerate case evaluates to. It resolves #132.

It owns the **entire deterministic half** of the map's split reproducibility contract. Everything
here must be computable with no model, no weights, no network and no torch, and must produce
byte-identical output on any machine — so everything here is specified tightly enough to be
golden-tested from a single fixture file.

It builds on ADR-0015 (evaluation vocabulary: Normalizer, Metric, Pooled, Macro-average, and error
rates never clamped), ADR-0016 (the model, and WER > 1.0 as the surfacing mechanism for a blown
transcript), ADR-0017 (Pooled headline over the Scope actually scored, per-Split Breakdown, failed
Samples excluded and disclosed N-of-M), ADR-0007 (`RATIO_DP = 4`) and ADR-0008 (exact goldens with
no tolerance). It consumes research #128. It **amends ADR-0017 in one place**: the predicted
`[scoring]` config section is withdrawn.

The Reference is the Prompt — v0.1's Intended text, filling ADR-0015's Reference *role*. This is the
map's named ceiling: every Metric below measures **recognition error plus speaker deviation**, not
recognition alone. That is not a caveat appended to the Report; it is a property of the measurement,
and two decisions here exist specifically because of it.

## Decisions

### Two Normalizers, both always computed, neither configurable

Every Scoring run produces every Metric under **two** Normalizers:

- **Tier A** (`sdw-tier-a/1`) — minimal: case and punctuation, nothing else. **The headline.**
- **Tier B** (`whisper-english/b80bcf6`) — OpenAI's `EnglishTextNormalizer`, vendored verbatim.

Research #128 sized this decision precisely, which is what makes it answerable. ESB
([arXiv:2210.13352](https://arxiv.org/abs/2210.13352) Table 4) is the only primary source that
ablates normalization layers on the *same* systems and *same* data: punctuation removal is worth
**−2.0 to −4.1** absolute WER points, case folding a further **−0.5 to −0.6**, and the **entire
remaining** Whisper normalizer — contractions, number standardization, British→American spellings,
filler removal — a further **−0.5 to −0.9**.

So the tier choice is worth **under one WER point** on published multi-domain data. On a 12-utterance
corpus, where #128's bootstrap puts the 95% CI at **6–11 points wide**, that is far under the noise
floor. A decision that small cannot be made well by argument; it can only be relitigated every time
someone reads the Report. **Computing both converts the argument into data.**

Three things make this cheap rather than indulgent:

- **The seam was built for it.** The map quarantined non-determinism behind the Hypothesis Record
  precisely so that re-scoring costs nothing. Two normalizations in one pass is two traversals of a
  few hundred short strings.
- **The delta is exact.** #128's central interpretability finding is that while our *absolute*
  number is sampling-limited, comparing two normalizations of the **same Hypotheses** is pure,
  paired, and carries no sampling error at all. The sub-1-point deltas above are therefore
  measurable on our own corpus even though they sit far beneath the CI — they simply cannot be
  compared against anyone else's published number.
- **The delta reads on the map's named ceiling.** A written Prompt can never contain *um*, *uh*,
  *hmm*; a real utterance can, and a model that transcribes one faithfully is charged an insertion.
  Filler removal is therefore the one aggressive rule that **directly attacks the prompt-as-Reference
  conflation**, and it is worth more here than its share of ESB's 0.5-point bucket implies, because
  ESB's references are real transcripts that already *contain* disfluencies. Tier B − Tier A on a
  *prompted* corpus is thus a partial readout of deviation against recognition — turning the map's
  ceiling from a paragraph of disclosure into a number that can be watched.

**Neither tier is selectable.** This is where the ticket's sharpest tension resolves — and it
resolves by dissolving rather than by picking a side. ADR-0004's rejection of a `deviation_warn`
knob and ADR-0011's anti-`[images]` argument both hold that a knob changing durable identity for no
change in substance is a trap. The map holds that free re-scoring under changed rules is the payoff
the whole Hypothesis Record seam was built to deliver. Both survive intact: **you do not need a knob
to see the number under different rules, because both rules always run.**

### Tier A — the exact rule list

Applied in order:

1. **NFKC** — compatibility fold (`ﬁ`→`fi`, full-width forms→ASCII, NBSP→space)
2. **`casefold()`**, not `lower()` — handles `ß`→`ss`, Turkish dotted/dotless I, Greek final sigma
3. **NFD, drop every `Mn` mark** — strips diacritics
4. **Delete apostrophes** — `'` `’` `ʼ` `′` `` ` `` `´`
5. **Every remaining character in Unicode category `M*`/`S*`/`P*` → space**
6. **Collapse all whitespace to single spaces; strip**

Measured against our own `examples/` prompts and #128's trap cases:

| input | Tier A |
| --- | --- |
| `Bright vixens jump; dozy fowl quack.` | `bright vixens jump dozy fowl quack` |
| `It's Dr. Smith's well-known co-worker.` | `its dr smiths well known co worker` |
| `Mother-in-law's O'Brien recipe.` | `mother in laws obrien recipe` |
| `café naïve résumé` / `cafe naive resume` | both → `cafe naive resume` |
| `hello\tworld\xa0again\nnow` | `hello world again now` |
| `Um.` | `um` |

Four properties are decisions rather than incidents:

**Apostrophes are deleted, not spaced.** Whisper spaces out all punctuation, but expands contractions
*first* (`can't`→`can not`). Tier A has no replacer table, so spacing would give `don't`→`don t`:
two tokens, inflating the reference word count — which *deflates* WER — and splitting one misheard
contraction into two errors. Deleting yields `dont`, `its`, `obrien`: one token, symmetric, with no
expansion ambiguity to get wrong. `dont` is not a word, but WER compares strings and both sides are
shaped identically.

**Hyphens *are* spaced, and the asymmetry with apostrophes is principled**: an apostrophe is
intra-word, a hyphen is a word-joiner an ASR normally renders as a space. `well-known` ≡ `well known`
is bought here for free, and it is the reason `merge_compounds` is unnecessary below.

**Accent stripping (step 3) is in the same class as case folding** — an orthographic equivalence, not
a semantic one — so it sits below the laundering line. Whisper does the same thing.

**Tier A cannot empty a non-empty Prompt.** `Um.` → `um`, where Whisper's normalizer yields `""`.
Empty normalized References are therefore an almost-exclusively Tier B condition, which matters to
the edge-case rules below.

Step 6 is a **contract obligation, not hygiene**. #128 measured that `jiwer`'s default tokenizer
splits on the literal space only, so a single surviving tab produces `wer("hello\tworld",
"hello world") == 2.0` — a silent 200% error. The Normalizer guarantees single-space separation; no
downstream scorer is trusted to repair ragged whitespace.

### Tier B — OpenAI's normalizer, vendored verbatim at a pinned sha

**Depending on a package is structurally impossible**, which narrows this before preference enters.
`openai-whisper` requires torch. `transformers` ships its own copy, but lives behind the opt-in eval
extra, and ADR-0017 forbids the Scoring path importing anything from the ASR stack — a boundary #137
is making an executable check. So the choice is **vendor or write**, and the split contract made it.

We vendor `whisper/normalizers/english.py` and `basic.py` at commit **`b80bcf6`**, with
`english.json`, **unmodified**.

- **It is ADR-0016's move again.** That ADR rejected SYSTRAN's CTranslate2 conversions — smaller and
  faster — in favour of OpenAI's published artifact, on the grounds that for a destination demanding
  *honest* comparison, "an unattested link mid-chain is the wrong economy." A community fork of a
  normalizer is the same unattested link.
- **It is the only Tier B with external meaning.** ESB's `− full normalisation` row *is* this
  function. Tier B therefore answers a question the literature has already asked; a fork or a
  homegrown tier answers a question only we have asked.
- **Pinning the sha is the fix for a named ambiguity.** #128 found that `openai/whisper`,
  `transformers` and `open_asr_leaderboard` ship **three different functions** under the class name
  `EnglishTextNormalizer`, so "the Whisper normalizer" without a revision is meaningless. Recording
  the sha in the Report is what ADR-0016 did for model weights.

**Costs accepted on the record.** Two new *base* dependencies — `regex` and `more_itertools` — plus
56 KB of `english.json` and ~630 vendored lines, for a tier that is explicitly not the headline. The
vendored tree is excluded from `mypy --strict` and ruff, and carries MIT attribution. And Tier B's
verified corruptions land with it: `O'Brien → 0 brien`, `The dog's bone → the dog is bone`,
`the rep → the representative`. These are tolerable **only because Tier A is the headline** — they
can move the diagnostic, never the number.

**One honesty note about the delta.** Tier B is not "Tier A plus the aggressive rules"; it is an
independently written function that happens to overlap, using `.lower()` where Tier A uses
`casefold()` and skipping NFKC. The B−A delta is therefore *mostly* the aggressive rules, carrying a
little noise from those divergences. The Report names it a **delta**, never "deviation".

### Tier A is the headline

The Report's single headline number is **Tier A Pooled WER**. Tier B sits beneath it, labelled.

- **We own Tier A completely.** Six steps of Unicode work against someone else's forty-plus regexes
  and a 56 KB spelling map. The headline number of this project should not depend on a bug list we
  did not write, and #128 found real ones.
- **Tier B's corruptions are asymmetric on a prompted corpus specifically.** #128 notes they mostly
  cancel because both sides are mangled identically, but "stop cancelling when only one side contains
  the trigger — which for a prompted corpus is common, because the prompt is written English and the
  hypothesis is what a model heard." Our References are authored Prompts: precisely the text most
  likely to carry possessives, proper names and title abbreviations. We are near the worst case.
- **Tier B launders what the map instructed us to disclose.** #128's converse finding: aggressive
  normalization *hides* speaker deviation — filler removal makes a disfluent read look identical to
  a fluent one. This repo has now refused that shape three times for the same reason. ADR-0016
  rejected a repetition penalty because it "changes the model's output to flatter the Metric";
  ADR-0017 rejected silent exclusion of failed Samples because it would "flatter the Metric by
  discarding exactly the data this product exists for"; and the map ruled out ASR-as-dataset-QA on
  silent inversion. A headline that quietly deletes disfluency is the same move. It belongs in the
  Report — beneath the number, not as it.
- **The comparability argument for Tier B is already dead.** Its only real case is matching
  leaderboard practice, but a 12-utterance single-speaker prompted corpus is comparable to no
  published WER at any tier, and the leaderboard's own fork sets `merge_compounds=True`, which #128
  found "breaks comparability with every historical published number." The comparison this project
  actually needs is against **our own future fine-tune** — internal, paired, exact.

The cost: a reader fluent in ASR will see a headline higher than a leaderboard-style number and may
read the model as worse than it is. Tier B directly beneath it, labelled, is what pays that off.

### Text Normalization is symmetric

The **identical function** is applied to Reference and Hypothesis, with no exceptions.

#128 records this as a place where credible traditions genuinely diverge: NIST's `en20030506.glm`
carries a literal section header reading *"All mappings below will be applied to the system output
only and not to the reference"*, while Whisper/HF apply one function to both sides.

NIST's asymmetry is load-bearing **only because it is paired with machinery we cannot replicate** —
zero-cost alternates (`[HE'S] => [{HE IS / HE HAS}]`, aligned as word networks) and optional deletion,
by which a reference word is neither rewarded nor penalised. Asymmetry without alternates is the cost
without the benefit: picking one expansion by fiat, which is exactly what produces `dog's → dog is`.

And the asymmetry we would actually want **emerges for free from the corpus shape**. The one rule
where hypothesis-only application is obviously right is filler removal. But Tier A does not remove
fillers at all, so a spoken *um* is correctly charged as an insertion and surfaces as deviation; and
Tier B removes them from both sides, where the Reference — a written Prompt — has none. **Symmetric
Tier B on a prompted corpus already *is* hypothesis-only filler removal.** We get the behaviour
without the rule.

Symmetry also keeps the Normalizer a function of *text* rather than of *role*, which collapses the
golden test to one function over one fixture and is what makes the corruptions above cancel.

If `perceived_text` is ever collected, that is a different Reference and deserves a fresh decision —
not a hook inherited from here.

### The scorer is ours: ~40 lines of Levenshtein with backtrace

Scoring implements its own edit-distance alignment, pure Python, **zero new dependencies**, with
costs **0/1/1/1** (correct/insertion/deletion/substitution).

This is not preference. `jiwer` and `kaldialign` are both viable on our `>=3.13` floor and both were
seriously considered:

- **We override every library's edge-case behaviour anyway.** #128 is unambiguous — for an empty
  reference `jiwer` returns the raw insertion **count** (3.0, not a rate), `kaldialign` returns
  `inf`, `torchmetrics` `nan`, HF `evaluate` raises. Its conclusion is that no library default is
  adoptable as-is. Under any of them we would compute a number and then rewrite it at the edges. The
  library saves us the DP, not the decisions.
- **We need per-Sample S/D/I and reference lengths regardless**, and a backtrace yields them
  directly. #128 argues these should be emitted whatever else is decided, because they are what makes
  any later analysis possible and they cost nothing.
- **"Byte-identical across machines" is a contract, not an aspiration.** Both survivors ship compiled
  extensions (`kaldialign` is one; `jiwer` computes through `rapidfuzz`). The risk is small — integer
  counts, no floats — but a pure-Python integer DP makes the contract *trivially* true rather than
  true-pending-audit. ADR-0012's instinct: prefer the version that cannot be wrong over the version
  that is tested not to be.
- **#128 caught `jiwer` documenting behaviour it does not have** — `process_words`' docstring claims
  it raises `ValueError` on empty references; the code does not, and the research states plainly
  "the docstring is wrong." Auditing forty lines we wrote beats auditing a dependency whose
  documentation is already known false.

Edit costs are **0/1/1/1**, not `sclite`'s 0/3/3/4. Every Python implementation uses the former;
total error counts usually agree either way, and the weights change only the tie-break between one
substitution and an insertion+deletion pair. Since the S/D/I split is reported, that tie-break is
visible, and matching modern convention beats matching a toolkit we use only as a one-time oracle.

**The backtrace tie-break is fixed here, because equal costs make the S/D/I split ambiguous.** The
total — and therefore WER, CER and SER — is unaffected by which minimal path is walked, but the
*split* is not, and this ADR emits S, D and I as the source of truth. With `ref = "a b"` and
`hyp = "b a"`, two substitutions and one deletion plus one insertion both cost 2; without a stated
rule, two conforming implementations report different S/D/I for the same inputs and the golden test
pins an accident.

The matrix is indexed **Reference along `i`, Hypothesis along `j`**, so a diagonal step is a match or
substitution, a step in `i` alone is a **deletion**, and a step in `j` alone is an **insertion**.
Backtrace starts at `(len(ref), len(hyp))` and, among steps achieving the cell's minimum cost, takes
the **first** of:

1. **diagonal** — match or substitution
2. **deletion**
3. **insertion**

Diagonal first keeps one substitution in preference to an insertion+deletion pair wherever both are
minimal, which is the reading of an aligned pair a human expects. Deletion before insertion is
arbitrary in isolation, but it must be *written down* to be reproducible, and this ordering matches
the conventional `sclite` presentation of the pair. The rule is a **contract obligation**, not an
implementation note: it is what makes ADR-0008's no-tolerance goldens well-defined over the emitted
counts.

**`merge_compounds` is off and not implemented.** It exists as an option only under `kaldialign`. It
would be off regardless: it lowers WER and, per #128, "breaks comparability with every historical
published WER"; Tier A already spaces hyphens, so `well-known` ≡ `well known` is handled
symmetrically without it; and a scorer-side forgiveness rule that improves the number belongs to the
same family as the repetition penalty ADR-0016 rejected.

### Three Metrics, under both tiers, on the same normalized text

**WER, CER and SER**, each computed under Tier A and Tier B, from the same normalized text.

This ratifies rather than reopens: ADR-0015's glossary already defines **Metric** as *"word error
rate (WER), character error rate (CER), sentence error rate (SER)"*. Dropping SER now would mean
amending a settled ADR to remove a term from the ubiquitous language. It is also right on the merits
— SER is a per-Sample binary, so unlike WER it does not vary with utterance length, making it **far
more stable at N=12**. It is NIST's `S.Err`, thirty years old, and free from counts we already hold.

- **WER** = (S + D + I) / N over whitespace-separated tokens, N = Reference token count.
- **CER** = the same arithmetic over characters, **aligned per Sample and then Pooled — never
  concatenated**. #128 measured the difference: `refs = ["ab","cd"]`, `hyps = ["a","bcd"]` gives
  **0.5** per-Sample-Pooled and **0.0** concatenated — same inputs, same library, two answers, with
  HF `evaluate` switching between them silently depending on installed `jiwer` version. Concatenation
  aligns characters *across Sample boundaries*, which is meaningless when Samples are independent
  Recordings, and it sits badly with ADR-0017's pair-by-identifier rule.
- **The space character counts as a character** in CER. It is `jiwer`'s documented default and the
  nearest thing to a convention; our Normalizer *guarantees* exactly-single-space separation, so a
  space is a well-defined token rather than an artifact of ragged input; and excluding it would make
  CER blind to word-boundary errors — compound and hyphenation splits, a real error class on a
  prompted corpus.
- **SER** — a Sample is an error iff its normalized Reference and Hypothesis differ exactly; Pooled
  as errors / pairs.

No external authority defines English CER — #128 found Whisper's paper does not define one and the
Open ASR Leaderboard reports none. These semantics are therefore ours by default, and are fixed here
rather than left to an implementation.

### Edge cases — every degenerate input has a value, and none of them is an exception

**An empty normalized Reference is retained, never dropped.** The Open ASR Leaderboard drops such
Samples. Two reasons that is wrong here, the second decisive:

- Dropping is silent exclusion, which ADR-0017 rejected in the failure case because it would
  "flatter the Metric by discarding exactly the data this product exists for."
- **Dropping would break the two-tier design.** Empty References arise almost exclusively under Tier
  B (`Um.` → `""`; Tier A gives `um`). Dropping would therefore make Tier A and Tier B score
  **different Sample sets** — and the A/B delta would stop being paired, destroying the exactness
  that is the *entire* justification for computing two tiers. Retain-don't-drop is not a minor edge
  rule; it is load-bearing on the first decision in this ADR.

Retaining costs nothing arithmetically, because **Pooling already absorbs it**: Pooled WER sums errors
and sums Reference lengths and divides **once**, so an empty-Reference Sample contributes its
insertions to the numerator and zero to the denominator. No division by zero ever occurs. Only the
*per-Sample* rate is undefined.

| case | per-Sample rate | Pooled contribution |
| --- | --- | --- |
| Reference `""`, Hypothesis *k* tokens | **`null`** | *k* insertions / 0 |
| Reference `""`, Hypothesis `""` | **`null`** | 0 / 0; **SER: correct** |
| Reference *N* tokens, Hypothesis `""` | `1.0` | *N* deletions / *N* |
| WER > 1.0 | the real value | as computed |
| Scope with zero total Reference tokens | — | **error; refuse to emit** |

- **`null`, explicitly, for undefined per-Sample rates** — not a sentinel number. `jiwer` returning a
  raw insertion count from a function documented to return a rate is precisely what #128 warns
  "silently poisons a mean". A `null` propagates as an absence; a `0.0` or an `inf` propagates as a
  lie. Note that a per-Sample `null` does **not** feed a Macro-average: Aggregation below establishes
  that Macro averages *group Pooled rates*, and Pooling absorbs an empty Reference before any mean is
  taken. The `null` is emitted for the Sample's own row, and its protection is against a consumer —
  ours or a later one — that means to average Samples directly.
- **A Scope with zero total Reference tokens is an error, not a number.** `0.0` claims perfection and
  `inf` claims catastrophe; neither is a measurement.
- **WER > 1.0 is never clamped** — ratifying ADR-0015. #128 cites a real published **287.4%**, and
  ADR-0016 already designated an unclamped WER as the surfacing mechanism for a blown transcript.
- **No distinct "runaway decode" condition.** A flag needs a threshold, and a threshold is a knob
  that changes what the Report says for no change in substance — the trap ADR-0004 and ADR-0011 both
  named. The per-Sample Metrics make a runaway locatable without one.

This sits alongside ADR-0017's already-settled failure rule, which is unchanged: a **crashed** decode
is excluded from Scoring and disclosed N-of-M, and is recorded distinctly from an empty Hypothesis —
an empty string is the model's output; a crash is not.

### Aggregation and precision

**Pooled at every level.** The Scope headline is Pooled and nothing else. Each Breakdown group — per
Split, Session, Prompt, Device, Environment — is Pooled.

**Macro-average, standard deviation and median are computed *across* the groups of a Breakdown**, and
only there. ADR-0015's glossary already fixes the placement: Macro-average is *"legitimate for a
Breakdown, where groups differ in size on purpose; never presented unlabelled as 'the WER'."* This
is NIST's `Sum/Avg` / `Mean` / `S.D.` / `Median` shape, which `sclite` has printed since the 1990s
and which #128 measured **6.2 points apart** on four speakers in NIST's own shipped example. All are
free from counts already held, and the map's charting note applies: *whichever loses should still be
reported if it is cheap, because the two diverge and a reader will assume the one you did not
compute.*

**What Macro averages over is the group's Pooled rate — not the per-Sample rates inside it.** This
**names a unit ADR-0015 deliberately left generic**: that ADR defines Macro-average as averaging
*"per-unit rates"* and says in the same breath that the headline choice *"is a scoring-spec
decision"* — this is that spec, so fixing the unit is its job rather than a departure. `CONTEXT.md`'s
glossary entry had compressed "per-unit" to "per-Sample", which is narrower than ADR-0015 and wrong
once the unit is named; it is annotated in place rather than silently left to disagree. A
Breakdown group is Pooled first, and Macro is the unweighted mean of those group rates; so the
`null` that can reach a Macro-average is a **group** whose rate is undefined — which is a *narrower*
condition than the per-Sample `null` of the edge-case table above. A group containing an
empty-Reference Sample alongside any non-empty one has a perfectly well-defined Pooled rate, and its
per-Sample `null` never surfaces here.

**Undefined-ness is per Metric, because the three denominators differ.** A group's Pooled rate is
undefined exactly when that Metric's own denominator is zero:

| Metric | denominator | group rate undefined when |
| --- | --- | --- |
| WER | Reference **tokens** in the group | every Reference in the group normalizes empty |
| CER | Reference **characters** in the group | every Reference in the group normalizes empty |
| SER | **pairs** in the group | the group holds no Samples at all |

So a group whose every Reference is empty still has a well-defined Pooled **SER** — consistent with
the edge-case table above, which makes empty-vs-empty a *correct* Sample. Such a group reports a
`null` WER and CER and a real SER, and is excluded from the WER and CER Macros while counting in the
SER Macro. A group that is genuinely empty of Samples is not emitted at all.

The rule, stated over the right objects:

- **Macro, SD and median exclude groups whose Pooled rate is undefined *for that Metric*, and state
  how many they excluded.** The exclusion is therefore per Metric — the same group can be absent from
  the WER Macro and present in the SER Macro. With every group excluded, the Macro is `null` — not
  `0.0`.
- **A zero-Reference-length *group* is not the error condition** that the edge-case table gives a
  zero-Reference-length Scope. Refusing to emit is right for the headline, where the alternative is a
  Report whose single number is a fiction; inside a Breakdown it would let one degenerate group
  suppress an otherwise valid Report. The group is emitted with its integer counts, `null` for WER
  and CER, its real SER, and its exclusions from the Macros disclosed.
- Per-Sample `null` rates are still emitted per Sample, and are still excluded — with a count —
  from any statistic computed *across Samples* rather than across groups.

**The Tier B − Tier A delta is emitted as a first-class number**, plainly named as a delta.

**Precision inherits v0.1 rather than inventing.** WER, CER and SER are ratios, and ADR-0007 already
fixed that ratios take `RATIO_DP = 4`. No new constant.

- **Integer counts are the source of truth and are emitted exactly.** Every rate this ADR defines is
  recomputable from integers alone, which means **word-level and character-level counts are emitted
  separately** — CER is its own alignment (per Sample, never concatenated), so it has its own error
  counts and they are not derivable from the word-level ones:
  - **word-level** — S, D, I and Reference token count
  - **character-level** — S, D, I and Reference character count
  - **sentence-level** — sentence-error count and Sample count

  Rates are *derived*. This is what lets any later analysis — a confidence interval, a
  re-aggregation, a Breakdown nobody has asked for yet — be computed without re-scoring. Each set is
  emitted under **both** Normalizer tiers, since each tier aligns its own text.
- **Round at serialization, never at measurement**, quoting v0.1's own rule, which exists so "two
  runs within a ULP serialize identically" and ADR-0008's comparison "needs no tolerance."
- **The canonical form is a dimensionless rate**, `0.0833`, not `8.33%`. Percentage rendering is the
  human digest's business.
- **Key order is fixed by declaration order and guarded by a test**, as v0.1 already does, because
  reordering fields is an output change nothing else catches.

At 4 dp a single token error becomes invisible in the *rate* once a Scope exceeds ~10,000 Reference
tokens. Our corpus is order 100–1,000 tokens, so this is nowhere near biting, and the integer counts
remain exact regardless — but it is the thing to revisit if the corpus grows two orders of magnitude.

### `[scoring]` is empty, so it does not exist — amending ADR-0017

ADR-0017 wrote that `score` would inherit #8's defaults-plus-`--config` pattern *"with one new
section, **`[scoring]`**, owned by #132 (Normalizer tier, `merge_compounds`, which Metrics, CER
whitespace semantics, SER, whether a CI is reported)."*

Every item in that list is now a constant: both tiers always run; `merge_compounds` is off and
unimplemented; all three Metrics always; CER whitespace fixed; SER always; the CI question belongs to
#136 and is not configuration. **The section is empty, and an empty config section invites a knob** —
ADR-0017's own reason for refusing `transcribe` a `--config`.

So **`score` takes no `--config` flag**, and the property becomes symmetric and stateable in one
line: *neither evaluation command has any configuration; every input to an Evaluation is a constant
this repo owns or a field of the dataset it read.*

**This does not pre-empt #135.** If evaluation output layout or Run retention needs operator
configuration, `score` grows a `--config` back carrying a *different* section; `[scoring]` simply
stays absent. #135 therefore inherits the question of whether `score` has a config file at all.

### Normalizer identity reaches the Report — and is a required input to Run identity

ADR-0015 defines a Normalizer as *"a named, versioned rule-set"*, named *"because there is no single
canonical one… so an Evaluation Report must state which one it used"*. Both are named using
ADR-0010's existing separator convention:

- **`sdw-tier-a/1`** — bumping the `1` is the deliberate act declaring that new numbers are not
  comparable with old ones.
- **`whisper-english/b80bcf6`** — the vendored commit.

**Both strings are required inputs to a Run's identity, not merely to its provenance display.** #132 states the reason and this ADR adopts it unchanged: the rules are *part of the
Metric's definition*, so *"the same hypotheses scored under different rules are different numbers and
must not be silently comparable."* Everything above makes that concrete — Tier A and Tier B produce
six different numbers from one Hypothesis Record, and the whole point of the split contract is that
re-scoring is cheap and therefore frequent. An identity that omitted the Normalizer would let two
Runs over the same Hypotheses collide while disagreeing about every Metric, which is precisely the
silent comparability the ticket forbids.

So #134 inherits a **constraint rather than a question**, in both directions:

- **The scoring configuration contributes nothing** to Run identity, because there is no scoring
  configuration.
- **`sdw-tier-a/1` and `whisper-english/b80bcf6` must contribute**, and bumping either must change
  the Run's identity. What #134 still owns is the *form* — whether identity is a hash over a
  canonical preimage in ADR-0010's style, what else joins them in it, and how it is rendered — not
  *whether* these two strings are in it.

These are the only two strings this ADR sends; a Normalizer's rules are otherwise fixed here as
constants, so the version tag is the whole of its identity.

## Consequences

- The Scoring path's dependency closure is `regex` + `more_itertools` and nothing else — no torch, no
  network, no scientific stack. `sdw score` in a venv without the eval extra remains ADR-0017's
  executable demonstration of the boundary.
- The golden fixture must cover, at minimum: tab / newline / NBSP inputs (the 200% trap), an empty
  normalized Reference under Tier B, an empty Hypothesis, a WER > 1.0 case, a Scope of one Sample,
  a case with two equal-cost alignments so the backtrace tie-break is pinned rather than assumed,
  and both tiers over the same fixture so the delta is pinned too.
- Six numbers exist per Scope (three Metrics × two tiers), before Breakdowns. Exactly one is the
  headline; everything else is explicitly subordinate. Presenting that legibly is #136's problem, and
  it is a real one.
- The map's named ceiling acquires a measurement. It remains a disclosure obligation, not a solved
  problem.
- #138 inherits: validate the golden fixtures **once** against `sclite` and `jiwer` as dev-only
  oracles, then freeze. Our own scorer is the long-term source of truth; the oracles exist to catch a
  first-implementation error, not to be a standing dependency.
- #136 inherits a computable-but-undecided confidence interval — the per-Sample counts make a
  bootstrap possible with no re-scoring — plus the six-number presentation problem and the labelling
  rule that Macro-average is never "the WER".

## Rejected alternatives

**One Normalizer, chosen by fiat** — the cleanest identity story, and the shape ADR-0004 and
ADR-0011 would predict. Rejected because the choice is worth under one WER point on published data
and cannot be made well by argument at that size; picking one guarantees the argument recurs at every
reading of the Report, and the seam that makes both free was already built.

**A configurable Normalizer tier in `[scoring]`** — the shape ADR-0017 predicted. Rejected because it
puts a knob on durable identity for no change in substance, which is the trap ADR-0004 named, *and*
because it is unnecessary: computing both delivers the map's re-scoring payoff without one.

**Tier B as the headline** — matches leaderboard practice and yields the lower, more flattering
number. Rejected because it launders speaker deviation, which is the one thing the map instructed the
Report to disclose; because its verified corruptions are asymmetric precisely on authored-prompt
References; and because the comparability it buys is already unavailable at our corpus size.

**The Open ASR Leaderboard's normalizer fork** — genuinely *better* than OpenAI's: the possessive bug
is fixed (`dog's` survives) and the filler list is 19 words rather than 6, which is the part most
valuable for the deviation probe. Rejected because it lives on `main` with no release tags, and
because its improvements arrive bundled with `merge_compounds` and the acronym/name normalizers —
changes to the *scorer*, not merely to the text. Adopting a scoring philosophy to obtain a filler
list is the wrong trade.

**Writing our own Tier B (~40 lines)** — cheaper, no vendored tree, no new dependencies. Rejected
because the cheap parts (fillers, contractions) are the parts worth least, while the valuable part is
number standardization — `twenty five` ≡ `25`, `one hundred dollars` ≡ `$100`, `first` ≡ `1st`, which
#128 measured Whisper handling correctly in both directions — and that is ~400 of its 550 lines,
covering fractions, ordinals and currency. Forty lines buys the least valuable half and leaves our
aggressive tier comparable to nothing.

**`jiwer` or `kaldialign` as the scorer** — well-tested, widely used, and `kaldialign` would have made
a bootstrap CI a one-liner and given `sclite_mode` for free. Rejected on the four arguments above,
of which the first is decisive: every edge case that matters is one we override anyway, so the
library supplies the DP and none of the decisions, while adding a compiled extension to a path whose
contract is byte-identical output.

**Dropping empty-Reference Samples**, following leaderboard practice — the simplest rule, and it
eliminates the `null` rate entirely. Rejected because it would make the two tiers score different
Sample sets and destroy the paired exactness that justifies computing two tiers at all.

**Returning `0.0` or `inf` for an undefined per-Sample rate** instead of `null` — keeps every field
numeric and every consumer simpler. Rejected because both are lies that survive aggregation, which is
exactly the failure #128 identified in `jiwer`'s insertion-count return.

**Clamping WER at 1.0** — makes the number look like the proportion readers assume it is. Rejected by
ADR-0015 already; restated here because a runaway decode on quiet or atypical audio is our likeliest
path past 1.0, and clamping would hide precisely the failure the Report exists to surface.

**Macro-average as the headline** — weights every Sample equally, which sounds fairer. Rejected on
#128's measurement: with `refs = ["the cat sat on the mat and then it slept quietly", "go"]`, Pooled
gives 0.083 and Macro gives 0.5. For a Prompt list of wildly varying length, Macro-average is a
length-weighting decision disguised as an averaging decision.

**A distinct runaway-decode flag** — would name the failure explicitly rather than leaving it implicit
in a large WER. Rejected because it requires a threshold, and a threshold is a knob that changes what
the Report says without changing what happened.
