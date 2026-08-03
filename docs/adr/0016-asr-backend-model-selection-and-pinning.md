# ASR backend, model selection & pinning (v0.2)

v0.2 puts a model inside a tool that until now had none. Everything else on the evaluation map —
the Hypothesis Record and the Run provenance it carries, the Evaluation Report's Breakdowns — is
downstream of *which model, run how*, so this ADR fixes that first. It consumes research #127 (ASR runtime & model
landscape) and resolves #131.

It builds on ADR-0005 (WAV-only ingest, mono/16 kHz/PCM_16 Normalized target, zero FFmpeg),
ADR-0006 (`[manifest].lang`), ADR-0007 (quality flags are advisory; `duration_max_s` is
configurable), ADR-0010 (`dataset_version` covers manifest bytes and effective config) and
ADR-0015 (evaluation vocabulary, whose terms this ADR uses throughout). It amends none of them.
Every ADR written for v0.1 assumed no model ever runs in this tool; that assumption ends here, and
the isolation this ADR specifies is what keeps it true of the `build` path.

The reproducibility contract splits in two, and this ADR sits entirely on the non-reproducible
side: Transcription is **attributed, not reproducible**. No runtime surveyed in #127 documents
reproducibility at all — PyTorch disclaims it across releases, commits and platforms in writing.
That is not a concession to be worked around; it is the only honest position available, and it
makes the job here *removing every variance that can be removed and disclosing the rest*, rather
than pretending to a determinism nobody offers.

## Decisions

### Runtime — `transformers`, with first-party OpenAI weights

The eval path runs **`transformers`** against **`openai/*`** checkpoints on the Hugging Face Hub.

Research #127 recommended `faster-whisper` (CTranslate2), leading with the argument that it is the
only viable runtime needing no torch, which would make the map's "CI scores with no torch" property
a fact about the dependency graph rather than about test discipline. That argument does not
survive the packaging shape #137 is settling: the ASR stack sits behind an opt-in boundary and the
scoring path imports none of it, so CI is torch-free under either runtime. What the runtime choice
actually decides is how heavy the venv gets **when you opt in** — a real cost (111 MB download,
~471 MB unpacked, plus `setuptools`, `sympy` and `networkx` in the runtime environment), but a
smaller claim than the one that led the recommendation.

Three things decide it the other way, and the first is the one that matters:

- **Provenance.** `faster-whisper`'s size aliases resolve to CTranslate2 conversions published by
  SYSTRAN and Mobius Labs — not artifacts OpenAI ever released. #127 could not verify they are
  faithful conversions; `model.bin` at 3087.3 MB against `model.safetensors` at 3087.1 MB is size
  arithmetic, not attestation. The chain a report would have to state is "OpenAI weights → a third
  party's converter run → this commit sha." The map's destination asks for enough provenance that
  today's number can be honestly compared against a future fine-tuned model's; an unattested link
  in the middle of that chain is the wrong place to economise.
- **v0.3 is a `transformers` problem.** Fine-tuning produces a `transformers` checkpoint. Under
  this runtime, the future model is the same code path with a different repo id. Under
  `faster-whisper` it is either a genuine second backend or a `ct2-transformers-converter` step we
  would own.
- **Learning.** #131 asks explicitly whether the engineering consideration or the learning one wins,
  and warns that a runtime making Whisper a one-liner may be the right engineering choice and the
  wrong learning choice. Here they point the same way: HF model tooling is one of the three areas
  this project exists to learn, and CTranslate2 teaches CTranslate2. That the two considerations
  agree is why this choice is comfortable rather than a trade.

**Offline capability does not discriminate**, which is why it is absent from the three reasons
above rather than overlooked. #131 lists it among the factors to weigh, and both candidates
satisfy it: `faster-whisper` takes `local_files_only=` as a constructor argument, and the HF Hub
honours `HF_HUB_OFFLINE=1` plus `local_files_only=True` on `from_pretrained`. Each reaches a
fully-populated cache with the network down, so the criterion is met on both sides and decides
nothing between them. It does not discriminate anywhere else in the surveyed set either: every
candidate loads from a local cache once the weights are present. #131 lists offline capability
and provenance/pinning as separate factors, and they stay separate here — `pywhispercpp` is
rejected below on pinning, which is not an offline failure.

It also disposes of the one unresolved licensing question in #127. `faster-whisper` requires `av`,
whose wheels bundle an FFmpeg built with `--enable-libx264 --enable-libx265` — codecs FFmpeg's own
`configure` refuses without `--enable-gpl`, though the flag is absent from the published build
scripts and pyav-ffmpeg publishes no licence statement. ADR-0005 accepted LGPL deliberately and
said nothing about GPL. Choosing `transformers` makes the question moot rather than open.

