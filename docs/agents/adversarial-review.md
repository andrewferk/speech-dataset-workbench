# Adversarial review

Configuration for the `/adversarial-review` loop. The fenced `yaml` block below is parsed by `scripts/cursor-review.sh`; the prose is for humans. Edit values in place — re-running `/setup-adversarial-review` is only necessary to change the reviewer model or re-check the Cursor bridge.

```yaml
reviewer_model: cursor-grok-4.5-high
max_rounds: 2
blocking_kinds: violation, missing, partial, wrong
script_path: /Users/andrewferk/.claude/plugins/cache/adversarial-code-review/adversarial-code-review/0.1.0/scripts/cursor-review.sh
skill_dir: /Users/andrewferk/.claude/plugins/cache/adversarial-code-review/adversarial-code-review/0.1.0/skills/adversarial-review
code_review_fallback_path: /Users/andrewferk/.claude/plugins/marketplaces/mattpocock/skills/engineering/code-review/SKILL.md
code_review_discovery: skill
```

## What each key does

- **`reviewer_model`** — the Cursor model that reviews this repo's changes. Required, no default. The whole mechanism rests on it being a *different* training distribution from the model that writes the code, so pick a model from a different family than the one you implement with. `cursor-agent models` lists what your account can reach.
- **`max_rounds`** — how many challenge/confirm rounds before the loop gives up and escalates. Default `3`. Beyond that the two sides are usually arguing about taste, which is a human's call.
- **`blocking_kinds`** — which finding kinds hold the pull request in draft. Default `violation, missing, partial, wrong`. The two left out, `judgement` and `scope-creep`, still have to be dispositioned; they just do not block on their own.
- **`script_path`** — absolute path to `cursor-review.sh`, resolved once at setup so no round has to go looking for it.
- **`skill_dir`** — absolute path to the `adversarial-review` skill folder, where the briefs and the wire contract live.
- **`code_review_fallback_path`** — absolute path to `/code-review`'s `SKILL.md`, used in the reviewer's brief as a fallback for when Cursor cannot see the skill. Points at the marketplace git checkout, which `git pull`s in place, rather than the versioned plugin cache, which moves on every update.
- **`code_review_discovery`** — `skill` if Cursor can see `/code-review` as a skill, `fallback` if the reviewer has to read the SKILL.md by path. Set by the probe at setup.
