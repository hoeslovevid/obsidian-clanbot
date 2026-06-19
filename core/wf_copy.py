"""Unified Warframe degraded-data copy for embeds and replies."""
from __future__ import annotations

from core.cache_utils import cache_footer_suffix


def wf_degraded_note(*, cache_key: str | None = None, stale_after: float = 120.0) -> str:
    """Standard suffix when WF data may be stale."""
    suffix = cache_footer_suffix(cache_key, stale_after=stale_after) if cache_key else ""
    base = "_Warframe data may be cached until the API recovers._"
    return base + suffix if suffix else base


def wf_unavailable_body() -> str:
    return (
        "The Warframe stats API is unreachable right now.\n\n"
        "Tap **Notify me when back** and I'll DM you once data is live again."
    )


def merge_wf_footer(base: str, cache_key: str | None = None, *, stale_after: float = 120.0) -> str:
    """Append standard degraded/cache suffix to a Warframe embed footer."""
    if not cache_key:
        return base
    from core.cache_utils import freshness_note

    suffix = freshness_note(cache_key, stale_after=stale_after)
    if not suffix:
        return base
    return (base or "").rstrip() + suffix
