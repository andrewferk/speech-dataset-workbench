# Packaging, optional dependencies & the import boundary (v0.2)

The map's founding claim about v0.2 is that isolation is **structural, not aspirational**: `sdw.pipeline`
imports nothing from the eval path, the ASR dependencies sit behind an optional extra, and the
evaluator reads the emitted JSONL **like a stranger**. ADR-0017 then made one half of that an
executable demonstration — `sdw score` in a venv without the extra — and handed the rest here.

This ADR fixes the mechanics: how the ASR dependencies are packaged, how the module tree is split so
the dependency split and the module split are the same line, what happens when the deps are absent,
how the two boundaries that **cannot** be made structural are checked instead, and what CI installs.
It resolves #137.

It builds on ADR-0012 (a structural impossibility beats a test that merely passes; a checklist
mirroring a set of documents is a second source of truth), ADR-0014 (the build backend, the `sdw`
entry point, and the smoke step that runs it from outside the checkout), ADR-0016 (`transformers` +
torch; `HF_HOME`/`HF_HUB_CACHE` respected and nothing set), ADR-0017 (two commands; `score` never
opens the dataset and imports nothing from `sdw.manifest`/`sdw.provenance`; structural aborts move in
front of the model load), ADR-0018 (`regex` and `more_itertools` join the **base** dependencies for
the vendored Tier B normalizer), ADR-0019 (the eval path **does** import `sdw.serialization`, and that
does not weaken the boundary) and ADR-0020 (`run.json` records resolved library versions).

It **amends ADR-0014 in place**, whose smoke step now carries a property it was not written for.

Two of the ticket's five questions arrived already answered and are restated rather than reopened:
there is no `sdw evaluate` — ADR-0017 split it into `transcribe` and `score`, and the graceful-absence
question is therefore about `transcribe` alone — and the PyAV/FFmpeg GPL question #127 raised is
**dead, not deferred**, since it existed only under `faster-whisper`, which ADR-0016 did not adopt.

## Decisions

### `asr` is a PEP 621 extra, and the dependency group was never a candidate

```toml
[project.optional-dependencies]
asr = ["transformers>=5", "torch>=2.13"]
```

#137 asked which of a PEP 735 dependency group, a PEP 621 optional-dependency extra, or a separate
distribution is right *here*, noting the repo currently uses both PEPs. The question resolves on
mechanics rather than judgement, and the mechanics are worth writing down because the two PEPs look
interchangeable in a `pyproject.toml` and are not.

**PEP 735 dependency groups are never published in distribution metadata.** They exist in the source
`pyproject.toml` and are reachable by tools operating on the local project — `uv sync --group`,
`uv run --group`, `pip install --group` against a directory. Nothing in a built wheel or sdist
records them, so there is no way for a consumer who has only `sdw` from an index to ask for one.
`pip install 'sdw[asr]'` is, definitionally, an **extra**.

So the repo keeps using both, for the two different jobs they solve, and the existing usage is
already correct: `[dependency-groups] dev` holds tooling that only ever runs against a checkout and
should never be installable by a consumer, while `[project.optional-dependencies] asr` holds
runtime deps a consumer must be able to opt into. Recording this is the point — a future reader
looking at `dev` as a group and `asr` as an extra will otherwise read the inconsistency as an
oversight and "fix" it in whichever direction they noticed first.

**A separate distribution** (`sdw-asr`, depending on `sdw`) is rejected. It buys the same install
lean-ness at the cost of a second version number, a second release step, and a cross-distribution
version-compatibility question that an extra does not have — and its one genuine advantage, that
the ASR code could not physically be imported from `sdw.pipeline`, is not available anyway: the
boundary that most needs enforcing runs the *other* way (the evaluator must not import
`sdw.manifest`), and a separate distribution makes that direction **easier**, not harder.

The extra is named `asr` rather than `transcribe`. Under the module split below it maps 1:1 onto a
command, so `[transcribe]` would let the pair read off the command names — but the extra names the
**capability** being added rather than the command that happens to consume it today, and
`pip install 'sdw[asr]'` tells a stranger what they are about to download in a way `[transcribe]`
does not. This is the weakest call in this ADR and nothing depends on it.

