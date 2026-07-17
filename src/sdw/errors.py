class HardError(Exception):
    """A structural failure that aborts the run: non-zero exit, no durable output (ADR-0003).

    Distinct from a quality flag, which is advisory and never affects the exit code (ADR-0007).
    """
