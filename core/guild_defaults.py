"""Default guild settings applied when the bot joins a new server."""
from __future__ import annotations

import logging

from core.config import DEFAULT_LEAN_FEATURES
from core.utils import TOGGLEABLE_FEATURES
from database import set_guild_setting

logger = logging.getLogger(__name__)

# Off by default on new installs when DEFAULT_LEAN_FEATURES is enabled.
_LEAN_OFF_FEATURES: frozenset[str] = frozenset({"music", "pets", "gambling"})


async def apply_new_guild_defaults(guild_id: int) -> None:
    """Apply lean feature defaults for discovery-sized installs."""
    if not DEFAULT_LEAN_FEATURES:
        return
    for feat in _LEAN_OFF_FEATURES:
        if feat not in TOGGLEABLE_FEATURES:
            continue
        try:
            await set_guild_setting(guild_id, f"feature:{feat}", "off")
        except Exception:
            logger.debug("[guild_defaults] failed feature:%s guild=%s", feat, guild_id, exc_info=True)
    logger.info(
        "[guild_defaults] lean defaults applied guild=%s (off: %s)",
        guild_id,
        ", ".join(sorted(_LEAN_OFF_FEATURES)),
    )