### Two subpackages, drawn on the dependency line — not one `sdw/eval/`

```
src/sdw/transcribe/     # requires the asr extra
src/sdw/score/          # base dependencies only
```

`src/sdw/` has been seventeen flat modules since v0.1. These are the first subpackages, and the
nesting is not an aesthetic preference — it is the only layout in which the ticket's own constraint
holds.

The constraint is that **the module split must match the dependency split**, because ADR-0017's
demonstration (`sdw score` in a venv with no torch) is a claim about which modules import what. The
layout that looks tidiest fails it: a single `sdw/eval/` package matches ADR-0015's vocabulary,
where Evaluation *is* both halves — and puts the torch line **inside** the package, so the package
boundary and the dependency boundary are different lines and neither implies the other. Splitting on
the command names instead puts the dependency line exactly on a package boundary.

That is what makes the enforcement rules below expressible over module **prefixes** rather than a
hand-maintained list of module names — ADR-0010's objection to enumerated lists ("a hand-maintained
list that rots"), applied to the check itself. It also dissolves the module-versus-package question:
because the rules are phrased over prefixes, `sdw.transcribe` may be one module today and a package
tomorrow without the check changing a line. And it survives `score` being genuinely large — Tier A,
ADR-0018's ~630 vendored Tier B lines, the Levenshtein scorer, the metrics, the five Breakdowns and
ADR-0022's two renderings are not one file, so "flat" was never going to stay flat. It was going to
be roughly eight more modules in a seventeen-module directory with the boundary maintained as a
naming convention, which is the failure mode ADR-0014 spent an ADR removing in a different guise.

### `sdw.cli` imports no command module at module level

Today `cli.py` opens with `from sdw import pipeline`, and `_parser()` builds the whole subcommand
table before any dispatch. Left as-is with `transcribe` added, `sdw --help` would import torch, and
`sdw score` would fail to start in the venv that is supposed to prove it does not need it.

The obvious repair is one lazy import inside the `transcribe` branch, with a comment explaining why
that branch is special. **A special case with a comment explaining it is the thing that gets tidied
away.** So the rule is uniform instead: `sdw.cli` imports **no** command module at module level —
`pipeline`, `transcribe` and `score` are each imported inside their own dispatch branch, and none is
an exception to anything.

This touches working `build`/`validate` code for a reason that originates with `transcribe`, and
that cost is accepted. What it buys is that the rule has no exception to erode, the check that
enforces it is simpler rather than more complex, and `sdw --help` becomes cheap for every command
rather than for three out of four.

Consequences that fall out for free, and are therefore *not* separate decisions: `sdw --help` lists
all four commands in a venv with no ASR extra, `sdw transcribe --help` prints its usage there too,
and `sdw score` starts without importing anything from `sdw.transcribe`.

### Absence is probed, never caught

`sdw transcribe` in a venv without the extra raises a `HardError` — ADR-0017's exit-1 path — naming
the install:

```
error: sdw transcribe needs the ASR extra, which is not installed.
       uv sync --extra asr        (in a checkout)
       pip install 'sdw[asr]'     (installed)
```

The detection is an explicit `importlib.util.find_spec` probe over **every** name the extra
provides, before importing anything from `sdw.transcribe`.

The cheaper version — wrap the dispatch import in `try: … except ImportError:` and print the same
message — is rejected because it conflates two different facts. A typo'd internal module name inside
`sdw.transcribe` is an `ImportError` too, and it would be reported to the operator as *"install the
ASR extra"*: a confident diagnosis pointing at the one thing that is not wrong. Under the probe, a
genuine internal `ImportError` propagates as a traceback, which is correct, because it is a bug and
not an operator problem. This is the same distinction ADR-0017 drew between an empty Hypothesis and
a crashed decode, and the same shape as ADR-0019's refusal to encode one fact two ways.

