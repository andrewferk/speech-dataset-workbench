# Code comments

**Trace, don't restate.** The ADR is the single source of truth for *why*. Code carries only what a future editor needs at the moment they edit.

- Cite a decision by bare tag — `(ADR-0005)` — and let the tag carry the reasoning.
- Comment when an edit that looks correct would break a decision. Say what breaks, in one line.
- Docstrings state the contract: what it returns, what it raises, what invariant it holds. One to three lines.
- Rejected alternatives, trade-offs, library choices, and licensing live in the ADR. If a rationale needs a paragraph, add that paragraph to the ADR and cite the tag.
- Delete any comment whose removal wouldn't change what a future editor does. If a comment restates a sentence that exists in an ADR, the tag alone replaces it.
- Comments and docstrings together stay under ~40% of a module's lines. This is a smell detector, not a build gate — a breach means look at the file.
