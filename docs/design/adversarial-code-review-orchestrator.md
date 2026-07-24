# Adversarial Code Review orchestrator — design spec

**Status:** design, ready to hand off to an `/implement` build effort. Not yet built.

**Source of decisions:** wayfinder map [#104](https://github.com/andrewferk/speech-dataset-workbench/issues/104)
and its closed tickets #105–#109, #111, #112, #113. This document consolidates those
decisions; each section cites the ticket that settled it. Where this doc and a ticket
disagree, the ticket's *latest* comment wins (several were reconciled after the fact —
notably the `auto-loop` → `adversarial-review` label rename in #113).

---

## 1. Purpose & destination

From a single human invocation `/implement <spec>`, run hands-off through:

```
/implement <spec>
    → isolated worktree
        → build (implementer)
            → draft PR
                → bounded implementer ↔ independent-reviewer loop on the PR
                    → ready-for-review   (converged)
                    or → parked / needs-human   (capped or failed)
```

**Multiple such loops run concurrently**, each in its own worktree, supervised by one
long-lived orchestrator. The flow stops at *ready-for-review*; a human merges. The
orchestrator never selects work on its own — a human always invokes `/implement`.

The runtime concept is **adversarial code review (ACR)**: an implementer and an
independent, different-model reviewer held in tension until the reviewer signs off or a
round cap is hit.

### Out of scope (map #104)

- **Auto-merge** — flow stops at ready-for-review.
- **Auto-kick-off from a ticket** — a human invokes `/implement <spec>`; no autonomous
  work-selection.
- **Cloud / CI orchestration & multi-user** — local driver only.
- **Changing what `/implement` or `/code-review` evaluate** — this effort wires existing
  skills together; it does not redesign their content.

---

## 2. Roles & billing posture

### Implementer

An **in-session Task subagent** of the orchestrator (§3), pinned by cwd to the loop's
existing worktree. It builds, pushes, opens the draft PR on its first turn, and posts an
ACR marker each turn.

### Independent reviewer

**Grok 4.5, driven locally by `cursor-agent -p --model grok-4.5 -f "<prompt>"`** inside
the loop's worktree (#107). The reviewer emits its review to **stdout**; the **driver
relays it to the PR** via `gh pr comment` with role/agent/model attribution. Grok never
posts to GitHub directly — the driver owns the comment format.

- **Model diversity is the point.** The reviewer must be a *non-Claude* model so it does
  not share the implementer's blind spots. Grok was chosen for genuine diversity *and*
  lowest token cost (#106).
- **Ruled out (#107):** Bugbot (cloud, posts in its own format); any Claude-family
  reviewer (no diversity). **No API fallback retained** — the direct xAI API path is
  ruled out for now; revisit only if `cursor-agent` proves infeasible.

### Billing posture (#105 — strong preference, API fallback)

Billing follows **authentication, not invocation mode**. A process bills to the
subscription only when signed in via `/login` **and** `ANTHROPIC_API_KEY` is *unset*
(the key overrides the subscription and forces API charges).

- **Drive from an interactive `claude` session** logged in via subscription, with
  `ANTHROPIC_API_KEY` unset. In-session Task subagents, hooks, and background Bash all
  inherit subscription billing.
- **Avoid** `claude --bare -p`, the Agent SDK library, and Managed Agents — all
  metered/API.
- If turns must ever be scripted, only **non-bare `claude -p`** in a clean-env
  (`ANTHROPIC_API_KEY` unset) stays on subscription. This spec does **not** use it — the
  implementer is an in-session subagent precisely to avoid the key-leak risk (#109).
- The real ceiling is the shared rolling **5-hour + two weekly** usage windows, not a
  documented session count. Guard weekly spend by **throttling new `/implement`
  invocations**, not by the concurrency cap (#113).

The Cursor/Grok reviewer bills to Cursor's usage pools, independent of the Claude window.

---

## 3. Driver form & state model (#109, #113)

### Driver form

A single, long-lived **interactive `claude` orchestrator session** (subscription
`/login`, `ANTHROPIC_API_KEY` unset). You start it once and leave it running (e.g. an
`/orchestrate` command or a plain supervising session). Everything it spawns inherits
its subscription auth (§2).

### Core principle — the PR is the state machine

Loop state is **not** held in the orchestrator's context. It is reconstructed from
**structured PR marker comments** (§5). Consequence: the orchestrator is **restartable** —
kill it, restart it, and it recovers every loop's state from GitHub. There is **no local
state file** (§4 rejects a registry).

### The orchestrator loop

```text
loop forever:
    prs = discover_loops()                       # gh pr list --draft --label adversarial-review
    for pr in prs[:MAX_CONCURRENT]:
        if has_label(pr, "needs-human"):         # restart guard (#112 §4) — already parked
            ensure_parked(pr); continue          #   idempotently finish parking, skip
        state, round = read_state(pr)            # §5: pure function of the latest ^ACR: marker
        case state of
          AWAITING_REVIEW                     -> run_reviewer_turn(pr)              # §2, #107
          AWAITING_IMPLEMENTER, round < 3     -> run_implementer_turn(pr, round+1)  # in-session subagent
          AWAITING_IMPLEMENTER, round == 3    -> park(pr, reason="round-cap")       # §6 trigger B
          REVIEWER_APPROVED                   -> gh pr ready pr; untrack(pr)        # §7 ready path
          no ACR marker / malformed           -> park(pr, reason="marker-anomaly")  # §6 trigger C
    sleep(POLL_INTERVAL)
```

- Distinct PRs advance in **parallel**; within one PR, turns are strictly sequential
  (implementer → reviewer → implementer …).
- **In-session turn hand-offs are event-driven** off the awaited subagent, *not* polled.
  Polling is load-bearing only for **new-loop pickup** and **restart resync**.

### Implementer turn — in-session Task subagent (#109, #113)

`run_implementer_turn` spawns an **in-session Task subagent** pinned by **cwd** to the
loop's *existing* worktree. The worktree is a **precondition** created before the
subagent (§8) — the subagent is *born into it* and does **not** spawn a fresh
`isolation: worktree`. Prompt shape: *"read the latest review marker on PR #X, address
it, push, post an implementer ACR marker."*

- Subscription billing is guaranteed (inherits session auth); **no `ANTHROPIC_API_KEY`
  leak risk**. A spawned `claude -p` was rejected — it carries #105's silent-API-billing
  risk for no gain.
- **Model/effort inherits the orchestrator session** by default (#113): launch the
  orchestrator as, e.g., Opus 4.8 / medium and the implementer subagents run Opus 4.8 /
  medium. Model choice is a **launch-time** decision, not a baked constant. "Favor
  Sonnet" is an *optional* cap-rationing note (demoted from #109's rule), not a
  requirement. Reviewer diversity (Grok) remains the quality guard regardless.

### Concurrency (#113)

- Loops keyed by **PR# ↔ branch ↔ worktree** (all one-to-one).
- **`MAX_CONCURRENT = 3`, configurable.** Its binding constraint is **human oversight**
  (every parked loop hands back to a human) **+ local-machine/subagent resources** (each
  loop = a worktree + a Claude implementer subagent + a periodic `cursor-agent` process).
  It is **not** a billing/weekly-window limit — burst is fine; weekly spend is guarded
  orthogonally by throttling new `/implement`s. Raise it once the loop proves trustworthy.
- **`POLL_INTERVAL = 60s`**, a discovery/recovery cadence only. `gh` load is a non-issue
  (~`1 + N` calls/cycle). Turns take *minutes*, so sub-minute polling buys nothing; 60s
  starts a freshly-`/implement`ed loop within a minute. Latency, not load, is the only
  constraint.

---

## 4. Loop discovery & worktree-path resolution (#109, #113)

### Discovery

`/implement <spec>` labels the draft PR **`adversarial-review`**; the orchestrator
discovers loops via:

```
gh pr list --draft --label adversarial-review
```

Decoupled, restartable, no live IPC. The label is **explicit opt-in** (respects the
"no autonomous work-selection" scope boundary). Rejected alternatives: a
`.orchestrator/loops.jsonl` registry (local state that desyncs, cuts against "the PR is
the state machine") and in-session hand-off (not restartable).

### Worktree-path resolution — pure derivation, no registry

Derive the worktree path from the branch (no stored state → preserves restartability):

1. **PR → branch:** `gh pr view <pr> --json headRefName`.
2. **branch → path:** match in `git worktree list --porcelain` — the entry whose
   `branch refs/heads/<branch>` equals it; its `worktree` line is the absolute cwd.

Git forbids two worktrees on one branch, so **branch is a guaranteed-unique key**, and
`git worktree list` enumerates all worktrees regardless of the orchestrator's cwd. A
**missing match** (worktree pruned under a still-open `adversarial-review` PR) is
**detected and surfaced, not silently skipped** → parks the loop (§6 trigger D).

---

## 5. Signaling protocol — the `ACR:` marker (#111)

State is carried on a **single greppable leading line** of each turn's PR comment, with
human prose below it.

### Field layout

```
ACR: <STATUS> round <n>/3 role=<role> agent=<tool-slug> model=<model-slug>
```

- Parsed as `^ACR:` — one anchor per comment, the whole machine record via a field split.
- The driver reads bodies through `gh pr view --json comments` (raw text, not rendered),
  so line length is purely cosmetic.
- Chosen over an HTML-comment / fenced block so a human scanning **raw** comments sees the
  state directly.
- The token `ACR:` names the runtime concept (adversarial code review); it is explicitly
  *not* `wayfinder` (the planning tool) and *not* the label string.

### Status vocabulary — exactly 3 tokens

| Token | Author | Meaning |
|---|---|---|
| `AWAITING_REVIEW` | implementer | pushed changes (or pushed back) — over to the reviewer |
| `AWAITING_IMPLEMENTER` | reviewer | changes requested — over to the implementer |
| `REVIEWER_APPROVED` | reviewer | signs off — **terminal** |

- **Convergence = reviewer-approval-terminal.** The loop ends the instant the reviewer
  emits `REVIEWER_APPROVED`; implementer satisfaction is implicit in submitting for
  review. `IMPLEMENTER_SATISFIED` and the "both satisfied / mutual handshake" framing were
  **dropped** — the implementer always hands off to the reviewer, so it needs one status;
  its stance ("declining this nit because…") lives in the prose.

### Round counter

- `round n/3`, where **n = the implementer's attempt number (1..3)**.
- The **implementer owns the counter** (stamps `round k/3` when it begins attempt k); the
  **reviewer echoes** the round it is reviewing.
- **Cap fires** on `AWAITING_IMPLEMENTER round 3/3` → park (§6 trigger B). The implementer
  gets exactly 3 attempts; the reviewer reviews each.

### Attribution (#107, #111)

- `role=implementer | reviewer` — a fixed 2-value **enum**.
- `agent=` tool slug (`claude-code`, `cursor-agent`, …); `model=` model slug
  (`claude-opus-4-8`, `grok-4.5`, …).
- Reflects the **authoring** agent, not the poster (the reviewer's comment is authored by
  Grok but relayed by the driver).
- `agent`/`model` are **free-form lowercase slugs, not an enum** — diversity is the point
  and these churn. **The driver never branches on them**; they serve only logs and the
  disagreement summary (§6 trigger B).

### State-derivation rule — `read_state`

1. `gh pr view <pr> --json comments` → chronological order.
2. Filter to comments containing a `^ACR:` line; take the **most recent** such comment; its
   marker is that first `^ACR:` line.
3. Parse **`status` and `round` only**. `role`/`agent`/`model` are **not** used for
   derivation (status implies the author).

| Latest marker | Driver action |
|---|---|
| `AWAITING_REVIEW` | run reviewer turn |
| `AWAITING_IMPLEMENTER`, `round < 3` | run implementer turn (attempt `round+1`) |
| `AWAITING_IMPLEMENTER`, `round == 3` | cap hit → park (§6 B) |
| `REVIEWER_APPROVED` | terminal → `gh pr ready`, untrack (§7) |
| *no `ACR:` marker* / malformed | anomaly → park (§6 C) |

**Latest marker wins — state is a pure function of it.** No quorum, no cross-comment
reconciliation. Per §8 the implementer opens the draft PR *and* posts
`AWAITING_REVIEW round 1/3` in the same first turn, so a well-formed loop PR always has
≥1 marker. A discovered PR with **zero** markers or a **malformed** one is an anomaly
handed to §6, not a normal turn.

### Example turn sequence

```
ACR: AWAITING_REVIEW      round 1/3 role=implementer agent=claude-code  model=claude-opus-4-8
ACR: AWAITING_IMPLEMENTER round 1/3 role=reviewer    agent=cursor-agent model=grok-4.5
ACR: AWAITING_REVIEW      round 2/3 role=implementer agent=claude-code  model=claude-opus-4-8
ACR: REVIEWER_APPROVED    round 2/3 role=reviewer    agent=cursor-agent model=grok-4.5   # terminal
```

Non-convergent tail: `ACR: AWAITING_IMPLEMENTER round 3/3 …` → cap → park.

---

## 6. Failure & non-convergence handling — the `PARKED` state (#112)

All failure/anomaly paths converge on **one canonical `PARKED` terminal state**, entered
by **five triggers**. Parking is uniform; only the summary's *reason* varies. A parked PR
is identifiable by the **`needs-human` label alone**, regardless of cause.

### The `PARKED` routine — always these five steps, in order, idempotently

1. PR stays **draft** (never `gh pr ready`).
2. Add the **`needs-human`** label.
3. **Remove the `adversarial-review`** label — **load-bearing**: a parked PR stays draft,
   so removing the label is the only thing dropping it from the
   `--draft --label adversarial-review` frontier.
4. Post one driver-authored **park summary comment** (below).
5. **Preserve** the worktree and **log** a terminal nudge (§ notification). *(Skipped for
   trigger D — there is no worktree.)*

### The five triggers

| # | Trigger | Detected at | Handling |
|---|---|---|---|
| **A** | Build fails **before a PR exists** — first implementer turn ends with no draft PR on the branch | **in-session post-check** right after awaiting the first implementer subagent (no PR ⇒ nothing for `gh pr list` to discover) | Driver **synthesizes a fallback draft PR** (`[PARKED] <branch> — failed to start`), then parks. If the branch has no diff (no commits), the driver first makes an **empty commit** (`git commit --allow-empty -m "parked: build failed before PR"`) so the PR is openable. Reason `build-failed-to-start`; summary quotes the subagent's failure output. |
| **B** | **3-round cap, no agreement** — latest marker is `AWAITING_IMPLEMENTER round 3/3` | `read_state` | Reason `round-cap`. Driver quotes the **last implementer marker and last reviewer marker** (`role`/`agent`/`model`/`round` + prose) into a neutral synthesis: *"Reviewer (`grok-4.5`) requested X; implementer (`claude-opus-4-8`) responded Y; unresolved after 3 rounds."* No extra agent turn. |
| **C** | **Zero / malformed `^ACR:` marker** on a discovered loop PR | `read_state` | Reason `marker-anomaly`; summary quotes the offending comment (or "no `ACR:` marker found"). **No retry** — turns are minutes-long and event-driven, so a missing/mangled marker is a real fault, not a race. |
| **D** | **Worktree missing** for a still-open loop PR — no `git worktree list` match (§4 seam) | worktree-path resolution | Reason `missing-worktree`. **No auto-recreate** — the driver can't distinguish a deliberate human prune from a crash, so it surfaces rather than fighting the human. Summary hands the one-command resume `git worktree add <derived-path> <branch>`, then re-add `adversarial-review`. PARKED **step 5 skipped** (no worktree). |

(The five triggers are A-with-diff, A-without-diff (the empty-commit sub-case), B, C, D.)

### The park summary comment — quote, don't adjudicate

- **Author: the driver, always.** The driver holds no domain opinion (it never branches on
  `agent`/`model`), so it **quotes, never adjudicates**, and spends **no extra agent turn**
  — it assembles the summary mechanically from artifacts it already has (PR comments,
  subagent stdout).
- **Outside the ACR protocol.** The comment is **not** an `^ACR:` marker — #111's 3-token
  status vocabulary and 2-value `role` enum stay **sealed** (no `role=driver`, no `PARKED`
  status token). It carries a distinct human-facing header, e.g. `## ⛔ Parked — needs
  human`, then the reason, the quoted markers/error, and the worktree location.

### Machine signal & restart idempotency

- **`needs-human` is the sole machine signal for "parked."** `read_state` never parses the
  park comment.
- **Restart guard:** the orchestrator treats a **present `needs-human` label as "already
  parked → skip"**, *before* parsing any marker. This makes the whole park routine
  **idempotent and re-runnable**: if a park half-completes (e.g. crash after adding
  `needs-human` but before removing `adversarial-review`), a restart re-discovers the PR,
  sees `needs-human`, completes any missing steps, and skips — a no-op.

### Worktree teardown — asymmetric, never destructive

- **On ready (converged):** attempt `git worktree remove <path>` — **no `--force`**.
  At convergence everything is pushed; the branch/PR on GitHub hold all the human needs, so
  the checkout is disposable. If remove **refuses** (worktree unexpectedly dirty),
  **leave it and log** — never destroy surprise local work. **Branch always kept.**
- **On parked (triggers A–D):** **never remove** — the human needs the local checkout to
  take over. Removed later by the human / a manual sweep. Trigger D has none to begin with.
- **Concurrency-safe:** `git worktree remove <path>` touches only that path and its
  `.git/worktrees/<id>` admin dir, never siblings, and runs only at a terminal exit (the
  loop's subagents have already returned).

### Local notification

- **`needs-human` label = source of truth** (durable, restart-survivable). The human's
  inbox is `gh pr list --draft --label needs-human` (worth a documented shell alias).
- **Terminal log line = active nudge:** at park, print one prominent line, e.g.
  `⛔ PARKED pr#123 <branch> reason=round-cap → <worktree>`.
- **No OS notification.**

---

## 7. Terminal states — summary

| Terminal state | Machine signal | PR | `adversarial-review` label | Worktree |
|---|---|---|---|---|
| **Ready** (reviewer approved) | non-draft PR | `gh pr ready` | shed automatically via `--draft` filter (removal is hygiene) | `git worktree remove` if clean, else leave + log; branch kept |
| **Parked** (needs human) | `needs-human` label | stays **draft** | removed by orchestrator — **load-bearing** | preserved (except trigger D) |

`gh pr ready` sheds *finished* loops from the frontier via the `--draft` filter;
**label removal sheds *parked* ones** (they stay draft). Both are done by the orchestrator
at the terminal exit.

---

## 8. The worktree-always + draft-PR-always invariant (#108)

> **Canonical, enforced invariant for the orchestrated `/implement` flow.** This section is
> the single source of truth for it; `AGENTS.md` carries only a thin index pointer here.
> Scope is **narrow** — it governs only the orchestrated `/implement` flow, not all
> implementation-flavored work in the repo. There is no separate `docs/agents/*` file, no
> skill override, and no wrapper command (all rejected as a second home for a rule the
> orchestrator already enforces).

The two invariants split by natural timing (flow: worktree → build → draft PR → review):

- **Worktree = precondition.** The driver (`/implement`) creates the isolated worktree
  *before* spawning the implementer. The implementer is **born into it** and never performs
  the setup, so isolation is **structural**, not instruction-followed. This is what makes N
  concurrent loops safe.
- **Draft PR = postcondition.** The implementer creates the draft PR as its **final step**
  and authors the real title + body from the completed diff (it is the only party with the
  build context) — and posts `ACR: AWAITING_REVIEW round 1/3` in the same turn (§5). The
  driver **guarantees** the PR via a **post-check**: after the implementer yields, the
  driver asserts a draft PR exists on the branch and, if missing, opens a **fallback PR**
  (parking it) or fails loudly (§6 trigger A). Pre-opening an empty PR was rejected — it
  forces placeholder title/body and fights the flow ordering.

---

## 9. Build-effort prerequisites

Setup and mechanics that the later `/implement` build effort must land — surfaced by the
decisions above, **not** themselves design decisions:

- **Reviewer transport not wired today (#107):** install the `cursor-agent` CLI on PATH,
  authenticate Cursor (`~/.cursor`), and confirm Grok 4.5 model access. None exist yet;
  the loop cannot run without them.
- **Labels:** create the **`adversarial-review`** and **`needs-human`** labels in the repo.
- **First-turn post-check + empty-commit fallback-PR** mechanic for §6 trigger A (the #108
  "opens a fallback / fails loudly if missing" seam).
- **`AGENTS.md` index pointer** to §8 of this doc (per #108: index points at detail).
- **Documented shell aliases:** the parked inbox `gh pr list --draft --label needs-human`
  and the loop frontier `gh pr list --draft --label adversarial-review`.
- **The riskiest slice to prototype first (#109):** drive **one** loop end-to-end —
  implementer subagent → push + marker → orchestrator detects reviewer's turn →
  `cursor-agent -p` → relay → round 2 → approval → `gh pr ready`. The genuinely unproven
  mechanics are (a) turn detection from PR-comment markers, (b) the `cursor-agent -p`
  stdout → `gh` relay, and (c) subscription billing actually holding for the subagent turn.

---

## 10. Assets & provenance

- Research: `docs/research/claude-code-billing-modes.md` (branch
  `research/claude-code-billing-modes`), `docs/research/independent-reviewer-options.md`
  (branch `research/independent-reviewer-options`).
- Prototype strawman: `docs/prototype/orchestration-driver.md` (branch
  `worktree-prototype+orchestration-driver`).
- Decisions: map [#104](https://github.com/andrewferk/speech-dataset-workbench/issues/104);
  tickets #105 (billing), #106 (reviewer research), #107 (reviewer decision),
  #108 (invariant placement), #109 (driver design), #111 (signaling protocol),
  #112 (failure handling), #113 (concurrency & discovery).