Probing every name rather than one sentinel means a half-installed venv is diagnosed as a missing
extra rather than crashing partway through the import with whichever name happened to be absent.

The probe is the **earliest** preflight — ahead of argument validation, and far ahead of ADR-0017's
structural aborts, which are themselves in front of the model load. It costs nothing, because
`find_spec` locates a module without executing it.

### Three rules, and exactly one of them is already structural

The map asks for two boundaries; ADR-0017 adds the torch-free demonstration. As three rules over
module prefixes:

1. `sdw.pipeline`'s transitive closure imports nothing under `sdw.transcribe` or `sdw.score`.
2. `sdw.score` imports nothing under `sdw.transcribe`.
3. Neither `sdw.transcribe` nor `sdw.score` imports `sdw.manifest` or `sdw.provenance`, at any
   depth. `sdw.serialization` is explicitly permitted (ADR-0019).

**Rule 2 is already structural and free.** The `check` CI job installs no extra, so the moment
#138's Scoring goldens run there, a module-level `import torch` anywhere under `sdw.score` is an
`ImportError` and the whole suite is red. Nothing needs to be written to enforce it. What needs
writing down is the **property of the CI shape** that supplies it, so that nobody later adds
`--extra asr` to the `check` job as a convenience and silently deletes the guarantee — see below.

**Rules 1 and 3 cannot be made structural, and this is worth being explicit about**, because
ADR-0012's bar is a structural impossibility and this ADR does not clear it twice. `sdw.pipeline`
importing `sdw.score.metrics`, and `sdw.transcribe` importing `sdw.manifest.SPLIT_ORDER`, are both
same-distribution, zero-dependency imports that would work perfectly and break nothing at runtime.
There is no dependency graph to make them impossible; the separate-distribution option above would
have made rule 1 structural and rule 3 *easier* to violate. These are precisely the map's "one
careless import away, and the whole manifest-contract dogfood dies silently" cases, so they get a
check — ADR-0012's bar met one notch below its ideal, because for these two rules there is no notch
above.

### The check is ours: an AST import graph, run under `pytest`

A test under `tests/unit/` parses every module under `src/sdw/` with `ast`, builds the intra-package
edge set **tagged by node depth** — module-level import versus an import nested inside a function or
method — computes reachability, and asserts the three rules. A violation reports the *path*
(`sdw.pipeline → sdw.staging → sdw.score.metrics`), not merely the fact.

Writing import-graph analysis by hand when a maintained tool exists needs a reason, and there is
one. **`import-linter` cannot express the rule this ADR just created.** It works at module
granularity and treats a module-level import and a function-body import as the same edge, so it
cannot forbid `sdw.cli → sdw.transcribe` at the top of the file while permitting it inside the
dispatch branch — and that distinction *is* the mechanism keeping `--help` alive in a torch-free
venv. It would also live in configuration that `pytest` does not run, so the loudest signal a
contributor gets locally would not carry it.

**A subprocess `sys.modules` assertion** — import `sdw.pipeline` in a fresh interpreter, dump
`sys.modules`, assert no forbidden prefix appears — is about fifteen lines, transitive by
construction, and catches computed imports the AST cannot see. It is rejected because it is blind to
exactly the pattern this ADR blesses: once function-body imports are sanctioned in `cli.py`, a
second one anywhere else is invisible to a runtime check, and rule 3's most likely violation is a
convenience import reached for inside a function.

The AST check runs under plain `pytest`, so it is loud in the place a contributor looks first rather
than only in CI.

### CI is three jobs, and `check` may never gain the extra

| Job | Installs | Runs |
| --- | --- | --- |
| `mise-config` | — | `mise ls` (unchanged) |
| `check` | `uv sync --locked` | the `sdw --help` smoke, `ruff`, `pytest` |
| `asr` | `uv sync --locked --extra asr` | `mypy --strict` |

