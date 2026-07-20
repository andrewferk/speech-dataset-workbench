# A build backend, and `sdw` as the entry point (#48)

We add a `hatchling` build backend so `uv sync` installs the package into `.venv`, and take the
`[project.scripts]` entry point that becomes available. This **amends ADR-0012**, whose *Release
mechanic* said "no build backend."

It adds no pipeline behavior: no new stage, no new output, no change to any artifact. What changes
is how the tool is put on the interpreter's path, and what you type to run it.

## The problem

ADR-0012 fixed a src-layout with no build backend, so nothing installs the package and `src/` must
be put on `sys.path` by hand. That was done in four places, one per audience:

| Audience | Where `src` was set |
|---|---|
| `pytest` | `pyproject.toml` → `[tool.pytest.ini_options] pythonpath` |
| CI | `.github/workflows/ci.yml` → `env: PYTHONPATH` |
| mise users | `mise.toml` → `[env] PYTHONPATH` |
| Everyone else, running the CLI by hand | *(nothing — `PYTHONPATH=src`, typed)* |

The fourth row was silently empty until #47/#49: `python -m sdw` as documented in the README failed
with `No module named sdw` for any contributor not using mise. #49 documented the prefix rather than
removing it.

Four copies of one string, none of which check each other, is **the second source of truth that
drifts from day one** — ADR-0012's own words for the thing it was written to refuse. It had simply
been displaced from a checklist into path configuration, where it was harder to see.

## Decisions

### The no-install property was never load-bearing

ADR-0012's argument for no build backend is one sentence: "the tooling research chose no build
backend unless a packaged CLI is needed, and #8 runs the tool as `python -m <package>`." The
research's reason in turn is that an undistributed CLI "needs no build system," honoring *avoid
premature production architecture*.

That is **the absence of a reason to add one, not a property being protected**. No ADR depends on
the package being uninstalled. Re-reading ADR-0012 on its own terms — which #48 rightly insisted on
before anything changed — finds nothing that the install costs us.

