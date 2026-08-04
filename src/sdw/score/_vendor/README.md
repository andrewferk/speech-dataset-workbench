# Vendored third-party source

Everything under this directory is copied verbatim from an upstream project at a pinned revision. It
is excluded from `ruff` and from `mypy --strict` (see `pyproject.toml`), because the whole point of a
vendored copy is that it is byte-identical to something someone else published — a lint fix or a type
annotation applied here would silently make that false.

**Do not edit these files.** To move to a newer upstream revision, re-copy the whole tree, update the
revision below, and update the Normalizer identity string that names it.

## `whisper_normalizers/`

| | |
| --- | --- |
| Upstream | [openai/whisper](https://github.com/openai/whisper) |
| Path | `whisper/normalizers/` |
| Revision | [`b80bcf610d89960bc658b61af9c333fc6d978d78`](https://github.com/openai/whisper/tree/b80bcf610d89960bc658b61af9c333fc6d978d78/whisper/normalizers) (2023-03-06) |
| Files | `__init__.py`, `basic.py`, `english.py`, `english.json` |
| Licence | MIT — `whisper_normalizers/LICENSE`, Copyright (c) 2022 OpenAI |

`EnglishTextNormalizer` from `english.py` is Tier B, addressed as `whisper-english/b80bcf6`
(ADR-0018). Three different functions ship under that class name across `openai/whisper`,
`transformers` and `open_asr_leaderboard`, so the revision is part of the identity rather than a
footnote — changing it changes the number, and the Report names the string.

Depending on the package instead was not available: `openai-whisper` requires torch, and
`transformers` sits behind the `asr` extra that ADR-0023 forbids the Scoring path from reaching.
`basic.py` is not used directly, but `english.py` imports from it, so it is vendored with it.

Its two imports — `regex` and `more_itertools` — are therefore **base** dependencies of `sdw`, not
extras.
