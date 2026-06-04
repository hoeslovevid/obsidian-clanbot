"""Central embed image URLs and category art (Obsidian brand)."""
from __future__ import annotations

import os
from pathlib import Path

from core.config import BOT_WEBSITE, GITHUB_RAW_REPO, PROJECT_ROOT, EMBED_BANNER_URL as _ENV_BANNER

# Default: GitHub raw after deploy; override with EMBED_BANNER_URL
_DEFAULT_BANNER = (
    f"https://raw.githubusercontent.com/{GITHUB_RAW_REPO}/main/"
    f"obsidian_clanbot/assets/obsidian_embed_banner.png"
)

EMBED_BANNER_URL = _ENV_BANNER or _DEFAULT_BANNER
EMBED_LOGO_URL = os.getenv("EMBED_LOGO_URL", "").strip() or None

# Category thumbnails (small icons, top-right)
CATEGORY_THUMBNAILS: dict[str, str] = {
    "warframe": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f3ae.png",
    "economy": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f4b0.png",
    "moderation": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f6e1.png",
    "community": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f465.png",
    "general": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f48e.png",
    "prestige": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/2b50.png",
    "error": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/26a0.png",
    "warning": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f4a1.png",
}

# Large banner images per template variant
TEMPLATE_IMAGES: dict[str, str] = {
    "showcase": EMBED_BANNER_URL,
    "error": EMBED_BANNER_URL,
    "levelup_low": EMBED_BANNER_URL,
    "levelup_mid": EMBED_BANNER_URL,
    "levelup_high": EMBED_BANNER_URL,
}

# Warframe sub-variant thumbnails
WARFRAME_VARIANT_THUMBNAILS: dict[str, str] = {
    "baro": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f6d2.png",
    "fissures": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f48e.png",
    "cycles": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f319.png",
    "world_state": "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/1f30d.png",
}

PLATFORM_EMOJI: dict[str, str] = {
    "pc": "🖥️",
    "xbox": "🎮",
    "ps4": "🎮",
    "switch": "🕹️",
}

COMPLAINT_SEVERITY_COLORS: dict[str, str] = {
    "low": "#52C97B",
    "medium": "#FAA61A",
    "high": "#E05252",
    "critical": "#992D22",
}

# Category keyword → severity (longest / explicit keys checked via substring match)
COMPLAINT_CATEGORY_SEVERITY: dict[str, str] = {
    "dox": "critical",
    "doxxing": "critical",
    "threat": "critical",
    "violence": "critical",
    "harassment": "high",
    "harass": "high",
    "bully": "high",
    "hate": "high",
    "trade": "medium",
    "scam": "medium",
    "voice": "medium",
    "conduct": "medium",
    "application": "medium",
    "spam": "low",
    "other": "low",
    "general": "low",
}


def complaint_severity_for_category(category: str) -> str:
    """Map a complaint category label to a severity preset (low/medium/high/critical)."""
    key = (category or "").strip().lower()
    if not key:
        return "medium"
    for pattern, severity in COMPLAINT_CATEGORY_SEVERITY.items():
        if pattern in key:
            return severity
    return "medium"

LOCAL_BANNER_PATH = PROJECT_ROOT / "assets" / "obsidian_embed_banner.png"


def local_banner_exists() -> bool:
    return LOCAL_BANNER_PATH.is_file()
