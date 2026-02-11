"""
Hybrid mention response: keyword matching for common queries + AI fallback.
When users @mention the bot, responds with canned replies for known phrases
or uses OpenAI when configured for everything else.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Canned responses for common phrases (case-insensitive partial match)
KEYWORD_RESPONSES = [
    (r"\b(hi|hey|hello|sup|yo)\b", "Hey! 👋 Use **`/help`** to explore commands. Quick links: **`/economy balance`** · **`/warframe status`**"),
    (r"\bhelp\b", "Use **`/help`** to see all commands! Quick links: **`/economy balance`** · **`/warframe status`** · **`/general profile`**"),
    (r"\bbaro\b", "Check Baro's visit with **`/warframe baro`** or **`/warframe status`** for Baro + Alerts + Cycles in one view."),
    (r"\b(alert|alerts)\b", "View active alerts with **`/warframe alerts`** or **`/warframe status`**."),
    (r"\b(cycle|cycles|cetus|fortuna|deimos)\b", "Check open world cycles with **`/warframe cycles`** or **`/warframe status`**."),
    (r"\b(daily|claim)\b", "Claim your daily coins with **`/economy daily`**!"),
    (r"\b(balance|bal|coins)\b", "Check your balance with **`/economy balance`** or **`/economy transactions`**."),
    (r"\b(lfg|looking for group)\b", "Create an LFG post with **`/warframe lfg`** or right-click a message → Create LFG."),
    (r"\b(price|plat|market)\b", "Check market prices with **`/trading trade_price`** or right-click a message → Check Price."),
    (r"\bwho are you\b", "I'm the **Obsidian Clan Bot** – your Warframe clan assistant! Use **`/help`** to explore what I can do."),
]


def _strip_mention(content: str, bot_id: int) -> str:
    """Remove bot mention from message content and return trimmed query."""
    cleaned = re.sub(rf"<@!?{bot_id}>", "", content, flags=re.IGNORECASE)
    return cleaned.strip()


def _match_keyword(query: str) -> Optional[str]:
    """Check if query matches a canned response. Returns response or None."""
    if not query or len(query) > 500:
        return None
    query_lower = query.lower()
    for pattern, response in KEYWORD_RESPONSES:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return response
    return None


async def get_ai_response(query: str, api_key: str) -> Optional[str]:
    """Call OpenAI for a conversational response. Returns None on failure."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the Obsidian Clan Bot, a friendly Discord bot for a Warframe clan. "
                        "Keep responses short (1-3 sentences). Mention relevant slash commands when helpful "
                        "(e.g. /warframe baro, /economy daily). Be casual and helpful."
                    ),
                },
                {"role": "user", "content": query[:1000]},
            ],
            max_tokens=150,
            temperature=0.7,
        )
        text = response.choices[0].message.content
        return (text or "").strip() if text else None
    except Exception as e:
        logger.warning(f"[mention_chat] OpenAI error: {e}")
        return None


async def get_mention_reply(content: str, bot_id: int, openai_api_key: Optional[str] = None) -> str:
    """
    Get reply for a mention. Tries keyword match first, then AI fallback.
    """
    query = _strip_mention(content, bot_id)
    if not query:
        return (
            "Hi! I'm the Obsidian Clan Bot. Use **`/help`** to explore commands.\n"
            "Quick links: **`/economy balance`** · **`/warframe status`** · **`/general profile`**"
        )
    canned = _match_keyword(query)
    if canned:
        return canned
    if openai_api_key:
        ai_reply = await get_ai_response(query, openai_api_key)
        if ai_reply:
            return ai_reply
    return (
        f"I'm not sure how to help with that. Use **`/help`** to explore commands, "
        "or try asking about Baro, alerts, cycles, daily, or balance!"
    )
