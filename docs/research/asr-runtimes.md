# ASR runtime & model landscape (research #127)

Feeds [#131 (ASR backend, model selection & pinning)](https://github.com/andrewferk/speech-dataset-workbench/issues/131)
and [#137 (packaging, optional dependencies & the import boundary)](https://github.com/andrewferk/speech-dataset-workbench/issues/137).
This document **reports**; it decides nothing. The final section names what it hands on.

**Verified 2026-07-29** against primary sources only — official docs, library source at the
published tag, HF model-card front-matter, and PyPI metadata. Every version number below was read
live, not recalled. Dependency resolutions were produced locally with `uv pip compile` against the
real index on the real machine (macOS arm64 / Darwin 25.5, CPython 3.13.14, uv 0.11.29); **nothing
was installed and no model weights were downloaded**, so every claim marked *measured* is metadata
arithmetic, and every claim about runtime behavior is source-reading unless stated otherwise.

Where a source contradicts another source, both are shown. Where a claim could not be checked, it
says so. See [Could not verify](#could-not-verify) for the consolidated list.

---

## 1. The candidates, and which ones survive contact with this repo

The repo declares `requires-python = ">=3.13"`, uv-managed, single `pyproject.toml`, PEP 735
dependency groups. That constraint alone eliminates one candidate outright and reduces another to
a curiosity.

Resolutions below are `uv pip compile <pkg>` on this machine, with wheel download sizes summed from
PyPI's `size` field for the best-matching `cp313` / `abi3` / `py3-none-any` macOS arm64 artifact.

| Runtime | Latest | Released | Resolves on py3.13 macOS arm64 | Packages | Wheel download | Needs torch |
|---|---|---|---|---|---|---|
| `pywhispercpp` (whisper.cpp) | 1.5.0 | 2026-05-30 | yes, all wheels | **9** | **16.4 MB** | no |
| `faster-whisper` (CTranslate2) | 1.2.1 | 2025-10-31 | yes, all wheels | **24** | **61.7 MB** | **no** |
| `transformers[torch]` | 5.14.1 | 2026-07-16 | yes, all wheels | 36 | 156.7 MB | yes |
| `openai-whisper` | 20250625 | 2025-06-26 | yes, all wheels | 23 | **181.5 MB** | yes |
| `nemo_toolkit[asr]` | 2.7.3 | 2026-04-23 | resolves, but **7 source builds** | **172** | **392 MB** | yes |

Sources: [`openai-whisper`](https://pypi.org/pypi/openai-whisper/json),
[`faster-whisper`](https://pypi.org/pypi/faster-whisper/json),
[`transformers`](https://pypi.org/pypi/transformers/json),
[`pywhispercpp`](https://pypi.org/pypi/pywhispercpp/json),
[`nemo_toolkit`](https://pypi.org/pypi/nemo_toolkit/json).

### `nemo_toolkit[asr]` is not viable here, and the reason is not taste

The local resolve succeeds — and that is misleading. Seven of the 172 packages have **no wheel at
all** on this platform and must compile from source: `kaldialign==0.8.0`, `kaldi-python-io==1.2.2`,
`sox==1.5.0`, `editdistance==0.8.1`, `grpcio==1.83.0`, `antlr4-python3-runtime==4.9.3`, `wget==3.2`.
`kaldialign` is the sharpest: NeMo pins `kaldialign<=0.9.1`, and 0.9.1's cp313 wheels are
manylinux/win only ([PyPI](https://pypi.org/pypi/kaldialign/json)) — cp313 macOS wheels first appear
in 0.9.2, which the pin excludes. uv therefore walks back to 0.8.0, the newest version under the pin
that ships an sdist at all, and builds C++/CMake.

Two further blockers:

- NeMo 2.7.3 requires **`transformers~=4.57.0`**. Current `transformers` is **5.14.1**. NeMo cannot
  coexist with a modern `transformers` in one environment — fatal for a single-`pyproject.toml`
  repo, which is exactly the shape [#137](https://github.com/andrewferk/speech-dataset-workbench/issues/137) is deciding.
- NVIDIA's install docs never mention macOS. [NeMo Speech install](https://docs.nvidia.com/nemo/speech/nightly/starthere/install.html)
  lists "Python 3.12 or above", "PyTorch 2.7 or above", "NVIDIA GPU + CUDA (required for training;
  CPU-only inference is possible but slow)" — Linux is the only OS named. Note this also contradicts
  the shipped metadata, which declares `requires_python = ">=3.10"` and carries only a
  `Programming Language :: Python :: 3.10` classifier.

Credit where due: NeMo does gate its NVIDIA packages correctly
(`cuda-bindings; platform_system != "Darwin"`), MPS inference is real and documented
([results.html](https://docs.nvidia.com/nemo/speech/nightly/asr/results.html);
`examples/asr/transcribe_speech.py` carries `allow_mps: bool = False  # allow to select MPS device
(Apple Silicon M-series GPU)` and logs *"MPS device … support is experimental"*), and the toolkit
itself is Apache-2.0. **None of that survives the `transformers` pin.** And — see §7 — you do not
need the toolkit to run its models.

### `openai-whisper` is the reference implementation and the heaviest install

It is the *only* candidate whose upstream README does not claim to support this Python. Verbatim:
*"the codebase is expected to be compatible with Python 3.8-3.11"*
([README](https://github.com/openai/whisper/blob/main/README.md)), while the PyPI classifiers do list
3.13. Both are upstream statements and they disagree; the resolve works, but nobody upstream is
promising it does.

Its weight is not mostly torch. `numba` (for the word-timestamp DTW kernels) drags in **`llvmlite`
at 40.5 MB** — a fifth of the install, for a feature this project has no stated need for. Combined
with torch's 111.2 MB that is 84% of the total.

The last release is **2025-06-26**, thirteen months ago.

---

## 2. Install weight & platform reality on macOS arm64

### torch supports the Python floor, comfortably

Current stable is **torch 2.13.0**, released **2026-07-08**
([PyPI](https://pypi.org/pypi/torch/json); [releases API](https://api.github.com/repos/pytorch/pytorch/releases)).
`requires_python = ">=3.10"`, classifiers through 3.14. PyTorch's own
[Release Compatibility Matrix](https://raw.githubusercontent.com/pytorch/pytorch/main/RELEASE.md)
states 2.13 → `>=3.10, <=(3.15, 3.15t experimental)`.

**`requires-python = ">=3.13"` is not a problem, and has headroom to 3.14.** The macOS wheel for
this interpreter is `torch-2.13.0-cp313-cp313-macosx_14_0_arm64.whl`.

Two constraints ride along:

- The platform tag is **`macosx_14_0`** — macOS 14+, and **arm64 only**; there is no macOS x86_64
  torch wheel at all in 2.13.0. This contradicts pytorch.org/get-started's prose ("PyTorch is
  supported on macOS 10.15 (Catalina) or above"), which is stale. Cite the wheel tags.
- torch dropped free-threaded 3.13t builds in 2.13.0 (release notes: *"Stop building CPython 3.13t
  (free-threaded) binaries"*). Irrelevant unless someone tries `3.13t`.

### There is no "CPU-only install" question on macOS — the default *is* CPU/MPS

Every NVIDIA requirement in torch's metadata is marker-gated:
`cuda-toolkit[...]==13.0.3; platform_system == "Linux"`, `nvidia-cudnn-cu13`, `nvidia-nccl-cu13`,
`triton==3.7.1; platform_system == "Linux"`, and so on. **Zero resolve on macOS.** The install matrix
embedded in [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) emits, for
every macOS+CUDA selection, the literal string `# CUDA is not available on MacOS, please use default
package`, and the macOS command is a bare `pip3 install torch torchvision` — **no `--index-url`, no
`+cpu` local version, no custom index.** [uv's PyTorch guide](https://docs.astral.sh/uv/guides/integration/pytorch/)
says the same: PyPI "hosts CPU-only wheels for Windows and macOS", and the recommended pattern falls
back to PyPI on macOS.

**Consequence for `pyproject.toml`:** a bare `torch` in a PEP 735 group resolves correctly on this
machine with no `[tool.uv.sources]`, no `[[tool.uv.index]]`, no marker gymnastics. All the index
configuration seen in PyTorch install guides is Linux/Windows-specific.

MPS is compiled in by default (the wheel ships `torch/backends/mps/`, `c10/metal/*`,
`torch/_inductor/codegen/mps.py`); there is no separate MPS wheel or extra.

### Sizes, measured

| Artifact | Download | Uncompressed |
|---|---|---|
| `torch-2.13.0-cp313-cp313-macosx_14_0_arm64.whl` | **111.2 MB** (106.1 MiB) | **471.0 MB** (449.1 MiB), 12,710 files |
| `torch-2.13.0-cp313-cp313-manylinux_2_28_x86_64.whl` | 526.6 MB | 1095.0 MB |

The 4.7× gap is one file: the Linux wheel carries `libtorch_cuda.so` at 448 MiB. The macOS wheel's
`torch/lib/` contains exactly `libc10`, `libomp`, `libshm`, `libtorch`, `libtorch_cpu`,
`libtorch_global_deps`, `libtorch_python` — no CUDA binary. (Uncompressed figures were read from the
wheels' zip central directories over HTTP range requests; nothing was downloaded or installed.
PyTorch publishes no official installed-footprint number — see [Could not verify](#could-not-verify).)

torch's own dependency tail on macOS is only 9 packages / ~10 MB, of which `sympy` (6.0 MB),
`networkx` (2.0 MB) and `mpmath` (0.6 MB) are 85% — all serving `torch.compile`/FX, dead weight for
inference but not optional. Note torch also puts **`setuptools>=77.0.3` into the runtime environment**.

### The lightest path avoids torch entirely, and by a wide margin

`faster-whisper` 1.2.1 requires **neither torch nor torchaudio** — its runtime is
`ctranslate2>=4.0,<5`, `av>=11`, `onnxruntime`, `huggingface-hub`, `tokenizers`, `tqdm`. The measured
resolve is **24 packages / 61.7 MB**, i.e. **~3× lighter than `openai-whisper`** and less than the
torch wheel alone.

The single most surprising number in this document:
**`ctranslate2-4.8.1-cp313-cp313-macosx_11_0_arm64.whl` is 1.3 MB.** The same version's manylinux
x86_64 wheel is 39.5 MB ([PyPI files](https://pypi.org/pypi/ctranslate2/json)). CTranslate2 on
Apple Silicon links **Apple Accelerate** and **Ruy** rather than bundling MKL/oneDNN
([README key features](https://github.com/OpenNMT/CTranslate2#key-features);
[hardware_support.md](https://github.com/OpenNMT/CTranslate2/blob/master/docs/hardware_support.md)),
so the entire inference engine is a rounding error on disk.

`faster-whisper`'s weight is instead **`av` (18.2 MB) + `onnxruntime` (19.1 MB) = 60% of the
install** — PyAV for audio decoding, ONNX Runtime for the Silero VAD model. Neither is needed for
the way this project would call it (§5, §8), but both are hard requirements of the distribution.

`pywhispercpp` at 9 packages / 16.4 MB is lighter still — it resolves to `numpy`, `requests`,
`tqdm`, `platformdirs` and certs. Prebuilt `cp313-cp313-macosx_11_0_arm64` wheels exist (arm64 only;
no Intel-mac, no universal2), so nothing compiles.

### `torchaudio` is in maintenance and has fallen off the release train

Worth knowing before anyone reaches for it. `torchaudio` is at **2.11.0 (2026-03-23)**; **2.12.0 and
2.13.0 do not exist** (`https://pypi.org/pypi/torchaudio/2.12.0/json` → 404), while `torchvision`
shipped 0.28.0 alongside torch 2.13.0 on the same day. torchaudio has been **removed from the
official install matrix** — every command on pytorch.org/get-started is now `pip3 install torch
torchvision`. Upstream, verbatim:

> "**We have transitioned TorchAudio into a maintenance phase. This process removed some user-facing
> features. These features were deprecated from TorchAudio 2.8 and removed in 2.9.**"
> — [pytorch/audio README](https://github.com/pytorch/audio/blob/main/README.md)

Decoding/encoding migrate to `torchcodec`. None of the four viable runtimes require torchaudio:
`openai-whisper` does not depend on it, `faster-whisper` depends on neither torch nor torchaudio, and
in `transformers` it appears only under the `audio`/`all`/`dev` extras. It is reachable in exactly
one place — the HF ASR pipeline's *resampling* branch (§5) — which this project would never take.

---

## 3. Model identity & pinning

The four runtimes have four genuinely different provenance stories, and only two of them let you
name a commit.

### `openai-whisper` — no Hub, no revision, but a real content hash

Weights come from **`openaipublic.azureedge.net`, not Hugging Face**. The URL *is* the pin: the
sha256 of the checkpoint is the second-to-last path segment, and `_download` verifies it both after
download and on every cache hit
([`whisper/__init__.py`](https://github.com/openai/whisper/blob/main/whisper/__init__.py)):

```python
expected_sha256 = url.split("/")[-2]
...
if hashlib.sha256(model_bytes).hexdigest() == expected_sha256:
    return model_bytes if in_memory else download_target
```

So the identity you can report is `("large-v3-turbo", "aff26ae408abcba5…")`, and the digest is
pinned **by the installed `openai-whisper` version**, not by anything you write. There is no `revision=`
parameter and no repo id. Cache defaults to `~/.cache/whisper` (or `$XDG_CACHE_HOME/whisper`),
overridable per call via `load_model(..., download_root=...)`. There is **no offline env var**, but a
pre-seeded cache directory is fully offline: a hash-matching file short-circuits before any network
call. `torch.load(..., weights_only=True)` is used, so the `.pt` is not an arbitrary pickle.

### `faster-whisper` — full HF revision pinning, but third-party weights

`WhisperModel(size_or_path, revision=..., download_root=..., local_files_only=...)` forwards straight
to `huggingface_hub.snapshot_download`
([`faster_whisper/utils.py`](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/utils.py)),
with `allow_patterns` restricted to `config.json`, `preprocessor_config.json`, `model.bin`,
`tokenizer.json`, `vocabulary.*` — so you fetch only what you need and can pin a commit sha.

The catch is **who published the weights**. `faster-whisper`'s size aliases resolve to:

| Alias | Repo | Repo HEAD sha (today) | Last modified | `model.bin` |
|---|---|---|---|---|
| `large-v3` | `Systran/faster-whisper-large-v3` | `edaa852ec7e145841d8ffdb056a99866b5f0a478` | 2023-11-23 | 3087.3 MB |
| `small` | `Systran/faster-whisper-small` | `536b0662742c02347bc0e980a01041f333bce120` | 2023-11-23 | 483.5 MB |
| `base.en` | `Systran/faster-whisper-base.en` | `3d3d5dee26484f91867d81cb899cfcf72b96be6c` | 2023-11-23 | 145.2 MB |
| `large-v3-turbo` / `turbo` | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` | 2025-11-05 | 1617.9 MB |

(HF API, `?blobs=true`.) These are **CTranslate2 conversions published by SYSTRAN and Mobius Labs —
not artifacts OpenAI ever released.** The provenance chain a report would have to state is
"OpenAI weights → a third party's `ct2-transformers-converter` run → this commit sha", and the
conversion itself is not reproducibly attested anywhere. `Systran/faster-whisper-large-v3`'s
`model.bin` at 3087.3 MB matches `openai/whisper-large-v3`'s fp16 `model.safetensors` at 3087.1 MB,
which is consistent with a straight float16 conversion — but that is size arithmetic, not proof.

The escape hatch is documented: `ct2-transformers-converter --model openai/whisper-large-v3
--output_dir … --quantization float16` converts from the OpenAI repo yourself
([faster-whisper README §Model conversion](https://github.com/SYSTRAN/faster-whisper#model-conversion)).
That trades a third-party artifact for a locally-produced one whose bytes you must then pin yourself.

### `transformers` — the cleanest identity story

`from_pretrained(repo_id, revision=<sha>)` on a **first-party OpenAI repo**. Cache and offline are
fully environment-controlled and documented
([hub env vars](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)):

- `HF_HOME` — root, default `~/.cache/huggingface`
- `HF_HUB_CACHE` — default `$HF_HOME/hub`
- `HF_HUB_OFFLINE=1` — *"no HTTP calls will be made to the Hugging Face Hub… only the cached files
  will be accessed. If no cache file is detected, an error is raised."* Also skips the
  revision-freshness HEAD request that otherwise fires even on a cache hit.

Current first-party shas: `openai/whisper-large-v3-turbo` → `41f01f3fe87f28c78e2fbf8b568835947dd65ed9`
(2024-10-04), `openai/whisper-large-v3` → `06f233fe06e710322aca913c1bc4249a0d71fce1` (2024-08-12),
`openai/whisper-small` → `973afd24965f72e36ca33b3055d56a652f456b4d`.

**One trap worth naming:** repo total ≠ download. `openai/whisper-large-v3-turbo` is 1622.5 MB total
and `model.safetensors` is 1617.8 MB — fine. But `openai/whisper-large-v3` totals **24.7 GB** because
it also carries `flax_model.msgpack`, `pytorch_model.bin`, and two fp32 shard sets; `openai/whisper-small`
totals 3872.9 MB for a 967 MB model because it also ships Flax **and** TensorFlow copies.
`from_pretrained` fetches only the safetensors it needs; a naive `snapshot_download` fetches
everything. That distinction belongs in whatever cache-warming step v0.2 grows.

### `pywhispercpp` — cannot pin, and is behind upstream

Weights come from `https://huggingface.co/ggerganov/whisper.cpp` in the legacy **`ggml`** format
(not GGUF — whisper.cpp checks `GGML_FILE_MAGIC` and the converter writes `0x67676d6c`). The HF repo
is at `5359861c739e955e79d9a303bcbc70fb988958b1`, unchanged since 2024-10-29, so churn risk is low —
but `pywhispercpp` hardcodes `MODELS_PREFIX_URL = "resolve/main/ggml"`
([`constants.py`](https://github.com/absadiki/pywhispercpp/blob/v1.5.0/pywhispercpp/constants.py)),
so **its downloader cannot pin a revision at all**. You would fetch the blob yourself at a pinned sha
and hand `Model()` a file path; `models/README.md` also publishes per-model SHA1s
(`large-v3-turbo` = `4af2b29d7ec73d781377bfd1758ca957a807e941`) to verify against.

Separately, `pywhispercpp` 1.5.0 vendors whisper.cpp at submodule sha
`9386f239401074690479731c1e41683fbbeac557` = tag **v1.8.4** (2026-03-19), while whisper.cpp upstream
is at **v1.9.1** (2026-06-19). **The C++ engine version is not something you can express in
`pyproject.toml`** — you pin `pywhispercpp==1.5.0` and inherit whatever it vendored. For a project
whose entire reproducibility story is "pinned versions + content hashes" (ADR-0005), that is an
opaque link in the chain.

`ggml` f16 sizes: `tiny` 77.7 MB, `base` 148.0 MB, `small` 487.6 MB, `medium` 1533.8 MB,
`large-v3` 3095.0 MB, `large-v3-turbo` 1624.6 MB. The f16 conversion is a **lossless repack** — the
converter never calls `.astype(np.float16)`; OpenAI's `.pt` is already fp16 and 1-D tensors/conv
biases/positional embeddings are *widened* to f32
([`convert-pt-to-ggml.py`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/models/convert-pt-to-ggml.py)),
which is why `ggml-tiny.bin` is slightly larger than `tiny.pt`. The `-q5_0`/`-q5_1`/`-q8_0` variants
are genuinely lossy block quantization and should not be used for a baseline number.

---

## 4. Determinism — what greedy actually buys, and what it does not

### The framework disclaims it, in writing

> "Completely reproducible results are not guaranteed across PyTorch releases, individual commits, or
> different platforms. Furthermore, results may not be reproducible between CPU and GPU executions,
> even when using identical seeds."
> — [torch randomness notes, 2.13](https://docs.pytorch.org/docs/2.13/notes/randomness.html)

**MPS appears zero times on that page**, and zero times on
[`torch.use_deterministic_algorithms`](https://docs.pytorch.org/docs/2.13/generated/torch.use_deterministic_algorithms.html).
The determinism guidance is written entirely for CPU and CUDA/cuDNN. The
[MPS notes page](https://docs.pytorch.org/docs/2.13/notes/mps.html) is two paragraphs and a code
sample: no maturity label, no unsupported-op list, no `PYTORCH_ENABLE_MPS_FALLBACK` mention, no
numerics statement. **Absence of a "beta" label is not a stability guarantee** — it is an absence of
documentation, and should be read that way.

CTranslate2 documents **no** determinism guarantee either; its
[versioning page](https://github.com/OpenNMT/CTranslate2/blob/master/docs/versioning.md) covers API
and converted-model compatibility only, and says other APIs "are expected to evolve to increase
efficiency". A `ctranslate2.set_random_seed` symbol exists. whisper.cpp is likewise **silent**: the
v1.9.1 README contains no hit for `determinis|reproduc|bit-exact|seed`.

**No runtime in this survey documents reproducibility.** The map's "attributed, not reproducible"
framing for transcription is not a concession — it is the only honest position available.

### Temperature 0 is not the default anywhere except `transformers`

This is the finding most likely to bite an implementation that assumes otherwise.

| Runtime | Default decode | Fallback ladder |
|---|---|---|
| `openai-whisper` | `beam_size=None` → greedy | **`temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)`** |
| `faster-whisper` | **`beam_size=5`, `best_of=5`** | **`temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]`** |
| `whisper.cpp` | greedy, `best_of=5` | `temperature=0.0`, **`temperature_inc=0.2`** → same ladder |
| `transformers` (short-form) | `do_sample=False`, `num_beams=1` | **`temperature=None` → none** |

Sources: [`whisper/transcribe.py`](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)
signature; [`faster_whisper/transcribe.py`](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)
`WhisperModel.transcribe` signature; `whisper_full_default_params()` in
[`src/whisper.cpp`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/src/whisper.cpp);
`openai/whisper-large-v3-turbo`'s `generation_config.json`, which sets no `temperature`, `num_beams`
or `do_sample`, leaving `GenerationConfig` defaults.

The ladder is not decoration. When a window trips `compression_ratio_threshold=2.4` or
`logprob_threshold=-1.0`, decoding is **retried at t>0, which engages an RNG**. Passing a scalar
`temperature=0` collapses the ladder in `openai-whisper` and `faster-whisper`; in whisper.cpp the
equivalent is `temperature_inc = 0.0`, which takes the `else` branch and never builds the ladder.
Also note `faster-whisper` defaults to **beam search with beam 5** — its own README flags the
divergence: *"in openai/whisper, `model.transcribe` uses a default beam size of 1 but here we use a
default beam size of 5."* Beam search is deterministic, but it is a *different decode*, so the two
runtimes are not comparable at defaults.

### The good news: v0.1-shaped data sidesteps almost all of it

ADR-0007 sets `duration_max_s = 20.0`. HF's Whisper implementation computes
`is_shortform = total_input_frames <= num_segment_frames` — 3000 frames = **30 s**
([`generation_whisper.py`](https://github.com/huggingface/transformers/blob/main/src/transformers/models/whisper/generation_whisper.py)).
Every Whisper runtime is built on the same 30-second window
(`CHUNK_LENGTH = 30`, `N_SAMPLES = 480000` in
[`whisper/audio.py`](https://github.com/openai/whisper/blob/main/whisper/audio.py)).

**A prompted utterance under the default duration ceiling is a single window.** The long-form
machinery — sequential window stitching, `condition_on_previous_text` carrying one window's output
into the next, `prompt_reset_on_temperature` — is *inert*. What remains live is the within-window
temperature fallback, which the runtime's own `DecodingResult.temperature` field reports, so a run
that fell back is detectable rather than silent.

**Two caveats, stated precisely:**

1. `duration_out_of_range` is a **soft flag, not a rejection** (ADR-0005, ADR-0007) — an over-length
   recording is *included and flagged*. And `duration_max_s` is a config knob, not a constant. A
   dataset built with `duration_max_s = 45`, or containing a flagged 40-second outlier, re-enters the
   long-form path and the reproducibility story changes underneath the report. Whatever v0.2 does
   here should be a checked property, not an assumption.
2. Short-form is only *sufficient* for determinism if the fallback ladder is also disabled. They are
   independent knobs.

### Residual variance that greedy does not remove

- **Thread count changes results.** `faster-whisper`'s README says *"When running on CPU, make sure to
  set the same number of threads"* and points at `OMP_NUM_THREADS`; `WhisperModel(cpu_threads=…)`
  overrides it. whisper.cpp defaults `n_threads = min(4, hardware_concurrency())` — i.e. **the default
  varies with the machine**. Floating-point reductions are order-dependent; thread count changes the
  order.
- **Compute type is silently rewritten on Apple Silicon.** CTranslate2's implicit-conversion table
  ([quantization.md](https://github.com/OpenNMT/CTranslate2/blob/master/docs/quantization.md)) maps,
  for `AArch64/ARM64 (Apple)`: `float16 → float32`, `int16 → int8_float32`, `int8_float16 →
  int8_float32`. The SYSTRAN models are float16 on disk, so `compute_type="default"` on this machine
  **upconverts to float32 at load** — roughly 6 GB resident for `large-v3`. The effective compute type
  is a property of the host, not the config, and belongs in the provenance record.
- **Backend divergence is undocumented everywhere.** whisper.cpp defaults `use_gpu=true` and
  `flash_attn=true` on Apple Silicon (Metal + Accelerate are CMake defaults under `if (APPLE)`), and
  makes no claim that Metal and CPU agree. torch makes the opposite claim explicitly — that CPU and
  GPU *may not* agree.
- **A source-read hazard in whisper.cpp, flagged as unverified:** `state->decoders[0].rng =
  std::mt19937(0)` runs once at state init, while the per-call reseed loop starts at `j = 1`. Decoder
  0's RNG state therefore appears to carry across successive `whisper_full()` calls on one context,
  which would make a fallback-triggering segment transcribe differently on a second call in the same
  process. This is a reading of the source, not documented behavior, and was not executed.

---

## 5. Audio input contract — v0.1's Normalized output, tested

**The v0.1 claim holds, and this is the first time it has been checked.**

All four runtimes converge on the same in-memory contract: **mono, 16 kHz, float32, nominally
[-1, 1]**.

- `openai-whisper`: `SAMPLE_RATE = 16000`; `transcribe(model, audio: Union[str, np.ndarray, torch.Tensor])`.
- `faster-whisper`: `if not isinstance(audio, np.ndarray): audio = decode_audio(audio, sampling_rate=...)`
  — an ndarray goes straight through.
- `transformers`: `preprocessor_config.json` for every Whisper checkpoint has `"sampling_rate": 16000`;
  the pipeline accepts `np.ndarray` directly and only touches a resampler when handed a `dict` whose
  `sampling_rate` differs.
- whisper.cpp: `WHISPER_SAMPLE_RATE = 16000` and `whisper_full(ctx, params, const float * samples,
  int n_samples)`. `pywhispercpp`'s own `.wav` loader *rejects* non-16 kHz (`"WAV file must be 16000
  Hz"`) and non-16-bit input — it will not resample for you.

And the numeric convention is identical across the board. `openai-whisper`'s ffmpeg path ends
`np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0`; `faster-whisper`'s PyAV path
ends `audio.astype(np.float32) / 32768.0`.

**Verified locally** (`soundfile` 0.14.0 / libsndfile 1.2.2, the versions this repo already pins),
on a mono 16 kHz `PCM_16` WAV written exactly as ADR-0005 specifies:

```
int16 roundtrip exact:                 True
float32 == int16/32768 exactly:        True
float64 == int16/32768 exactly:        True
max |float32 - int16/32768|:           0.0
```

So `soundfile.read(path, dtype="float32")` on a v0.1 Normalized WAV produces **bit-identical values
to what every runtime's own decoder would produce from the same file**. Range is `[-1, 1)`
(min exactly `-1.0`, max `0.99990845`). No resampling, no downmix, no scaling, no conversion loss.

### But feeding it *directly* means feeding the array, not the path

This is the part v0.1's claim glossed. **The path-based entry points all route through FFmpeg:**

- `whisper.load_audio` shells out to the **`ffmpeg` CLI** — *"Requires the ffmpeg CLI in PATH"* — and
  the README instructs `brew install ffmpeg`.
- The HF ASR pipeline calls `ffmpeg_read(...)` for `str`/`bytes` inputs.
- `pywhispercpp` shells out to `ffmpeg -i … -ac 1 -ar 16000` for anything that is not a conforming
  `.wav`.

**ADR-0005 chose WAV-only specifically to keep the stack "Zero ffmpeg / PyAV."** Handing the array
rather than the path preserves that at the *API* level for all four runtimes. It does **not** preserve
it at the *install* level for `faster-whisper`: `av>=11` is a hard requirement, and PyAV's wheels
*"are provided on PyPI for Linux, macOS, and Windows with FFmpeg bundled"*
([PyAV README](https://github.com/PyAV-Org/PyAV/blob/main/README.md)) — 18.2 MB of vendored FFmpeg 8.x
shared libraries land in the venv whether or not a single frame is ever decoded through them. See §6
for why that is also a licensing question.

### Two contract details that are not obvious

- **Every runtime zero-pads to 30 seconds.** `pad_or_trim` to `N_SAMPLES = 480000`. A 2-second prompted
  utterance is presented to the encoder as 2 s of speech and 28 s of digital silence. That is the exact
  regime `no_speech_threshold=0.6` and Whisper's hallucination behavior live in, and it applies to
  *every* sample this project will ever evaluate. Not a defect — but the padding is not neutral, and
  a baseline that never says so is under-reporting its own conditions.
- **dtype matters.** Pass `float32`. `soundfile`'s default `dtype` is `float64`; the extra precision
  buys nothing and each runtime will cast it anyway.

---

## 6. Licensing

### Runtimes

| Package | License | Source |
|---|---|---|
| `openai-whisper` | MIT | [PyPI](https://pypi.org/pypi/openai-whisper/json) |
| `faster-whisper` | MIT | [PyPI](https://pypi.org/pypi/faster-whisper/json) |
| `ctranslate2` | MIT | [PyPI](https://pypi.org/pypi/ctranslate2/json) |
| `onnxruntime` | MIT | [PyPI](https://pypi.org/pypi/onnxruntime/json) |
| `av` (PyAV bindings) | BSD-3-Clause | [PyPI](https://pypi.org/pypi/av/json) |
| `transformers` | Apache-2.0 | [PyPI](https://pypi.org/pypi/transformers/json) |
| `huggingface-hub` | Apache-2.0 | [PyPI](https://pypi.org/pypi/huggingface-hub/json) |
| `torch` | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT` | [PyPI `license_expression`](https://pypi.org/pypi/torch/json) |
| `numba` / `llvmlite` | BSD | [PyPI](https://pypi.org/pypi/numba/json) |
| whisper.cpp | MIT (`Copyright (c) 2023-2026 The ggml authors`) | [LICENSE](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/LICENSE) |
| `pywhispercpp` | MIT | [PyPI](https://pypi.org/pypi/pywhispercpp/json) |
| `nemo_toolkit` | Apache-2.0 | [PyPI](https://pypi.org/pypi/nemo_toolkit/json) |

Nothing here is more restrictive than the LGPL this project already accepted for libsndfile/libsoxr —
**except possibly the FFmpeg vendored inside `av`**, which is flagged below and is genuinely open.

### Weights — and a conflict worth flagging

The [openai/whisper README](https://github.com/openai/whisper/blob/main/README.md) states plainly:

> "Whisper's code and model weights are released under the MIT License."

**The HF model cards do not agree.** Front-matter, read from each card's raw markdown today:

| Repo | `license:` |
|---|---|
| `openai/whisper-large-v3-turbo` | **mit** |
| `openai/whisper-large-v3` | **apache-2.0** |
| `openai/whisper-small` | **apache-2.0** |
| `openai/whisper-base.en` | **apache-2.0** |
| `Systran/faster-whisper-*` | mit |
| `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | mit |
| `ggerganov/whisper.cpp` | mit |

Both are OpenAI-published statements, and they contradict each other for every checkpoint except
`large-v3-turbo`. Neither license is restrictive for this project's purposes, so this is a
*reporting* problem rather than a blocking one: whatever provenance record v0.2 emits should carry
the license **as declared by the artifact it actually fetched**, not a project-wide constant asserted
once. Picking `large-v3-turbo` happens to make the conflict disappear.

Non-Whisper weights, for completeness: `nvidia/parakeet-tdt-0.6b-v2` and `-v3` are **CC-BY-4.0**;
`nvidia/parakeet-unified-en-0.6b` is under the **NVIDIA Open Model License**;
`facebook/wav2vec2-base-960h` is Apache-2.0; **`facebook/mms-1b-all` is CC-BY-NC-4.0 — non-commercial**.

### The one unresolved licensing question: FFmpeg inside PyAV

PyAV's wheels bundle FFmpeg 8.x built by [pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg).
That build passes `--enable-version3` and, on arm64, `--enable-libx264 --enable-libx265`
([`scripts/build-ffmpeg.py`](https://github.com/PyAV-Org/pyav-ffmpeg/blob/main/scripts/build-ffmpeg.py)).
x264 and x265 are GPL codecs and FFmpeg's own `configure` refuses them without `--enable-gpl`, which
implies a **GPL-configured FFmpeg shipping inside the venv**. But I could find no `--enable-gpl` in
either `build-ffmpeg.py` or `cibuildpkg.py`, and pyav-ffmpeg publishes **no license statement at
all**. Marked **could not verify** — and it matters, because ADR-0005 accepted LGPL deliberately and
said nothing about GPL. It is a genuine input to the `faster-whisper` decision, since `av` is
non-optional there.

---

## 7. Is "Whisper" still the right assumption?

The map inherited Whisper rather than choosing it. The honest answer is: **Whisper is no longer the
accuracy leader, but it is still the best-supported thing on this platform, and the alternatives cost
more than they look.**

Evidence, from the Open ASR Leaderboard's results CSV
([`hf-audio/open-asr-leaderboard-results`, `english_short_latest.csv`](https://huggingface.co/datasets/hf-audio/open-asr-leaderboard-results/raw/main/english_short_latest.csv),
91 rows) — average WER on cleaned English short-form, open-licensed entries only:

| Avg WER | Model | License | Params (B) | RTFx |
|---|---|---|---|---|
| 4.901 | `ibm-granite/granite-speech-4.1-2b` | apache-2.0 | 2 | 547 |
| 4.990 | `Qwen/Qwen3-ASR-1.7B-hf` | apache-2.0 | 2.04 | 796 |
| 5.064 | `nvidia/canary-qwen-2.5b` | cc-by-4.0 | 2.5 | 861 |
| 5.393 | `nvidia/parakeet-tdt-0.6b-v2` | cc-by-4.0 | 0.6 | **6038** |
| 5.661 | `nvidia/parakeet-tdt-0.6b-v3` | cc-by-4.0 | 0.6 | **6098** |
| 13.474 | `facebook/mms-1b-all` | cc-by-nc-4.0 | 0.96 | 1954 |
| 20.490 | `facebook/wav2vec2-base-960h` | apache-2.0 | 0.09 | 3366 |

(The License column is submitter-reported; the NVIDIA/Meta/IBM/Qwen rows were cross-checked against
their model cards. Leaderboard numbers are measured on NVIDIA GPUs and say nothing about macOS.)

**wav2vec2 and MMS are not viable baselines for *this* project**, and the reason is textual, not
accuracy. `facebook/wav2vec2-base-960h`'s `vocab.json` is 32 tokens —
`<pad> <s> </s> <unk> | E T A O N I H S R D L U M W C F G Y P B V K ' X J Q Z` — i.e. **uppercase
letters, apostrophe, and a word delimiter. No lowercase, no punctuation, no digits.** MMS's `eng`
vocab is lowercase-only. Both force a normalization scheme onto the scoring stage before a number
exists at all, which is precisely the argument the map is trying to keep *downstream* of the
hypothesis artifact.

**Parakeet TDT is the one serious non-Whisper contender**, and §1's NeMo verdict does not rule it out,
because you do not need NeMo to run it:

- `transformers` gained first-party `ParakeetForCTC` / `ParakeetForRNNT` / `ParakeetForTDT` on
  **2025-09-25** ([model doc](https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/parakeet.md)),
  and the TDT example names `nvidia/parakeet-tdt-0.6b-v3` directly through the ordinary
  `pipeline("automatic-speech-recognition", ...)`. That repo is tagged `library_name: transformers`
  and ships `model.safetensors` (2508.3 MB), sha `7c35754d166cca382ad1e53e68b01e7c575f3a1d`.
  **`-v2` ships only the `.nemo` file** — the transformers route needs v3.
- Its input contract matches ours exactly: *"Input Type(s): 16kHz Audio / Input Format(s): `.wav` and
  `.flac` … Monochannel audio"*, and its output includes *"Punctuations and Capitalizations"*
  ([v2 card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2/raw/main/README.md)).
- **It has no sampling machinery at all.** The transformers doc describes "Greedy CTC decoding for
  inference" and "Greedy transducer decoding for inference". There is no temperature ladder, no
  beam-vs-greedy default mismatch, no `condition_on_previous_text`. On the determinism axis it is
  strictly simpler than Whisper.
- Lighter runtimes exist: `onnx-asr` 0.12.0 (MIT, classifiers list 3.13 and 3.14, deps are numpy +
  onnxruntime only) and `parakeet-mlx` 0.5.2 (Apache-2.0, Apple-native via `mlx`). Both consume
  **community** exports, not NVIDIA-official ones.

Against it: the model cards say *"Our AI models are designed and/or optimized to run on NVIDIA
GPU-accelerated systems"* and list Linux as the only supported OS. **No primary source claims
Parakeet runs on macOS or CPU** — not forbidden, just unclaimed and unmeasured.

Bottom line for [#131](https://github.com/andrewferk/speech-dataset-workbench/issues/131): Whisper
remains the defensible default — it is the only family with three independent, macOS-native, py3.13
runtimes and first-party weights. Parakeet TDT via `transformers` is the credible alternative and
should be *named and rejected on the record* rather than never considered, because "we inherited
Whisper" is not a decision.

---

## 8. What this research would recommend

**`faster-whisper` (CTranslate2), CPU, `compute_type` stated explicitly, `temperature=0`,
`beam_size` chosen deliberately, weights pinned by HF commit sha.**

Five reasons, in order of weight:

1. **It is the only viable runtime that does not require torch.** 24 packages / 61.7 MB against
   `openai-whisper`'s 23 / 181.5 MB and `transformers[torch]`'s 36 / 156.7 MB. For
   [#137](https://github.com/andrewferk/speech-dataset-workbench/issues/137), an optional extra that
   does not drag a 471 MB unpacked deep-learning framework into the venv is a materially different
   packaging decision — and it makes the "CI tests the scoring path with no torch" property in the
   map trivially true rather than carefully arranged.
2. **The engine is 1.3 MB on this platform.** Apple Accelerate + Ruy, no bundled BLAS. The install is
   dominated by two dependencies (`av`, `onnxruntime`) that serve features we would not use.
3. **Revision pinning is a first-class parameter** — `revision=`, `download_root=`,
   `local_files_only=` all forward to `huggingface_hub`, so the provenance stamp the map requires is
   a constructor argument, not a workaround.
4. **CPU is the supported path, not a degraded one.** No MPS, therefore no reliance on a backend
   PyTorch's own determinism documentation does not mention.
5. It is maintained (1.2.1, 2025-10-31) and its README is unusually candid about the ways two Whisper
   implementations fail to be comparable.

**The cost, stated plainly:** the default weights are **third-party conversions** (SYSTRAN /
Mobius Labs), which is a real step down in provenance from `transformers` + `openai/*`, and the
`av`/FFmpeg licensing question in §6 is unresolved. If either of those is judged disqualifying, the
fallback is **`transformers` + `openai/whisper-large-v3-turbo` pinned by sha** — best-in-class
identity, true greedy short-form decoding by default, first-party weights, `HF_HUB_OFFLINE` — at the
price of torch.

**`openai-whisper` should not be chosen.** It is the heaviest install, 40.5 MB of it is `llvmlite`
for a feature we do not want, its weights cannot be pinned by anything but the library version, its
loader requires a system `ffmpeg` binary that ADR-0005 deliberately eliminated, it has not shipped in
thirteen months, and its own README does not claim to support this Python.

**`pywhispercpp` is the interesting outlier** — 16.4 MB, no torch, Metal for free — and is
disqualified on provenance, not weight: its downloader hardcodes `main` and cannot pin a revision, and
the whisper.cpp engine version is invisible to `pyproject.toml`. For a project whose reproducibility
rests on pinned versions, an unpinnable C++ engine is the wrong trade.

---

## Could not verify

Listed rather than smoothed over.

- **Whether the FFmpeg bundled in PyAV's wheels is GPL-configured.** `--enable-libx264
  --enable-libx265` plus `--enable-version3` are in the build script and normally require
  `--enable-gpl`, but that flag is absent from both `build-ffmpeg.py` and `cibuildpkg.py`, and
  pyav-ffmpeg publishes no license statement. This is the one open item with a real decision attached.
- **Whether `nemo_toolkit[asr]` actually installs end-to-end on macOS arm64 / py3.13.** The resolve
  succeeds; the seven source builds were not attempted. `lightning==2.4.0` (Aug 2024) declares no
  3.13 classifier and `hydra-core==1.3.2` stops at 3.11 — both pure-Python, so they will install;
  whether they *run* on 3.13 is unconfirmed.
- **torch's installed-on-disk footprint is not published by PyTorch.** The 471 MB figure is read from
  the official wheel's zip central directory; `__pycache__` generated at first import is additional
  and unquantified. Download size is a floor, not an estimate.
- **Whether the SYSTRAN CT2 conversions are faithful float16 conversions of the OpenAI weights.**
  `model.bin` at 3087.3 MB vs `model.safetensors` at 3087.1 MB is consistent with it. That is size
  arithmetic, not verification.
- **Whether `pywhispercpp`'s published arm64 wheel links Metal/Accelerate at runtime.** Inferred from
  its CI config (`macos-14` runner, `-DGGML_NATIVE=OFF`) plus ggml's `if (APPLE)` CMake defaults
  (`GGML_METAL_DEFAULT ON`, `GGML_BLAS_DEFAULT ON`, `GGML_METAL_EMBED_LIBRARY`). The wheel was not
  inspected.
- **The whisper.cpp decoder-0 RNG carryover** described in §4 is a source reading, not observed
  behavior, and not documented upstream.
- **Whether Metal and CPU backends produce identical transcripts** in whisper.cpp — no upstream
  statement either way, and no run was made.
- **Whether Parakeet runs usably on macOS CPU or MPS.** No primary source claims it; NVIDIA's cards
  claim the opposite environment.
- **Every WER number in §7 is leaderboard-reported**, measured on NVIDIA GPUs by third parties, and
  none of it was reproduced here. Treat it as ordering, not as measurement.
- **`torchaudio` 2.11.0 declares `requires_dist: null`** — no dependencies at all, not even torch.
  This was read from PyPI's derived field rather than the wheel's raw `METADATA`. If it is accurate,
  uv will resolve `torchaudio` without torch and fail at import; pin both if it is ever used.

---

## Open sub-choices handed to #131 / #137

This research deliberately does not make these calls.

### To [#131 — ASR backend, model selection & pinning](https://github.com/andrewferk/speech-dataset-workbench/issues/131)

1. **Runtime.** `faster-whisper` (§8's recommendation) vs `transformers` + first-party weights. The
   trade is *dependency weight and a torch-free CI path* against *first-party provenance and a
   documented offline mode*. Both are defensible; this research has a preference, not a mandate.
2. **Model size, and whether one or several.** `large-v3-turbo` (1.6 GB) vs `small` (0.5 GB) vs
   `base.en` (0.15 GB). This is a wall-clock and disk decision on a laptop, and nothing here measured
   either — no weights were downloaded and no inference was run.
3. **Whether to accept third-party CT2 conversions or run `ct2-transformers-converter` locally.**
   Local conversion buys provenance and costs a build step, a torch install at conversion time, and a
   locally-produced artifact whose bytes you must then pin yourself.
4. **Decode parameters as a fixed constant set.** At minimum: scalar `temperature=0` (collapsing the
   fallback ladder), an explicit `beam_size` (the two runtimes disagree at defaults — 1 vs 5),
   `condition_on_previous_text`, `vad_filter`, `word_timestamps`, `initial_prompt`. ADR-0005's
   "no config knobs, hard-coded constants" posture is the obvious precedent; whether decode params
   deserve the same treatment or belong in the hashed config block is #131's to settle.
5. **What the provenance record contains, and its exact shape.** Candidates surfaced here that a
   naive record would miss: the *effective* compute type after CTranslate2's implicit conversion
   (float16 → float32 on Apple arm64), the thread count, the license **as declared by the fetched
   artifact** rather than as a project constant, and — if `pywhispercpp` were ever chosen — the
   vendored whisper.cpp version, which cannot be read from `pyproject.toml`.
6. **Whether to name and reject Parakeet TDT on the record.** §7 argues it deserves an explicit
   rejection rather than silent omission, since "Whisper" is inherited. Whether that belongs in an ADR
   is #131's call.
7. **Accelerator policy.** The map lists this as fog. This research supplies one input: PyTorch's
   determinism documentation does not mention MPS at all, and its MPS page carries no maturity label.
   CPU-only is the position that needs no disclosure.
8. **Whether "short-form only" becomes a checked property.** §4's determinism argument depends on
   every sample being ≤30 s, which the *default* `duration_max_s = 20.0` gives — but that is a config
   knob and `duration_out_of_range` is a soft flag, so an over-length sample is included, not
   rejected. Asserting it, warning on it, or ignoring it is a decision.

### To [#137 — Packaging, optional dependencies & the import boundary](https://github.com/andrewferk/speech-dataset-workbench/issues/137)

1. **Optional extra vs PEP 735 dependency group.** The repo has `[dependency-groups] dev` already but
   no `[project.optional-dependencies]`. An extra is installable by a downstream consumer
   (`pip install sdw[asr]`); a group is not. Which the eval path deserves depends on whether `sdw` is
   ever installed by anyone but its author.
2. **Whether `torch` ever enters the lockfile at all.** This is the single largest packaging
   consequence of #131's runtime choice: 111.2 MB download / ~471 MB unpacked, plus `setuptools`,
   `sympy`, `networkx` and `mpmath` in the runtime environment. Picking `faster-whisper` means CI's
   torch-free scoring path is a property of the dependency graph rather than of test discipline.
3. **Whether `uv.lock` carries the ASR deps.** ADR-0010 ties `tool_version` bumps to lock changes by
   convention; adding a large optional stack to the lock changes how often that fires, and for reasons
   that cannot affect `dataset_version`.
4. **Where model weights and the HF cache live, and who sets it.** `HF_HOME` / `HF_HUB_CACHE` /
   `HF_HUB_OFFLINE` for the Hub-based runtimes; `download_root` for `openai-whisper`. This interacts
   with the map's "captured audio and sensitive metadata never enter git" preference and with whatever
   `examples/` ends up doing — 1.6 GB in `~/.cache` is invisible to `.gitignore` but very visible to a
   contributor.
5. **How the import boundary is *enforced*.** ADR-0012's unwritable-recomputation trick is the named
   precedent. What it has to enforce is now concrete: `sdw.pipeline` must not import
   `faster_whisper` / `ctranslate2` / `transformers` / `torch`, and the eval path must not import
   `sdw.manifest`. Whether that is a test, a lint rule, or a package-layout property is #137's call.
6. **Whether the eval extra is macOS-arm64-only in practice, and whether that is stated.** Nothing here
   needs a custom index on macOS — but `torch` on Linux pulls `cuda-toolkit`, `nvidia-cudnn-cu13`,
   `nvidia-nccl-cu13` and `triton` by default, so a CI matrix that adds Linux gets a very different
   install unless it is pinned to the CPU index. `faster-whisper` sidesteps this entirely.
7. **The unresolved PyAV/FFmpeg licensing question (§6)**, if `faster-whisper` is chosen. `av` is
   non-optional there, and ADR-0005 accepted LGPL explicitly while saying nothing about GPL. Resolving
   it may require reading the shipped binaries rather than the build scripts.
