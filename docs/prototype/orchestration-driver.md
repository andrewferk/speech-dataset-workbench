# Prototype strawman: the local orchestration driver

Rough artifact for wayfinder ticket #109 ("Design the local orchestration driver"),
child of map #104. **Not a build** — a concrete design to react to. Grounded in the
closed research: billing (#105), reviewer (#106/#107), invariant placement (#108).

---

## Driver form — *recommended, low openness*

A single, long-lived **interactive `claude` orchestrator session**, logged in via
subscription (`/login`; `ANTHROPIC_API_KEY` **unset**).

Forced by #105: mode 1 (interactive session) keeps everything it spawns — Task
subagents, background Bash, hooks — on subscription billing. An external
script/daemon buys nothing here and risks tipping to API billing. You start it once
and leave it running (`claude` → an `/orchestrate` command, or a plain supervising
session).

## Core principle: **the PR is the state machine**

Loop state is **not** held in the orchestrator's context. It is reconstructed from
**structured PR comments** (the signaling protocol — still fog, ticket forthcoming).
Every turn ends with a marker comment carrying: role, agent tool + model, a status
token (`AWAITING_REVIEW` / `AWAITING_IMPLEMENTER` / `IMPLEMENTER_SATISFIED` /
`REVIEWER_APPROVED`), and `round n/3`.

Consequence: the orchestrator is **restartable**. Kill the session, restart it, and
it recovers every loop's state from GitHub — no in-memory state to lose.

## The orchestrator loop (pseudocode)

```text
loop forever:
    loops = discover_loops()                 # see "Loop discovery" fork
    for pr in loops[:MAX_CONCURRENT]:
        state, round = read_state(pr)        # grep latest marker comment via `gh`
        case state of
          AWAITING_IMPLEMENTER, round < 3 -> run_implementer_turn(pr)   # fork below
          AWAITING_REVIEW                 -> run_reviewer_turn(pr)       # settled (#107)
          BOTH_SATISFIED                  -> gh pr ready pr; untrack(pr)
          round == 3 and not agreed       -> label needs-human; post disagreement
                                             summary; untrack(pr)
    sleep(POLL_INTERVAL)
```

Distinct PRs advance in **parallel**; within one PR, turns are strictly sequential
(implementer → reviewer → implementer …).

## Turn invocation

### Implementer turn — **PIVOTAL FORK**

- **Option A — in-session Task subagent** *(recommended)*. Orchestrator spawns a
  subagent with `isolation: worktree` pinned to the loop's worktree. Prompt: "read
  the latest review marker on PR #X, address it, push, post an implementer marker."
  Subscription-billed with **zero** env-cleanliness risk (#105's preferred path).
  The orchestrator session holds all loops.
- **Option B — spawned `claude -p`** (non-bare) via background Bash, `cwd = worktree`,
  env scrubbed of `ANTHROPIC_API_KEY`. Loops become independent OS processes; the
  orchestrator is a thin dispatcher. **Subscription only while the child env stays
  clean** — #105 flags silent API billing if a stray `ANTHROPIC_API_KEY` leaks in.

### Reviewer turn — **settled by #107**

`cursor-agent -p --model grok-4.5 -f "<prompt + gh pr diff>"`, capture **stdout**,
relay to the PR via `gh pr comment` with role + tool + model attribution. Grok never
posts directly — the driver owns the comment format.

## Concurrency model

One orchestrator session; N loops keyed by **PR number** (↔ one branch ↔ one
worktree). `MAX_CONCURRENT` throttles fan-out, because the binding ceiling is the
subscription **weekly usage window** (#105), *not* a process/session count. Favor
**Sonnet** for implementer turns to conserve the weekly cap. Reviewer turns bill to
Cursor's pools, independent of the Claude window.

## Loop discovery — **FORK**

- **Option 1 — labelled draft-PR polling** *(recommended)*. `/implement <spec>`
  creates worktree + draft PR + an `auto-loop` label; the orchestrator discovers via
  `gh pr list --draft --label auto-loop`. Decoupled, restartable, no live IPC; the
  label is explicit opt-in (respects "no autonomous work-selection", out of scope).
- **Option 2 — registry file**. `/implement` appends `{pr, branch, worktree}` to
  `.orchestrator/loops.jsonl`; orchestrator reads it. Explicit; also carries the
  worktree path (which Option 1 must derive from the branch).
- **Option 3 — direct in-session hand-off**. `/implement` runs *inside* the
  orchestrator session and registers the loop in memory. Tightest coupling; **not**
  restartable; forces `/implement` to require a running orchestrator.

## Riskiest slice to prototype end-to-end

Drive **one** loop: implementer turn (chosen form) → push + marker → orchestrator
detects reviewer's turn → `cursor-agent -p` → relay comment → implementer round 2 →
agreement detection → `gh pr ready`. Genuinely unproven mechanics: (a) turn
detection from PR-comment markers, (b) the `cursor-agent -p` stdout → `gh` relay,
(c) subscription billing actually holding for the implementer turn in the chosen form.

## What this resolution graduates (fog → tickets)

Choosing the driver form unblocks the three fog items on the map:
1. **Signaling protocol** — exact marker comment format + attribution.
2. **Failure & non-convergence handling** — build failure, 3-round cap, cleanup,
   local notification.
3. **Concurrency bounds & loop discovery** — `MAX_CONCURRENT`, poll interval, the
   discovery mechanism picked above.
