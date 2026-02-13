"""
Update Discord application profile metadata (description, tags).
Makes the bot profile more informative when users view it.
"""
import logging
import aiohttp

from config import TOKEN

logger = logging.getLogger(__name__)

# Description shown on the bot's profile (max 4000 chars for application description)
APP_DESCRIPTION = (
    "Warframe clan bot with voice channels, events, economy, moderation, and more. "
    "Try /help • /warframe status • /economy balance • /general profile"
)

# Tags for discovery (max 5, 20 chars each) - shown on profile / App Directory
APP_TAGS = ["Warframe", "Economy", "Events", "Voice", "Community"]


async def update_app_profile_metadata():
    """
    PATCH the application's description and tags via Discord API.
    Makes suggested commands and features visible on the bot's profile.
    """
    url = "https://discord.com/api/v10/applications/@me"
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "description": APP_DESCRIPTION[:4000],  # Discord limit
        "tags": [t[:20] for t in APP_TAGS[:5]],  # Max 5 tags, 20 chars each
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    logger.info("[app_profile] Application description and tags updated")
                else:
                    text = await resp.text()
                    logger.warning(f"[app_profile] Failed to update application metadata: {resp.status} {text}")
    except Exception as e:
        logger.warning(f"[app_profile] Error updating application metadata: {e}")