### Model — `openai/whisper-large-v3-turbo`, hard-coded

```
repo id   openai/whisper-large-v3-turbo
revision  41f01f3fe87f28c78e2fbf8b568835947dd65ed9
licence   mit
```

The checkpoint is a **source constant, not configuration, and not a CLI argument** — the same
posture ADR-0005 took toward the Normalization procedure. One Run evaluates one model.

Two properties beyond accuracy decided the checkpoint. It is the **only** Whisper checkpoint whose
HF card (`mit`) agrees with the openai/whisper README's claim that "Whisper's code and model
weights are released under the MIT License"; every other card declares `apache-2.0` against that
same README. And its repo total is 1622.5 MB against a 1617.8 MB model, so there is no shard trap
— `openai/whisper-large-v3` totals **24.7 GB** because it also carries Flax, PyTorch-bin and two
fp32 shard sets, and `openai/whisper-small` totals 3872.9 MB for a 967 MB model.

Where the choice is *fixed*, the baseline should be the strongest practical one: a weak baseline
silently flatters whatever v0.3 measures against it, and that is the one error this map's
destination cannot absorb.

Two consequences are accepted deliberately rather than overlooked. A **size ladder** — tiny → small
→ turbo on the operator's own speech, which #131 called arguably the most interesting thing v0.2
could report — becomes a code edit and a re-run, not an invocation. And **v0.3's fine-tuned
comparison becomes an ADR amendment**, because the backend is fixed. Both were weighed; neither was
missed. Widening is an ADR change, not a code change.

### API surface — explicit processor and `generate()`, never the pipeline

The eval path constructs `WhisperProcessor` and `WhisperForConditionalGeneration` directly and
calls `generate()` with the decode constants passed explicitly. It does not use
`pipeline("automatic-speech-recognition", ...)`.

This is what keeps ADR-0005's zero-FFmpeg promise **structural rather than disciplined**. #127
verified that `soundfile.read(path, dtype="float32")` on a v0.1 Normalized WAV is bit-identical to
`int16/32768` — exactly what every runtime's own decoder produces — but only if the **array** is
passed. Every path-based entry point routes through FFmpeg, and the HF pipeline calls `ffmpeg_read`
for `str`/`bytes` inputs. Under the explicit API there is no path parameter to reach for. This is
ADR-0012's move again: make the wrong thing unrepresentable rather than forbidden.

It also puts the decode parameters in our source rather than in a `generation_config.json` we do
not control, so the call site and the Run's provenance quote the same constants.

Audio is read as **float32** (not `soundfile`'s `float64` default; the extra precision buys nothing
and every runtime casts it anyway).

### Decode parameters — seven constants, no guards

```
task                     "transcribe"
language                 <effective, see below>
do_sample                False
num_beams                1
temperature              None
condition_on_prev_tokens False
return_timestamps        False
```

Fixed constants, not config. The model itself is not selectable, so exposing its decode knobs would
draw the line in a strange place.

`temperature=None` is load-bearing. `transformers` is the **only** runtime surveyed where
temperature 0 is already the default: `openai-whisper`, `faster-whisper` and `whisper.cpp` all ship
a `(0.0 … 1.0)` fallback ladder that **engages an RNG** whenever a window trips the
compression-ratio or logprob threshold. We inherit the good default rather than fighting a bad one,
and still pass it explicitly. `num_beams=1` is likewise stated rather than assumed — `faster-whisper`
defaults to beam 5 where `openai-whisper` is greedy, which is why two Whisper implementations are
not comparable at their defaults.

