"""Scoring — the deterministic half of Evaluation: no model, no weights, no network, no torch.

Base dependencies only. The package boundary *is* the dependency boundary (ADR-0023): a module-level
import from `sdw.transcribe`, or of anything behind the `asr` extra, breaks the `check` CI job that
installs no extra. `sdw.manifest` and `sdw.provenance` are off-limits at any depth — Scoring reads
the emitted JSONL like a stranger.
"""
