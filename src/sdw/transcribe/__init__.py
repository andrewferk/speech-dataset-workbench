"""Transcription — the expensive, non-reproducible half of Evaluation (ADR-0015, ADR-0017).

The package boundary *is* the dependency boundary (ADR-0023): the `asr` extra is required by exactly
one leaf module, and every other module here imports with no extra installed, which is what keeps
the plumbing suite in the CI job that installs none. `sdw.manifest` and `sdw.provenance` are
off-limits at any depth — Transcription reads the emitted JSONL and `dataset.json` like a stranger,
`SPLIT_ORDER` included (ADR-0017). `sdw.serialization` is the one permitted exception: byte-format
of our *own* output is not dataset interpretation (ADR-0019).
"""