**`check` installs no extra, and that is load-bearing rather than incidental.** It is what supplies
rule 2 above, and what makes ADR-0017's demonstration a fact about the repository rather than a
sentence in an ADR. Adding `--extra asr` to it would cost nothing visible on the day and would
delete the guarantee silently — `sdw.score` could grow a top-level `import torch` and CI would stay
green. This paragraph exists so that change cannot be made without reading why it must not be.

What the `asr` job runs beyond `mypy --strict` — whether any test exercises a real decode, and
whether weights are ever downloaded in CI — is **#138's**, not this ADR's. This ADR establishes that
the job exists, that it installs the extra, and that it is the only job that may.

### torch comes from the CPU index under a Linux marker, and `pip` divergence is accepted

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux'" }]
```

#127 found that torch on macOS needs no `+cpu` variant and no custom index, and resolves **zero**
NVIDIA packages there. On Linux x86_64 it resolves roughly fifteen `nvidia-*-cu12` wheels, and
`ubuntu-latest` is exactly that platform — so an unrestricted lock plus `uv sync --extra asr` in CI
pulls on the order of 2.5 GB on every run, into a cache with a 10 GB per-repository cap. Pinning the
Linux resolution to the PyTorch CPU index brings the `asr` job to roughly 200 MB.

The cost is real and is accepted on the record: **`[tool.uv.sources]` is uv-only**. A Linux user
running `pip install 'sdw[asr]'` reads only the published extra and gets the default CUDA-flavoured
torch, so CI proves a resolution that no `pip` user performs. The alternative — an unrestricted lock,
so CI installs precisely what a Linux `pip` user gets — has the honesty argument and is the genuine
runner-up.

It is rejected on what the divergence actually costs, which is nothing the `asr` job measures. That
job type-checks and proves the extra resolves; CPU torch and CUDA torch are type-identical, so
neither result differs. The property lost is "CI proves the `pip`-user resolution," and it is worth
less than 2.5 GB per run — particularly on a repo whose sole operator is on macOS, where the pin
does not apply at all and the local install is the default PyPI wheel either way.

Two things follow that a future reader should not have to rediscover: the NVIDIA packages do not
appear in `uv.lock` under this pin, so the lockfile stays legible; and a contributor on Linux who
uses `pip` rather than `uv` is in a supported but **untested** configuration, which is a fact for
#144's install documentation to state rather than a defect to fix.

### `mypy --strict` moves to the `asr` job, and only `transformers` gets an override

`transformers` ships no `py.typed`, so it needs `ignore_missing_imports` in every venv, present or
absent. That is not a decision — it joins the four entries already in `[[tool.mypy.overrides]]`
(`soundfile`, `soxr`, `scipy`, `matplotlib`) for exactly the reason they are there.

`torch` is the opposite case: it **does** ship `py.typed`, so an override would discard real type
information to buy a green light. It gets none, and `mypy --strict` therefore cannot run in a
torch-free venv at all — which is why it leaves the `check` job.

The move is a strict improvement rather than a trade. mypy's result does not depend on the venv
except through stub availability, and the `asr` venv is a superset of `check`'s: same files, same
`strict`, plus real torch stubs. Running it in the richer venv **dominates**.

The rejected option is to override `torch.*` as well, keeping one `mypy` invocation that passes
anywhere. It is rejected because its failure mode is silent: in the torch-free venv every torch call
becomes `Any`, `--strict` over the newest and least familiar code in the repo is close to vacuous,
and if the `asr` job is ever skipped or dropped, mypy does not go red — it goes **weak**, with
nothing in the output saying so. That is the silent-degradation shape this map has now refused in
ADR-0016 (repetition penalty), ADR-0017 (silent exclusion of failed Samples), ADR-0018 (Tier B
laundering speaker deviation) and ADR-0022 (a `flags` section reading as ASR-as-dataset-QA).

The accepted cost is local friction: a contributor who has not installed the extra cannot run `mypy`
at all — it fails on `import torch` rather than passing weakly. That is the honest report. You
cannot type-check the ASR module without the ASR dependencies, and a green-but-vacuous run says you
can. On macOS the extra is ~471 MB unpacked with zero NVIDIA packages (#127), which is a one-time
cost for the repository's single operator.

### Floors, no caps — the provenance record is the pin

`transformers>=5` and `torch>=2.13`: floors set by the API surface ADR-0016 actually calls
(`WhisperProcessor` + `generate()`), and nothing above them.

The repo already runs a two-tier policy it has never named — runtime dependencies bare (`soundfile`,
`soxr`, `numpy`, `scipy`, `matplotlib`), dev tooling `==`-pinned (`ruff==0.14.4`, `mypy==1.19.0`,
`pytest==9.0.1`, `pytest-cov==7.0.0`). The ASR dependencies sit on the runtime tier and stay there.

The argument is not consistency. **An `==` pin would claim a reproducibility this map explicitly
disclaims.** ADR-0016 records `torch_num_threads` and `attn_implementation` rather than pinning
them, on the grounds that Transcription is *attributed, not reproducible*; ADR-0020 puts the
resolved library versions in `run.json` for the same reason. A pin would assert a guarantee the
model does not honour anyway, while the provenance record already answers *which version produced
this number* honestly, and answers it per Run rather than per release. `uv.lock` pins exactly for
whoever uses uv, which is us.

Caps are rejected on evidence in the research rather than on principle: #127 found NeMo's
`transformers~=4.57` against a current 5.14.1 as one of the reasons that stack is **mechanically
non-viable**. Caps rot, visibly, in this exact ecosystem, and the failure they produce is an
unsatisfiable resolution rather than a bad number.

### The model cache is the operator's

Restated from ADR-0016 rather than decided here, because it is a packaging-shaped fact and this is
where someone will look for it: the ASR path **respects `HF_HOME` and `HF_HUB_CACHE` and sets
neither**. No project-local cache default, no `--data-out`-adjacent weights directory, nothing
written inside `--eval-out`. The weights are large, shared across projects, and already have a
well-known location the operator may have moved; a project-local default would silently re-download
gigabytes for a user who had already paid for them once.

### The install story, written by #144

#137 asks for install documentation for two audiences. The *story* is decided here; the prose is
[#144](https://github.com/andrewferk/speech-dataset-workbench/issues/144)'s, which owns the README
and is about to rewrite it for four commands. Writing it here would duplicate that work in a file
#144 is going to replace.

What #144 inherits, and must not lose:

- **Dataset work needs nothing new.** `uv sync`, or `pip install sdw`, and `build`/`validate` work
  exactly as v0.1 documented.
- **`transcribe` needs the extra.** `uv sync --extra asr`, or `pip install 'sdw[asr]'`.
- **`score` deliberately needs neither**, and saying so is the documentation of ADR-0017's split
  contract to a reader who will never open an ADR. It is also the only place the reader learns that
  yesterday's Run can be re-scored on a machine that cannot transcribe.
- **The `pip`-on-Linux caveat** from the CPU-index decision above: supported, but not the
  configuration CI exercises.

### `CONTEXT.md` is unchanged

This ADR introduces no domain vocabulary. Extras, dependency groups, index pins and import graphs are
tooling surface, not domain language — the same call ADR-0016 made for `decode parameters` and
ADR-0005 made for `soxr HQ`, both pinned in an ADR without a glossary entry. ADR-0014, the closest
precedent, is the other packaging ADR that changed `CONTEXT.md` not at all.

## Consequences

- `pyproject.toml` gains `[project.optional-dependencies] asr`, a `[[tool.uv.index]]` block for the
  PyTorch CPU wheels, a `[tool.uv.sources]` entry pinning `torch` to it under a Linux marker, and a
  `transformers.*` entry in `[[tool.mypy.overrides]]`. `mypy`'s `files` list is unchanged.
- `src/sdw/` gains its first subpackages, `transcribe/` and `score/`. The other seventeen modules do
  not move.
- `cli.py` loses its module-level `from sdw import pipeline`; all four dispatch branches import
  their command module inside the branch.
- `tests/unit/` gains the AST import-graph test. It is the first test in the repo that reads source
  rather than running it.
- CI goes from two jobs to three. `check` keeps the smoke, `ruff` and `pytest`, and loses `mypy`;
  the new `asr` job installs the extra and runs `mypy --strict`.
- **`uv.lock` grows.** `torch`, `transformers` and their transitive closure enter it, resolved
  against the CPU index on Linux and PyPI elsewhere. `uv sync` with no flags installs none of them.
- A contributor without the extra can run `ruff` and `pytest` but not `mypy`.
- No pipeline behavior changes, no artifact changes, and no v0.1 output is touched.

## Amendments to earlier ADRs

**ADR-0014** is amended in place. Its smoke step — `sdw --help` from a temp directory outside the
checkout — was written to assert three properties (the console script resolves, the package imports
without environment help, the CLI works when the operator's data is elsewhere). It now silently
carries a fourth: that the full subcommand table builds in a venv with no ASR extra. The step is
unchanged; the annotation records that the property exists so that a future edit to the step knows
what it would be deleting. ADR-0014's *"the install itself needs no check: `uv run pytest` imports
`sdw`"* now describes one of two venvs, and the `asr` venv has no equivalent backstop — the
`mypy --strict` run is what proves that install worked.

## Rejected alternatives

- **A PEP 735 dependency group for `asr`** — not an alternative at all once the mechanics are
  checked: groups are absent from published metadata, so no consumer of `sdw` can request one. Recorded
  because the repo's `pyproject.toml` uses a group and an extra side by side, and the asymmetry reads
  as an oversight until you know why.
- **A separate `sdw-asr` distribution** — the only option that would make rule 1 structural. Rejected
  on a second version number and a cross-distribution compatibility question, and because it makes
  rule 3 — the boundary that actually needs help — *easier* to violate rather than harder.
- **One `sdw/eval/` package** — matches ADR-0015's vocabulary, where Evaluation is both halves, and
  fails the ticket's own constraint by putting the dependency line inside the package.
- **Flat modules with a naming convention** — the status quo extended. Rejected because `score` is
  eight-or-so modules on its own, so the "flat" option was really "twenty-five flat modules with the
  boundary maintained by whoever last read the ADR."
- **One lazy import in the `transcribe` branch, with a comment** — the minimal change, and the
  reason it is rejected is the comment. A single sanctioned exception is what a later tidy-up
  removes; a uniform rule is not.
- **`try: … except ImportError:` around the dispatch import** — two lines, and it tells an operator
  to install the extra when the actual fault is a typo in our own module names.
- **`import-linter`** — the maintained tool, with chain reporting for free, and it cannot express
  the module-level-versus-function-body distinction this ADR depends on. It would also put the rule
  in configuration `pytest` does not run.
- **A subprocess `sys.modules` assertion** — fifteen lines and transitive by construction, but blind
  to function-body imports, which is the pattern this ADR sanctions and rule 3's likeliest violation.
- **An unrestricted lock, so CI installs what a Linux `pip` user gets** — the honesty argument, and
  the genuine runner-up. Rejected because the property it buys is not one the `asr` job measures,
  at roughly 2.5 GB per run.
- **No torch in CI at all, with `ignore_missing_imports` for `torch.*`** — cheapest, and it gives up
  `--strict`'s teeth over the least familiar code in the repo.
- **`torch.*` overridden so `mypy` passes in either venv** — keeps one invocation and local
  ergonomics, at the price of a check that degrades from strong to vacuous **without going red**.
- **`==` pins on `transformers` and `torch`** — asserts a reproducibility ADR-0015 and ADR-0016
  spent their length disclaiming, and duplicates what `run.json` already records per Run.
- **Upper caps** — #127 found NeMo's `transformers~=4.57` cap against 5.14.1 as a reason that stack
  is mechanically non-viable. The same mechanism, applied to us.
- **Writing the install documentation here** — #144 owns the README and is rewriting it for four
  commands; this ADR hands it the story and the caveat instead.
