"""Grant coins/achievement when onboarding questline completes."""
from __future__ import annotations

import logging

from database import add_coins, check_and_unlock_achievement, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

REWARD_COINS = 150
REWARD_KEY = "onboarding_complete_reward"


async def try_grant_onboarding_reward(
    guild_id: int,
    user_id: int,
    *,
    interaction=None,
    bot=None,
) -> tuple[bool, str]:
    """Idempotent completion reward. Returns (granted_now, message)."""
    try:
        from commands.general.onboarding import (
            ONBOARDING_STEP_NAMES,
            get_user_onboarding_progress,
        )

        done, _steps = await get_user_onboarding_progress(guild_id, user_id)
        if done < len(ONBOARDING_STEP_NAMES):
            return False, ""

        flag = await get_guild_setting(guild_id, f"{REWARD_KEY}:{user_id}")
        if flag == "1":
            return False, ""

        await add_coins(guild_id, user_id, REWARD_COINS, "ONBOARDING", "Completed onboarding questline")
        try:
            await check_and_unlock_achievement(
                guild_id, user_id, "onboarding_complete", None, interaction=interaction,
            )
        except Exception:
            pass
        await set_guild_setting(guild_id, f"{REWARD_KEY}:{user_id}", "1")
        msg = (
            f"🎉 **Onboarding complete!** +**{REWARD_COINS}** coins and a badge unlocked. "
            "Welcome to the clan — `/menu` for shortcuts."
        )
        client = bot or (interaction.client if interaction else None)
        if client:
            guild = client.get_guild(guild_id)
            member = guild.get_member(user_id) if guild else None
            user = member or client.get_user(user_id)
            if user:
                from core.safe_send import safe_dm
                from core.utils import obsidian_embed

                await safe_dm(
                    user,
                    embed=obsidian_embed("🎉 Onboarding complete", msg, client=client),
                )
        if interaction and not interaction.response.is_done():
            try:
                from core.utils import success_embed

                await interaction.followup.send(
                    embed=success_embed("Questline complete", msg, client=interaction.client),
                    ephemeral=True,
                )
            except Exception:
                pass
        return True, msg
    except Exception as exc:
        logger.debug("[onboarding_reward] %s", exc)
        return False, ""
