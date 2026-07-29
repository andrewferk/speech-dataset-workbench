# ASR evaluation conventions — normalization, WER/CER, aggregation

Research for [#128](https://github.com/andrewferk/speech-dataset-workbench/issues/128), feeding the metric-semantics
decision ([#132](https://github.com/andrewferk/speech-dataset-workbench/issues/132)) and the report spec
([#136](https://github.com/andrewferk/speech-dataset-workbench/issues/136)). Sources are papers, official
benchmark rules, and library source read at the URLs cited. Where a claim comes from running code rather than
reading a document it is marked **[measured]**; where a source could not be verified it says so.

Everything here is input to a decision. Nothing here *is* the decision — see the last section.

---

## 1. The number that sizes the decision

**Case + punctuation is worth ~2.5–4.7 absolute WER points. Everything else in the elaborate
Whisper-style normalizer is worth ~0.5–0.9 more.**

ESB (Gandhi, von Platen & Rush, 2022) is the only primary source found that ablates the layers
of normalization on the *same* systems and *same* data. Table 4 of
[arXiv:2210.13352](https://arxiv.org/abs/2210.13352) reports the macro-averaged benchmark score at four
successively more aggressive scoring conditions:

| Score (WER %)      | w2v2 CTC | CTC + n-gram | w2v2 AED | Whisper AED | Conformer RNN-T |
| ------------------ | -------- | ------------ | -------- | ----------- | --------------- |
| Orthographic (ESB) | 17.8     | 17.1         | 13.7     | 10.6        | 11.0            |
| − punctuation      | 14.8     | 13.0         | 11.4     | 8.6         | 8.7             |
| − casing           | 14.3     | 12.4         | 10.8     | 8.0         | 8.1             |
| − full normalisation | 13.7   | 11.6         | 10.3     | 7.4         | 7.2             |

Deltas: punctuation removal **−2.0 to −4.1**; case folding a further **−0.5 to −0.6**; the entire remaining
Whisper normalizer (contractions, number standardization, British→American spellings, filler removal) a further
**−0.5 to −0.9**. The paper's own summary: *"Removing punctuation yields a reduction of 2.0% or more for all
systems… Casing further reduces the score by 0.5-0.6%… We observe another 0.5% drop with full normalisation."*
"Full normalisation" there is explicitly *"the full English text normaliser from Radford et al. (2022)"* — i.e.
Whisper's `EnglishTextNormalizer`.

Two corroborating figures, both weaker evidence for our case:

- Whisper's own paper ([arXiv:2212.04356](https://arxiv.org/abs/2212.04356), §3.2) claims *"For several datasets,
  we observe WER drops of up to 50 percent usually due to a quirk such as a dataset's reference transcripts
  seperating contractions from words with whitespace."* This is **relative**, not absolute points, and it is
  attributed to *dataset quirks* — it is a statement about pathological reference formats, not about English
  normalization in general. It should not be read as "normalization is worth 50 WER points".
- Manohar, Pillai & Sherly, *What is lost in Normalization?* ([arXiv:2409.02449](https://arxiv.org/abs/2409.02449),
  §3.2) measure whisper-small on FLEURS with and without Whisper normalization: **English absolute reduction 5.1
  points** (baseline) and **4.5 points** (whisper-small.en); Finnish 3.2. Larger than ESB's ~3.2 total because
  FLEURS references are punctuated and cased and the model emits punctuation — the same regime we are in. Their
  headline finding is about Indic scripts (Malayalam: 152.2 points, because the normalizer strips vowel signs and
  shatters words), which does not apply to us but is the strongest published warning that a normalizer can
  *manufacture* a good score.

**So:** the punctuation/case decision is worth ~3–5 points and must be made. The choice between "strip
punctuation and lowercase" and "run the full Whisper normalizer" is worth **under one WER point** on published
multi-domain data — which is smaller than the sampling noise of a 12–100 utterance corpus (§7). That is the
ceremony budget for [#132](https://github.com/andrewferk/speech-dataset-workbench/issues/132).

The escape hatch: because the map splits transcription from scoring at a durable hypothesis artifact, re-scoring
under a second normalization is free. Reporting *both* numbers converts this decision into a measurement.

---

## 2. Text normalization: three traditions, and they are not variants of each other

### 2.1 NIST / `sclite` / GLM (1996–2000s)

The scoring pipeline is `hubscr.pl` → `csrfilt.sh -dh <glm>` → `sclite`
([hubscr.pl](https://github.com/usnistgov/SCTK/blob/master/src/hubscr/hubscr.pl), lines ~553–587). The GLM
("Global Mapping File") is a **data file, not code**: a hand-maintained list of string-rewrite rules
`A => B / C __ D`, applied by a left-to-right cursor scan, first-rule-wins
([GLMRules.txt](https://github.com/usnistgov/SCTK/blob/master/doc/GLMRules.txt)). The shipped Hub-5 English GLM
[`en20030506.glm`](https://github.com/usnistgov/SCTK/blob/master/doc/trans_rules/en20030506.glm) is **1818 lines**
and contains, in labelled sections: backchannel mappings (`UH-UH => %BCNACK`), hesitation mappings
(`UM => %HESITATION`), one-to-two-word compound expansions (`AIRCRAFT => AIR CRAFT`), spelling normalizations
(`CANCELLED => CANCELED ;; per AHD`), and contraction expansions.

Three properties of this tradition have no counterpart in the modern one, and they matter:

1. **Alternates.** The scorer accepts a *set* of correct answers at zero cost. The GLM writes
   `[HE'S] => [{HE IS / HE HAS}]`; `sclite`'s DP aligns two word *networks* rather than two strings
   ([sclite.htm](https://github.com/usnistgov/SCTK/blob/master/doc/sclite.htm)). Whisper's normalizer cannot
   express ambiguity — it must pick one expansion, which is the direct cause of the `dog's → dog is` corruption
   in §2.2.
2. **Optional deletion.** A reference word can be marked `(word)` or aliased to the NULL token `@`, so the system
   is *neither* rewarded nor penalized for it. `sclite -D` scores an optional word as correct if deleted. There is
   no modern equivalent; the closest is deleting filler words from both sides unconditionally.
3. **Asymmetry.** `en20030506.glm` has an explicit section header — *"All mappings below will be applied to the
   system output only and not to the reference"* — above the contraction expansions. Reference and hypothesis are
   deliberately **not** put through the same function.

Also from `sclite`: the DP alignment minimizes a **weighted** Levenshtein distance with costs 0/3/3/4 for
correct/insertion/deletion/substitution, not 0/1/1/1. This changes *tie-breaking* between an S and an I+D pair,
so the reported S/I/D breakdown can differ from an unweighted scorer even when total errors match. ESB notes the
older normalized-transcript convention by name: **SNOR**, Standard Normalised Orthographic Representation, NIST
1998 — single-case, no punctuation, no numerals.

### 2.2 Whisper's `EnglishTextNormalizer` — what the source actually does

Read at
[`whisper/normalizers/english.py`](https://github.com/openai/whisper/blob/main/whisper/normalizers/english.py)
and [`basic.py`](https://github.com/openai/whisper/blob/main/whisper/normalizers/basic.py). The paper's Appendix C
([arXiv:2212.04356](https://arxiv.org/abs/2212.04356) p. 21) lists twelve steps; the code matches, in this order:

```
lower() → strip [bracketed] → strip (parenthesised) → delete \b(hmm|mm|mhm|mmm|uh|um)\b
→ collapse space-before-apostrophe → 40+ regex replacers → drop commas between digits
→ periods not followed by a digit → space out all Unicode M/S/P categories (keeping .%$¢€£),
  NFKD, drop Mn marks → EnglishNumberNormalizer → EnglishSpellingNormalizer (British→American)
→ strip leftover currency/percent symbols → collapse whitespace
```

The replacer table is not just contractions. It also rewrites **ordinary English words** because they are also
title abbreviations: `\bst\b → saint`, `\bgen\b → general`, `\brep\b → representative`, `\bsen\b → senator`,
`\bcol\b → colonel`, `\bhon\b → honorable`, `\bjr\b → junior`. And the general rule `r"'s\b" → " is"` expands
every possessive.

**[measured]** — running the unmodified source (pure Python, needs only `regex`; `english.json` is the
British→American map):

| input                            | output                       |
| -------------------------------- | ---------------------------- |
| `The dog's bone`                 | `the dog is bone`            |
| `It's Dr. Smith's well-known co-worker.` | `it is doctor smith is well known co worker` |
| `Mother-in-law's O'Brien recipe.` | `mother in law is 0 brien recipe` |
| `The general said hello to the rep.` | `the general said hello to the representative` |
| `one two three`                  | `123`                        |
| `1 2 3`                          | `one 2 3`                    |
| `twenty five` / `25`             | `25` / `25`                  |
| `I have one hundred dollars` / `I have 100 dollars` | `i have $100` / `i have $100` |
| `first place` / `1st place`      | `1st place` / `1st place`    |
| `Twenty-five people arrived at 3:45 p.m.` | `25 people arrived at 3 45 p m` |
| `well-known` / `well known`      | `well known` / `well known`  |
| `Um.`                            | `` (empty)                   |

Reading the table honestly: the *wins* are real and exactly the ones we need — `twenty five` ≡ `25`,
`one hundred dollars` ≡ `$100`, `first` ≡ `1st`, hyphen-splitting so `well-known` ≡ `well known`, and
punctuation/case gone. The *corruptions* are real too — `O'Brien → 0 brien` (the number normalizer reads a bare
`o` as the digit zero), `dog's → dog is`, `rep → representative`. All are **symmetric**: both reference and
hypothesis get mangled identically, so most corruptions cancel and cost nothing. They stop cancelling when only
one side contains the trigger — which for a prompted corpus is common, because the prompt is written English and
the hypothesis is what a model heard.

Two further verified properties:

- **Idempotent** on every case tested: `n(n(x)) == n(x)`. **[measured]**
- **Output can be empty.** `Um.` → `""`. A prompt that is nothing but a filler normalizes to an empty reference,
  which is the edge case §6 is about. `BasicTextNormalizer` (non-English) does *not* strip trailing whitespace
  (`Um.` → `"um "`); `EnglishTextNormalizer` does, incidentally, because `EnglishSpellingNormalizer` does
  `" ".join(s.split())`. **[measured]**

Hyphenation, specifically, is handled by the M/S/P → space step: hyphens become spaces, so `well-known` becomes
two tokens. Contractions are handled by the replacer table *before* that step, so `can't` → `can not` rather than
`can t`.

### 2.3 What the Open ASR Leaderboard actually mandates — and it is a *fork*, not Whisper's normalizer

The leaderboard paper ([arXiv:2510.06961](https://arxiv.org/abs/2510.06961)) states: *"we normalize all text prior
to computing WER. This normalization removes punctuation and casing, and applies an English text normalization
pipeline closely following that of Whisper. The pipeline includes number normalization… spelling standardization,
and the removal of filler words. On the leaderboard, models are sorted according to average WER across all
datasets of a corresponding task."*

"Closely following" is doing work. Read at
[`normalizer/normalizer.py`](https://github.com/huggingface/open_asr_leaderboard/blob/main/normalizer/normalizer.py)
(commit `f83d546`, July 2026), the leaderboard's `EnglishTextNormalizer` diverges from Whisper's in four ways:

1. **The possessive bug is fixed.** Whisper's `r"'s\b" → " is"` is replaced by
   `r"\b(it|he|she|what|that|who|here|there|how|when|where|why|this)'s\b" → r"\1 is"` — only pronoun contractions
   expand; `dog's` survives.
2. **The filler list is much longer**: `hmm|mm|mhm|mmm|uh|um|ah|aha|ahh|ahm|eh|ehehe|em|hm|huh|hum|mhum|uhm|umm|uhuh`
   versus Whisper's six.
3. **New `EnglishAcronymNormalizer`** collapses runs of single-character tokens (`b b c` → `bbc`, `5 g` → `5g`),
   with a guard so `a`/`i` need a run of 3+.
4. **New `EnglishNameNormalizer`** and a hardcoded multi-word compound map (`wi fi` → `wifi`).

And the scoring path itself has moved on: the leaderboard no longer uses `jiwer`. It uses
`kaldialign.batch_error_rate(refs, preds, merge_compounds=True)`
([`normalizer/eval_utils.py`](https://github.com/huggingface/open_asr_leaderboard/blob/main/normalizer/eval_utils.py)),
where `merge_compounds` lets adjacent words concatenate to match a single word at **zero cost** — so
`white paper` ≡ `whitepaper` in either direction. That is the 2026 algorithmic answer to the same problem NIST
solved in 2003 by hand-listing `AIRCRAFT => AIR CRAFT` in the GLM.

Finally, the leaderboard **drops samples whose normalized reference is empty**, and drops the literal string
`"ignore time segment in scoring"` — itself an inherited NIST `stm` convention
([`normalizer/data_utils.py`](https://github.com/huggingface/open_asr_leaderboard/blob/main/normalizer/data_utils.py),
`is_target_text_in_range`). Filtering, not special-casing, is how the leaderboard avoids the empty-reference
problem.

**Takeaway for us:** there is no single artifact called "the standard ASR normalizer". Whisper's published
normalizer, the one vendored into `transformers`, and the one the leaderboard actually scores with are three
different functions, and the differences are exactly in the places that bite (possessives, fillers, compounds).
Vendoring a specific normalizer at a specific revision — or writing our own short one — is the only way to get a
byte-identical golden test.

---

## 3. WER: definition, and where implementations disagree

WER = (S + D + I) / N where N = reference word count, S/D/I from a minimum-cost alignment of the two token
sequences. `sclite` states the per-category form directly
([sclite.htm](https://github.com/usnistgov/SCTK/blob/master/doc/sclite.htm)): *"Percent of substituted words =
#Substituted words / #Reference words × 100"*, and likewise for inserted and deleted — note that the *insertion*
percentage is also divided by reference words, which is why WER is unbounded above.

Disagreements that are real:

- **Edit costs.** `sclite` uses 0/3/3/4 (C/I/D/S); every Python library uses 0/1/1/1. Total error count is
  usually the same; the S-vs-(I+D) split can differ. `kaldialign` exposes `sclite_mode=True` to reproduce NIST's
  weights ([kaldialign/__init__.py](https://github.com/pzelasko/kaldialign/blob/master/kaldialign/__init__.py)).
- **Tokenization.** `torchmetrics` uses `str.split()` (any whitespace run). `jiwer`'s default `wer_default`
  pipeline is `RemoveMultipleSpaces → Strip → ReduceToListOfListOfWords`, and
  `ReduceToListOfListOfWords.process_string` does `s.split(" ")` — **the literal space character only**.
  `RemoveMultipleSpaces` only collapses `\s\s+`, so a *single* tab or newline survives into a token.
  **[measured]** `jiwer.wer("hello\tworld", "hello world") == 2.0` — one reference token, one substitution plus
  one insertion. Any normalizer we write must collapse all whitespace to single spaces itself; relying on the
  scorer to do it is a silent, uncaught 200% error.
- **Compound merging.** Off by default everywhere except the Open ASR Leaderboard's invocation, where it is on.
  Turning it on lowers WER and is not comparable to a run with it off.
- **Zero-cost alternates.** Only `sclite` has them.

## 4. CER: less standardized than WER, and the whitespace question is unsettled

There is no NIST-style authority for English CER. What the implementations do:

- **`jiwer.process_characters`** aligns per utterance and pools counts, and its docstring is explicit: *"by
  default this method includes space (` `) as a character over which the error rate is computed."*
  ([process.py](https://github.com/jitsi/jiwer/blob/master/src/jiwer/process.py)). Internally it is literally
  `process_words` with every "word" one character long, so all the WER edge-case semantics carry over verbatim.
- **HF `evaluate`'s `cer`** is *not* that. For `jiwer < 4` it passes a `cer_transform` containing
  `ReduceToSingleSentence("")` — every utterance is **concatenated into one string with no delimiter** before
  alignment, so tokens can align across utterance boundaries. For `jiwer >= 4` (which removed `compute_measures`)
  the code falls through to a branch that calls `jiwer.process_characters` with **default** transforms and never
  passes `cer_transform` at all
  ([cer.py](https://github.com/huggingface/evaluate/blob/main/metrics/cer/cer.py)). The metric's semantics
  therefore change with the installed `jiwer` version, silently.

  **[measured]** how much that matters: `refs = ["ab", "cd"]`, `hyps = ["a", "bcd"]` → per-utterance pooled CER
  **0.5**, concatenated CER **0.0**. Same inputs, same library, two answers.
- **Whisper's paper** does not define an English CER at all. For Chinese, Japanese, Thai, Lao and Burmese it says
  it *"put[s] a space between every letter… effectively measuring the character error rate instead"* — i.e. CER is
  WER over character tokens, and the space handling falls out of that construction rather than being decided.
- **The Open ASR Leaderboard reports no CER** for any English track.

Whether CER is computed on normalized or raw text: nobody documents a rule. Every implementation computes it on
whatever you hand it, and every pipeline that uses it hands it the same normalized text it used for WER.

## 5. Aggregation — corpus-level within a corpus, macro-average only across corpora

This is the question the ticket flags as most often gotten wrong, and the primary sources are unanimous in a way
that is easy to miss because they use *both* methods, for different things.

**Within a test set, every authority pools.** `kaldialign.batch_error_rate` says it outright: *"The aggregate
`err_rate` is computed as `sum(ins + del + sub) / sum(ref_len)` rather than as an average of per-sequence error
rates."* `jiwer.process_words` accumulates `num_substitutions/num_deletions/num_insertions/num_rf_words` across
all sentence pairs and divides once. `torchmetrics._wer_update` sums `errors` and `total` across the batch and
`_wer_compute` divides. HF `evaluate`'s `wer` accumulates `incorrect` and `total` in a loop and divides once —
and its `concatenate_texts` flag, in current code, reaches the same pooled formula down either branch — it is
effectively vestigial for WER outside the empty-reference edge case, despite what the docstring implies
([wer.py](https://github.com/huggingface/evaluate/blob/main/metrics/wer/wer.py)).

**Across test sets, benchmarks macro-average, and say why.** ESB: *"We average WERs over individual datasets to
give the final score. Through a macro-average, we aim to give a sense of aggregate system performance over all
datasets… we lack a fair criterion with which to weigh the contribution of each dataset, and thus weigh each
dataset equally."* The Open ASR Leaderboard: *"models are sorted according to average WER across all datasets"*,
and its `score_results` implements exactly that — pooled `err_rate` per JSONL file, then an unweighted mean of
those percentages across files.

**`sclite` prints both, side by side, and they differ a lot.** From the `lur` report example in
[outputs.htm](https://github.com/usnistgov/SCTK/blob/master/doc/outputs.htm):

```
|   2347-a    |  [250]     51.2 |
|   2347-b    |  [637]     43.6 |
|   3129-a    |  [188]     89.4 |
|   3129-b    |  [704]     51.6 |
|=================================|
| Set Sum/Avg | [1779]     52.7 |     ← pooled over all 1779 reference words
|    Mean     |  [444]     58.9 |     ← unweighted mean of the four speaker WERs
|   StdDev    |  [263]     20.6 |
|   Median    |  [443]     51.4 |
```

**6.2 points apart on four speakers.** NIST's convention — pooled headline, plus mean/StdDev/median across the
grouping variable — is thirty years old and is precisely the report shape
[#136](https://github.com/andrewferk/speech-dataset-workbench/issues/136) is being asked for.

**[measured]** how badly macro-average misbehaves on short utterances:

```python
refs = ["the cat sat on the mat and then it slept quietly", "go"]
hyps = ["the cat sat on the mat and then it slept quietly", "no"]
jiwer.wer(refs, hyps)                     # 0.0833  — pooled: 1 error / 12 words
mean(jiwer.wer(r, h) for r, h in zip(...)) # 0.5    — macro: (0.0 + 1.0) / 2
```

A single one-word utterance carries the same weight as an eleven-word one. For a prompted corpus with prompts of
wildly varying length — which is what a prompt list is — macro-average is a length-weighting decision disguised
as an averaging decision.

**Defensible for a small single-speaker prompted corpus:** pooled/corpus-level as the headline number, because it
is what every library computes by default, what every leaderboard computes within a dataset, and what makes the
number comparable to a published WER. Macro-average has a legitimate second use — averaging *across* the
breakdown groups (session, prompt, device, environment) when you want each group weighted equally regardless of
how much audio it contains — and if it is reported it must be labelled as such and never presented as "the WER".

## 6. Edge cases: every library does something different, and two of them are wrong

Read from source; the `jiwer` column is **[measured]** against `jiwer` 4.0.0, the others are derived from source
and not executed.

| case | `jiwer` 4.0.0 | `kaldialign` 0.12.0 | `torchmetrics` 1.9.0 | HF `evaluate` 0.4.6 |
| --- | --- | --- | --- | --- |
| ref `""`, hyp `""` | `0.0` | `0.0` | `nan` (0/0 on a tensor) | `ZeroDivisionError` |
| ref `""`, hyp 3 words | **`3.0`** — the raw insertion *count* | `inf` | `inf` | `ZeroDivisionError` |
| ref 2 words, hyp `""` | `1.0` | `1.0` | `1.0` | `1.0` |
| WER > 1 (ref 1 word, hyp 5) | `4.0` | `4.0` | `4.0` | `4.0` |

The `jiwer` empty-reference behaviour is deliberate and tested, not a bug — see
[`tests/test_empty_ref.py`](https://github.com/jitsi/jiwer/blob/master/tests/test_empty_ref.py), which asserts
`out.wer == i` for a hypothesis of `i` words against an empty reference. But it is a *count* returned from a
function whose return type is documented as a rate, which is exactly the kind of thing that silently poisons a
mean. Note also that `process_words`' docstring claims *"Raises ValueError: If one or more references are empty
strings"* — the code does no such thing. **The docstring is wrong.** `kaldialign`'s `_compute_error_rate` is the
honest version: `0/0 → 0.0`, `n/0 → float("inf")`.

Two more, both structural:

- **WER > 1.0 is normal, not an error.** Insertions are divided by *reference* words, so an unbounded hypothesis
  gives an unbounded WER. Manohar et al. report a real published **287.4%** for whisper-small on Malayalam
  FLEURS. Any report that clamps WER to 100% is hiding a runaway-decode failure — the single most likely failure
  mode for an unmodified model on atypical or near-silent audio, which is our population.
- **Length mismatch.** `jiwer.process_words` raises `ValueError` if the reference and hypothesis lists differ in
  length after transformation. Pairing must be by identifier, never by position.

## 7. Is a corpus WER over 12–100 utterances interpretable at all?

Partly. Two separate questions get conflated.

**Comparing our number to anything external — another model, a future fine-tune, a published WER — is
sampling-limited.** The established method is Bisani & Ney's bootstrap over utterances
(*Bootstrap estimates for confidence intervals in ASR performance evaluation*, ICASSP 2004), implemented in
Kaldi as `compute-wer-bootci` and exposed in `kaldialign` as `bootstrap_wer_ci(refs, hyps, hyps2=None,
replications=10000, seed=0)`, which returns `wer`, `ci95`, `ci95min`, `ci95max` and, given a second system, the
probability that system 2 beats system 1. It is the *only* CI machinery found in any of the candidate libraries.
Whisper's paper uses the same family — Figure 9's caption reads *"95% bootstrap estimate confidence intervals are
shown."* NIST's answer is significance testing rather than intervals: `sc_stats` implements McNemar, the Matched
Pairs Sentence Segment Word Error test (MAPSSWE), the Sign test, the Wilcoxon signed-rank test, and ANOVA by rank
([sc_stats.1](https://github.com/usnistgov/SCTK/blob/master/doc/sc_stats.1)).

**[measured]** — an illustrative bootstrap (20 000 replications over utterances, synthetic data, 10% true
per-word error rate; this is my own simulation, not a published result):

| utterances | words/utt | reference words | 95% CI width | 1 word error = |
| --- | --- | --- | --- | --- |
| 12 | 8 | 96 | 6.3 pts | 1.04 pts |
| 12 | 12 | 144 | 11.1 pts | 0.69 pts |
| 50 | 10 | 500 | 5.4 pts | 0.20 pts |
| 100 | 10 | 1000 | 3.6 pts | 0.10 pts |

At 12 utterances the 95% interval is several WER points wide and a *single misheard word* moves the headline by
~1 point. A corpus WER at that size is an order-of-magnitude readout, not a measurement: it distinguishes "5%"
from "40%", not "8.1%" from "9.4%".

**Comparing two normalizations of the same hypotheses is not sampling-limited at all.** Scoring is a pure
function of a fixed artifact; re-scoring under different rules is exact and paired, with no sampling error. So
the sub-1-point normalization deltas of §1 *are* measurable on our own corpus even though they sit far under the
CI — they just cannot be compared against anyone else's published number.

**Per-group breakdowns are standard practice and predate the modern tooling.** `sclite`'s default `sum`/`rsum`
report is *"SYSTEM SUMMARY PERCENTAGES by SPEAKER"* with `# Snt`, `# Wrd`, `Corr/Sub/Del/Ins/Err/S.Err` per
speaker and `Sum`, `Mean`, `S.D.`, `Median` rows. `sclite` also reports **sentence error rate** (*"Percent of
sentence errors = #incorrect ref and hyp pairs / #ref and hyp pairs"*) — a per-utterance binary that is far more
stable than WER at small N, since it does not depend on utterance length. It is essentially free to compute and is
worth considering alongside WER for a 12-utterance corpus. Confidence intervals on a corpus this small are *not*
standard practice in the literature (published corpora are 5–100 hours), but the counts that make a CI
computable — per-utterance S/D/I and reference length — should be emitted regardless, because they are what makes
any later analysis possible and they cost nothing.

## 8. Libraries: exact semantics, weight, and viability under the split contract

The map requires scoring to run **byte-identically in CI with no torch, no weights, no network**. That is a hard
filter.

| | version | runtime deps | normalization | aggregation | verdict |
| --- | --- | --- | --- | --- | --- |
| **`jiwer`** | 4.0.0 | `click`, `rapidfuzz` (numpy only as an *optional extra* of rapidfuzz) | none by default; `wer_standardize` offers lowercase + naive contractions + Kaldi non-words | pooled | **viable** — three pure/compiled wheels, no torch, no network |
| **`kaldialign`** | 0.12.0 | **none** (compiled extension, Python ≥3.10) | none | pooled; explicitly documented | **viable** — lightest of all, and the only one with bootstrap CIs and `sclite_mode` |
| **HF `evaluate`** | 0.4.6 | `datasets`, `numpy`, `pandas`, `dill`, `multiprocess`, `xxhash`, `fsspec`, `huggingface-hub`, `tqdm`, `requests` | none | pooled | **disqualified** — see below |
| **`torchmetrics`** | 1.9.0 | **`torch>=2.0.0`**, `numpy`, `packaging`, `lightning-utilities` | none | pooled | **disqualified** — torch in the scoring path is exactly what the split contract forbids |
| **`sclite`** (SCTK) | — | C toolkit, not on PyPI | GLM data file | pooled `Sum/Avg` + `Mean`/`S.D.`/`Median` | not a dependency; useful as an **oracle** to validate golden fixtures once |

`evaluate` is disqualified on a stronger ground than dependency weight. `evaluate.load("wer")` does not import a
local metric — it constructs `HubEvaluationModuleFactory("evaluate-metric/wer", revision=revision)` with
`HUB_DEFAULT_VERSION = "main"`, resolves
`https://huggingface.co/spaces/evaluate-metric/wer/resolve/main/wer.py`, downloads it and executes it
([loading.py](https://github.com/huggingface/evaluate/blob/main/src/evaluate/loading.py) lines ~625–655,
[config.py](https://github.com/huggingface/evaluate/blob/main/src/evaluate/config.py) lines 25–28). The metric is
remote code at an unpinned branch head. A golden test cannot be byte-identical against that, and CI cannot run
offline.

Between the two viable options: `jiwer` gives alignment chunks (`AlignmentChunk` with type and index spans) and a
visualizer, which is what makes a per-utterance error report legible; `kaldialign` gives zero dependencies,
bootstrap CIs, `sclite_mode`, and `merge_compounds`, but returns only counts. Note `kaldialign` requires Python
≥3.10 and ships a compiled extension — check wheel availability for the target platforms before committing.

## 9. Where credible sources genuinely diverge

1. **Symmetric code vs. asymmetric data.** NIST applies a hand-curated, corpus-specific GLM, some of whose rules
   run on the hypothesis only, and encodes genuine ambiguity as zero-cost alternates. Whisper/HF apply one global
   Python function identically to both sides and resolve ambiguity by fiat. Neither is a refinement of the other.
   The modern approach is reproducible and portable; the NIST approach is more correct and unscalable.
2. **Is normalization measurement or laundering?** Whisper's paper defends it — *"a best-effort attempt to
   penalize only when a word error is caused by actually mistranscribing a word"* — while conceding the risk in
   §4.4 and checking it against FairSpeech's independent normalizer. Manohar et al. argue from measurement that
   the same routine produces *"artificially improved performance metrics"*, and that the languages with the worst
   normalization damage show the largest WER gains — normalization improving the score *because* it destroys the
   text. Both are right about different regimes. For punctuated English the effect is ~3–5 points and defensible;
   the disagreement is about whether that is a floor or the start of a slope.
3. **How much of the "50%" claim is normalization.** Whisper's §3.2 headline and ESB's Table 4 differ by an order
   of magnitude. They are not in conflict: Whisper's figure is *relative*, *maximal*, and attributed to reference
   formatting quirks; ESB's is *absolute*, *averaged*, and layered. Any downstream document that cites "up to 50%"
   as the value of normalization has conflated them.
4. **Whether compound merging is legitimate.** The Open ASR Leaderboard turns `merge_compounds=True` on for all
   scoring, on the argument that split-vs-joined spelling is not a recognition error. It is a scoring-time change
   that lowers WER and breaks comparability with every number computed before it. No paper found argues the
   opposite in print; the divergence is between current leaderboard practice and every historical published WER.
5. **Which normalizer is "Whisper's".** `openai/whisper`, `transformers`, and `open_asr_leaderboard` ship three
   different functions under the same class name. Citing "the Whisper normalizer" without a revision is
   ambiguous.

**Not verified.** Two things I could not confirm and am not asserting: (a) the per-dataset values behind Figure 10
of the Whisper paper (relative WER reduction vs the FairSpeech normalizer) are not tabulated anywhere in the
paper — only the boxplot, whose axis runs 0–50%, and the named outliers WSJ, CallHome and Switchboard; (b) the
exact `torchmetrics` and HF `evaluate` edge-case outputs in §6, which are read from source rather than executed,
because both require dependency closures this research deliberately did not install.

## 10. One interaction with the map's named ceiling

The map names the ceiling: v0.1 collects intended text only, so WER is measured against the **prompt** and
conflates recognition error with speaker deviation. Normalization is not neutral with respect to that ceiling.

A written prompt can never contain `um`, `uh`, `hmm`. A real utterance can, and a model that transcribes them
faithfully will be charged an insertion for each. **Filler-word removal is therefore the one aggressive
normalization rule that directly attacks the named ceiling**, and it is worth far more on a prompted corpus than
its share of ESB's 0.5-point "everything else" bucket implies — ESB's references are real transcripts that
*contain* disfluencies, so removing fillers from both sides is nearly a no-op there and is not for us. This is
reasoning from the sources, not a measurement in them.

The converse also holds: aggressive normalization *hides* speaker deviation, which is the thing
`perceived_text` exists to capture. Removing fillers makes a disfluent read look identical to a fluent one. That
is the right call for a *recognition* baseline and the wrong call for a *deviation* measurement, and it is a
reason for the report to say which one it is measuring rather than a reason to pick differently.

---

## Open sub-choices handed to [#132](https://github.com/andrewferk/speech-dataset-workbench/issues/132)

This research does **not** make these calls. It sizes them.

1. **Which normalization tier, and whether to report one number or two.** Tier A (NFKC → casefold →
   Unicode M/S/P → space → collapse whitespace) is uncontroversial and buys ~2.5–4.7 points. Tier B (contractions,
   number standardization, spellings, fillers) buys ~0.5–0.9 more on published data, is worth more than that here
   because of fillers (§10), and carries verified corruptions (§2.2). Because re-scoring is free, reporting both
   is available and cheap — but two headline numbers is a report-design cost, not a free lunch.
2. **Vendor, depend, or write.** Vendoring `EnglishTextNormalizer` at a pinned revision (which revision — OpenAI's
   or the leaderboard's fork?) versus depending on a package versus writing ~40 lines ourselves. All three can be
   byte-identical; they differ in who owns the bugs and in whether our number is comparable to a leaderboard
   number. Note that vendoring OpenAI's version imports `english.json` (56 KB) and a `regex` dependency.
3. **Symmetric or asymmetric.** Whether reference and hypothesis go through the same function. The prompt is
   authored text and the hypothesis is model output; the NIST tradition treats them differently for good reasons
   we cannot fully replicate without alternates.
4. **Scoring library:** `jiwer` (alignment chunks, error visualization, 2 deps) vs `kaldialign` (0 deps,
   bootstrap CIs, `sclite_mode`, Python ≥3.10 + compiled wheel) vs implementing Levenshtein ourselves (~30 lines,
   zero deps, total control of edge cases, no alignment visualization for free).
5. **`merge_compounds` on or off.** On matches current leaderboard practice and forgives `well known` /
   `wellknown`; off matches every historical published WER. Cannot be both.
6. **Our own empty-reference and empty-hypothesis semantics.** No library's default is adoptable as-is: `jiwer`
   returns an insertion *count*, `kaldialign` returns `inf`, `torchmetrics` returns `nan`, HF raises. Decide
   independently what a row with an empty normalized reference contributes to the pooled numerator and
   denominator, whether such rows are dropped (leaderboard practice) or retained-and-flagged, and whether a
   per-utterance rate is emitted for them at all. Also: what a corpus with zero total reference words does —
   error, not `0.0` and not `inf`.
7. **WER > 1.0 handling.** Confirmed normal and unbounded; decide whether the report clamps (it should not),
   flags, or ranks by it, and whether a runaway decode is surfaced as a distinct condition.
8. **CER at all, and if so with what whitespace semantics.** Per-utterance-aligned-then-pooled (jiwer default) vs
   concatenated (HF `evaluate` on older `jiwer`) — **[measured]** to differ by 0.5 vs 0.0 on a two-utterance toy.
   And whether the space character counts as a character. No external authority to defer to; this is ours to fix.
9. **Aggregation labelling in the report.** Pooled is the headline (§5). Whether the per-group breakdown
   additionally shows a macro-average across groups, and how it is labelled so it is never mistaken for the WER.
10. **Whether sentence error rate joins WER/CER.** Free to compute, far more stable than WER at N=12, and a NIST
    convention (`S.Err`).
11. **Whether the report carries a CI.** `kaldialign.bootstrap_wer_ci` makes it a one-liner if that library is
    chosen; otherwise it is ~20 lines. §7 argues the number is an order-of-magnitude readout without one.
12. **Whitespace hygiene in the normalizer contract.** `jiwer`'s default tokenizer splits on the literal space
    only; a surviving tab produces a 200% error. Whatever normalizer is chosen must guarantee single-space
    separation and the golden tests must cover tab/newline/NBSP inputs.
