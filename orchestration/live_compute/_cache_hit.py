"""What a live view needs around the result-set cache: its finder and its log line.

Also the subject every "where did this curve come from" line starts with."""


def build_curve_subject(analysis_name: str, channel_name: str) -> str:
    """The subject of a log line about one channel's curve, "Spectrum for
    B1 Out:+Z" -- what the cache, Tab cache and restore-recipe lines name."""
    return f"{analysis_name} for {channel_name}"


def resolve_cache_finder(session, enabled=True):
    """
    The worker-thread result-set lookup (`ProjectSession.cache_finder`) of
    `session`, or None when the cache is off (`enabled` False) or there is no
    session. `enabled` is the verdict the caller holds -- the applied
    `use_result_cache_lookup` setting, or the one a drop took for its batch.
    """
    if not enabled:
        return None
    finder = getattr(session, "cache_finder", None)
    return finder() if finder is not None else None


def build_cache_hit_line(subject: str, result_set_label: str, *, what: str = "FFT settings") -> str:
    """The line for a result that came from a saved result set; `subject` is the whole phrase."""
    return (f"PROJECT: {subject} loaded from result set "
            f"'{result_set_label}' -- {what} unchanged, no recompute needed.")