So this is not a decision reversed against its reasoning. It is a decision whose premise ("we have
no need for a backend") expired the moment the need showed up.

### src-layout's rationale is void without an install, which is what ruled out the flat layout

The obvious cheaper fix is to keep no build backend and **drop the src-layout** — move `src/sdw/` to
`sdw/`, and `python -m sdw` works because Python puts the CWD first on `sys.path`. This deserved a
real hearing, because the research's stated rationale for src-layout is:

> a flat layout can silently import the in-tree package instead of the installed one and mask
> packaging bugs; src-layout forces tests to run against the installed package.

Every clause of that is **conditional on there being an installed package**. With no build backend
there is no in-tree-vs-installed divergence to mask, so src-layout's benefit here was exactly zero
while its cost was the four rows above. src-layout + no backend, and flat + no backend, are each
internally coherent; what we had was the mixture that pays the cost and collects no benefit.

The flat layout is rejected anyway, on two grounds:

1. **It does not reach zero configuration.** `uv run pytest` does not put the CWD on `sys.path` —
   pytest inserts the test file's parent, `tests/`. It would still need a root `conftest.py` or
   `pythonpath = ["."]`. One site instead of four, but not none.
2. **It breaks CWD-independence.** `cd ~/my-recordings && sdw build …` fails, because `sdw/` is not
   there. This is the decisive one: the tool's *purpose* is to be pointed at data that lives
   somewhere else. It trades a known sharp edge for a worse-placed new one, and the README's
   walkthrough — which runs from the repo root — would not have caught it.

Adding the backend is the only one of the three options that reaches zero, and the only one that
does not degrade the CLI somewhere else to get there.

### `sdw` is the entry point; `python -m sdw` stays

`[project.scripts]` gives `sdw = "sdw.cli:main"`. The README documents `sdw`; `__main__.py` remains,
routing to the same `main`, so `python -m sdw` is equivalent.

Keeping both is not a second source of truth — one function, two doors, nothing to diverge. And
`python -m sdw` earns its keep for the reason this whole ADR exists: it works without anything being
on PATH, which is the failure mode we just spent an issue on.

This is a **product surface change**, and ADR-0012 was emphatic that it added none. Taken now, at
the finish line, deliberately: `examples/README.md` does not exist yet, and ADR-0012 requires it be
written **from observed output** (#35). Deferring the script means #35 writes a walkthrough against
`python -m sdw`, and a later release rewrites the one document whose entire authority comes from
having been written against what the tool actually printed. The churn is cheaper now, at one line,
than later at the cost of that document's provenance.

### The zero-config claim is asserted, not asserted-in-prose

*"Prose nothing runs is prose that is wrong within two releases"* (ADR-0012) applies to this ADR.
CI runs `sdw --help` from a temp directory outside the checkout, with no `PYTHONPATH` set anywhere.

One step, three properties, none of them otherwise covered: the console script resolves, the package
imports without environment help, and the CLI works when the user's data is not in the repo. That
last is the exact edge cited above to reject the flat layout — rejecting an option for a failure
mode and then not testing for it would be the same unchecked prose in a new place.

The install itself needs no check: `uv run pytest` imports `sdw`, so a broken install fails the
suite immediately.

## Consequences

- All four `PYTHONPATH` rows are deleted. `pytest`, CI, mise, and a bare `uv run sdw` all work with
  nothing set.
- `pyproject.toml` gains `[build-system]` and `[project.scripts]`, and loses `[tool.uv] package =
  false`. `uv sync` now installs the project **editable**, so source edits take effect without a
  re-sync.
- `mise.toml` keeps `_.python.venv` from #47 — still doing real work, pointing bare `python` and
  `pytest` at the venv — and loses only `[env]`.
- CI gains one smoke step; the `env:` block goes away entirely.
- README drops #49's `PYTHONPATH=src` stopgap and resolves the literal `<package>` placeholder,
  which #49 left behind, to `sdw`.
- **No pipeline behavior changes.** No stage, output, or artifact is touched.
- `CONTEXT.md` is unchanged; this ADR introduces no domain vocabulary.

### Left open for #37

`tool_version` (ADR-0010) is unimplemented — it is #37's work. An install makes
`importlib.metadata.version("sdw")` available, which is the more conventional source than reading
`pyproject.toml`. **Noted, not decided.** There is nothing here to change yet, and reaching into an
unimplemented ADR-0010 concern from a packaging change is how a packaging change grows a tail.

## Considered and rejected

- **Flat layout, no build backend** — the genuine runner-up, and cheaper. Rejected on
  CWD-independence, and because it still needs one config site. Its reasoning is recorded above
  rather than dismissed, because the observation that made it viable (src-layout's rationale is
  void without an install) is the thing a future reader is most likely to re-derive from scratch.
- **Delete three of the four rows, keep `pytest`'s** — fixes drift by making the cost uniform
  instead of removing it. Every contributor types the prefix forever, and the README stays a place
  where a path string is maintained by hand.
- **Leave it; document the prefix** — the status quo after #49. This is the option that had already
  failed: the prefix was documented precisely because the four-way split had produced a broken
  README, and documenting a defect does not stop it drifting.
- **A grep asserting `PYTHONPATH` appears nowhere** — checklist-shaped, a negative check mirroring a
  set of files, which ADR-0012 rejected twice on its own account. The positive smoke subsumes it:
  the property is "works without it," not "the string is absent."
- **`[project.scripts]` deferred to its own issue** — the scope-disciplined reading, and coherent.
  Rejected on the #35 timing above.
- **Amending ADR-0012 in place with no new ADR** — the treatment ADR-0012 gave ADR-0009. That fit
  there because it was a correction with no decision behind it ("the body was right; the heading was
  a stale draft artifact"). Here there is a live decision with rejected alternatives, and ADR-0012's
  *Considered and rejected* is about acceptance criteria — the flat layout has no honest home in it.