**No repetition penalty, no `no_repeat_ngram_size`, no `max_new_tokens` cap.** A repetition penalty
changes the model's output to flatter the metric, and this baseline exists to measure the unmodified
model. A length cap buys little: Whisper is architecturally bounded at 448 decoder positions, so a
runaway is already finite. Letting it run means a blown Hypothesis surfaces as a WER above 1.0 —
which ADR-0015 already forbids clamping and the Scoring spec (#132) must not either, precisely so
the failure stays visible rather than tidied away. Runaway decoding on quiet or atypical audio is
this Dataset's likeliest failure mode; hiding it would be the wrong kindness.

### Language — from the manifest, defaulting to `"en"`, with its source recorded

`language` is read from **`[manifest].lang`** (ADR-0006) and passed to `generate()`. When it is
`null` — the v0.1 default — the effective value is **`"en"`**, and the Run's provenance carries
both the effective value and whether it was `declared` or `defaulted`.

**Language detection is ruled out.** Its problem is not non-determinism — under greedy decoding with
pinned weights, detection is an argmax over language tokens and answers the same way every time.
The problem is that it makes the Hypothesis depend on an input appearing nowhere in the Run's
provenance, varying per-Sample within one Run. On quiet, atypical or near-silent audio — the population
this product exists for — mis-detection produces fluent garbage that lands in the report as
*recognition error*, indistinguishable from it. That is the same silent inversion the map already
rejected ASR-as-dataset-QA for.

Reading the manifest is the stranger-consumer contract doing its job: the dataset declares its
language and the evaluator obeys. Because `lang` is already inside `dataset_version` (ADR-0010
hashes manifest bytes and canonical config), language is provenance-covered at no cost, and the
report cannot disagree with the dataset it read.

Defaulting rather than aborting keeps an unlabelled v0.1 dataset evaluable — labelling one changes
the manifest bytes and therefore its `dataset_version`, which is correct but is a re-versioning we
decline to force. Recording `declared` vs `defaulted` is what stops that convenience becoming a
silent assumption: the map's posture is deterministic where possible, **disclosed where it is not**.

`task="transcribe"` is passed explicitly regardless, so a mislabelled `lang` can never silently
become translation.

### Device — CPU, float32, hard-coded

`device="cpu"`, dtype `float32`. **No MPS path exists**, opportunistic or otherwise.

torch states in writing that "results may not be reproducible between CPU and GPU executions, even
when using identical seeds" — and **MPS appears zero times** on torch's randomness notes and zero
times on `torch.use_deterministic_algorithms`. Its MPS notes page is two paragraphs with no
maturity label, no unsupported-op list and no numerics statement. Absence of a "beta" label is an
absence of documentation, not a stability guarantee.

Transcription being attributed-not-reproducible licenses us to disclose irreducible variance; it
does not license us to add removable variance. Device is removable. The specific risk is pointed:
v0.3 compares a fine-tuned model against this baseline, and if that comparison ever straddles CPU
and MPS, torch's own documentation says the difference may not mean what it appears to.

The cost is wall clock — every clip is zero-padded to 30 s so the workload is encoder-bound, and
turbo's speedup is decoder-only, leaving it at roughly `large-v3`'s encode cost. The architecture
absorbs this: the Hypothesis Record means Transcription runs **once**, while the iteration that
actually happens in ASR evaluation — arguing about Text Normalization — is re-Scoring, which needs
no model at all.

**CPU thread count is recorded, not pinned.** This is a deliberate inconsistency with the paragraph
above and is named rather than hidden. Floating-point reductions are order-dependent and thread
count changes the order, so two machines with different core counts produce different Hypotheses
from identical inputs. But unlike device, thread count has no correct value: pinning to 1 costs
several times the wall clock, and pinning to 4 is a number we invented with no reference run to
match. The resolved value goes in the attribution, where a future comparison can check it.

`attn_implementation` is likewise **recorded, not pinned** — the kernel selected is a numerics
input, but pinning `eager` would cost speed to fix a variance we have not observed.

### Weights — fetched on demand at the pinned revision

`from_pretrained(repo_id, revision=<sha>)` fetches only the files it needs. A first run downloads
~1.6 GB and says so; subsequent runs hit the cache.

The three network states are decided separately, because only one of them is an error:

| State | Outcome |
| --- | --- |
| Network, cold cache | Downloads at the pinned revision, announced. |
| No network, warm cache | **Runs normally.** The pinned revision is a cache key, so the cached sha names the same *weight bytes* the network would have served; `HF_HUB_OFFLINE=1` is honoured and never overridden by this tool. This is a claim about the weights loaded, **not** about the Hypotheses produced — Transcription stays attributed-not-reproducible whether the network is up or down. |
| No network, cold cache | **Hard error** — ADR-0005's "if it does not decode, the build aborts" applied to a missing required input. |

Pinning by sha is what makes the middle row safe: a revision that resolved to a tag or a branch
could name different bytes online than the ones already cached, and the offline run would be the
one telling the truth.

Cache location is **not** set by this tool: `HF_HOME` / `HF_HUB_CACHE` govern, per the ecosystem
convention. Where that lands in packaging and `.gitignore` guidance belongs to #137.

No CI job reaches this code — the Scoring path is model-free and torch-free by construction — so
allowing downloads costs CI nothing.

### Over-length samples — checked and disclosed, never rejected

Whisper's short-form path is selected by `total_input_frames <= 3000` (30 s at 16 kHz). ADR-0007's
`duration_max_s = 20.0` puts every default-configured Sample inside it, but that threshold is
**configurable** and `duration_out_of_range` is a **soft flag** — an over-length recording is
included and flagged, and a dataset built with `duration_max_s = 45` produces 30–45 s clips
routinely.

The evaluator computes, per Sample, whether the frame count exceeds 480 000; records it on that
Sample's Hypothesis Record line; and warns at Run level with the count. It does **not** abort.

The sharpest version of the risk is already defused by the decode constants, which apply in **both**
regimes: `temperature=None` and `condition_on_prev_tokens=False` mean a long-form sample decodes
greedily, with no fallback ladder and no cross-window text carry-over. It is a different *shape* of
decode — sequential windows — not a non-deterministic one. What remains is that a report could
silently mix two regimes, and disclosure fixes that.

Aborting was the tempting alternative and is rejected on ADR-0007's own logic: v0.1 deliberately
**includes** over-length samples rather than rejecting them, and an evaluator that refuses the
dataset's own data over an internal detail of Whisper's window size has stopped being a
stranger-consumer and started imposing its architecture on the dataset.

### Model identity in the Run's provenance

`CONTEXT.md` places the provenance of a Run on the **Hypothesis Record**, which carries it
alongside each Hypothesis; "provenance record" is #134's working name for that field set, not a
second artifact. #134 owns its shape and where it sits. This ADR mandates only the
model-identifying fields within it:

> **Amended by ADR-0019 (#133): "where it sits" is decided, and #134 keeps only the content.**
> The provenance lives in `run.json`, a sibling of `hypotheses.jsonl` inside the Run directory — not
> per-line and not on a header line, because ADR-0017 made provenance the completeness sentinel and a
> header cannot be written last. "Not a second artifact" survives: the two files are one Run
> directory, and neither is readable as a Run without the other. #134 still owns the field set,
> including the table below.

> **Amended by ADR-0020 (#134): the set is ratified; three keys are re-spelled.** `run.json` groups
> its fields into nested blocks, so `model_repo_id`, `model_revision` and `model_license` are
> `model.repo_id`, `model.revision` and `model.license`. This table mandated the model-identifying
> *fields* — a set, not a spelling — and every one of them is present. Two placements also differ
> from the reading this table invites: `language` sits in its own block beside `language_source`
> rather than among `decode_params`, because a fact recorded twice can disagree with itself; and
> `torch_num_threads` sits in `runtime` beside the host-architecture fields it shares its
> reduction-order reason with.

| Field | Value |
| --- | --- |
| `model_repo_id` | `openai/whisper-large-v3-turbo` |
| `model_revision` | `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` |
| `model_license` | as declared by the fetched artifact |
| `runtime` | `transformers` |
| `transformers_version`, `torch_version` | resolved |
| `device`, `dtype` | `cpu`, `float32` |
| `attn_implementation` | resolved |
| `decode_params` | the seven constants |
| `language`, `language_source` | effective value; `declared` \| `defaulted` |
| `torch_num_threads` | resolved |

Two entries exist only because #127 went looking. `model_license` reads **from the artifact**, never
from a project-wide constant: turbo makes the README/card conflict vanish today, but a hard-coded
licence string would be a lie waiting for the next checkpoint. And `torch_num_threads` is there for
the reduction-order reason above — a fact a naive record would omit and a future comparison would
need.

## Consequences

- The `build` path stays model-free. ADR-0005's zero-FFmpeg property survives at the install level
  (no `av`) and at the API level (array in, never a path).
- torch enters the lockfile, but only inside the opt-in eval stack; #137 owns how.
- The size ladder and the v0.3 fine-tuned comparison both require an ADR amendment. Deliberate.
- Every field the report needs to state its own conditions is fixed here: model, revision, licence,
  decode parameters, language and its source, device, dtype, thread count.
- Nothing here makes Transcription reproducible, and nothing here claims it is.

## Rejected alternatives

**`faster-whisper` (CTranslate2)** — research #127's recommendation, and the strongest rejected
option: 24 packages / 61.7 MB against `transformers[torch]`'s 36 / 156.7 MB, a 1.3 MB engine on
Apple Silicon (Accelerate + Ruy, no bundled BLAS), and `revision=` / `download_root=` /
`local_files_only=` as first-class constructor arguments. Rejected on provenance — third-party CT2
conversions of unverified fidelity — with the unresolved PyAV/FFmpeg GPL question and the v0.3
second-backend problem reinforcing it. Its dependency-weight advantage was real but bought less than
claimed, since the torch-free Scoring path comes from the import boundary, not the runtime.

**`faster-whisper` with local `ct2-transformers-converter`** — recovers first-party provenance while
keeping the light runtime. Rejected because it trades an unattested third-party artifact for a
locally-produced one whose bytes we must then pin ourselves, and adds a conversion step requiring a
torch install anyway.

**`openai-whisper`** — the reference implementation, and the heaviest install at 23 packages /
181.5 MB, of which 40.5 MB is `llvmlite` serving word-timestamp DTW kernels we do not want. Its
weights cannot be pinned by anything but the library version (the sha rides in the download URL);
its loader shells out to a system `ffmpeg` binary ADR-0005 deliberately eliminated; it last shipped
2025-06-26; and its own README claims compatibility only with Python 3.8–3.11 while this repo
requires ≥3.13.

**`pywhispercpp` (whisper.cpp)** — the interesting outlier at 9 packages / 16.4 MB with Metal for
free. Rejected on provenance, not weight: its downloader hardcodes `resolve/main/ggml` and cannot
pin a revision at all, and the vendored whisper.cpp version (v1.8.4 in `pywhispercpp` 1.5.0, against
upstream v1.9.1) is invisible to `pyproject.toml`. For a project whose reproducibility rests on
pinned versions, an unpinnable C++ engine is the wrong trade. #127 also flags an unverified
source-read hazard: decoder 0's RNG appears to carry across `whisper_full()` calls on one context.

**`nemo_toolkit[asr]`** — mechanically non-viable here, not a matter of taste. 172 packages with
seven source builds on this platform, and a `transformers~=4.57` pin against current 5.14.1 that
cannot coexist with a modern `transformers` in a single-`pyproject.toml` repo. NVIDIA's install docs
never mention macOS.

**Parakeet TDT (`nvidia/parakeet-tdt-0.6b-v3`) via `transformers`** — named and rejected on the
record, because "we inherited Whisper" is not a decision. It is the one serious non-Whisper
contender: reachable without NeMo through first-party `transformers` support since 2025-09-25, ahead
of Whisper on the Open ASR Leaderboard (5.661 avg WER at 0.6 B params), CC-BY-4.0, an input contract
of 16 kHz mono matching ours exactly, output carrying punctuation and capitalisation, and — the part
that stings — **no sampling machinery at all**, making it strictly simpler than Whisper on the
determinism axis. Rejected because **no primary source claims it runs on macOS or CPU**: NVIDIA's
cards say the models are designed for NVIDIA GPU-accelerated systems and list Linux as the only
supported OS. Not forbidden, but unclaimed and unmeasured, and a baseline is the wrong place to
find out. `-v2` additionally ships only a `.nemo` file, so the `transformers` route requires `-v3`.

**`facebook/wav2vec2-base-960h` and `facebook/mms-1b-all`** — rejected on their vocabularies, not
their accuracy. wav2vec2's `vocab.json` is 32 tokens: uppercase letters, apostrophe and a word
delimiter, with no lowercase, no punctuation and no digits; MMS's `eng` vocab is lowercase-only.
Both force a Text Normalization scheme onto Scoring *before a number exists at all*, which is
exactly what the map keeps downstream of the Hypothesis Record. MMS is also CC-BY-NC-4.0.

**Making the backend pluggable now** — a backend abstraction with one implementation is speculative
generality, and #131 asks the question honestly because v0.3's fine-tuned comparison is by
definition a second model. Rejected because choosing `transformers` largely dissolves it: a
fine-tuned checkpoint is the same runtime with a different repo id, so the seam that future needs is
a constant, not an interface.

**Language detection, and forcing `"en"` as a constant** — detection rejected above. Forcing a
constant was the option most consistent with the fixed-not-selectable posture, and is rejected
because it builds a permanent disagreement-in-waiting between the tool's hard-coded assumption and
the manifest's own `lang` field, and forecloses any non-English dataset without an ADR change.
Reading `lang` adds no knob; it consumes one v0.1 already has.

**MPS, opportunistic or mandatory** — several times faster on this encoder-bound workload, which
would matter if Transcription were iterated. It is not: the Hypothesis Record makes it a
run-once stage. Rejected for the documentation gap above.

**Richer Hypothesis Record telemetry** — per-segment timestamps, token logprobs and confidence scores were
open on the map pending what the backend exposes. `transformers` exposes all three cheaply
(`return_timestamps`, `output_scores`). Rejected for v0.2 anyway, in favour of the minimal constant
set: none of them feeds WER, CER or the Evaluation Report's Breakdowns, and each would need its own place in
the Hypothesis Record schema (#133) and its own determinism story.
