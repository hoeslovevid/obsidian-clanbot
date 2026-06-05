"""Central embed image URLs and category art (Obsidian brand).

Banner: set ``EMBED_BANNER_URL`` in Railway/your host env to a public HTTPS image
(e.g. raw GitHub ``assets/obsidian_embed_banner.png``). Local dev can use the file at
``assets/obsidian_embed_banner.png`` (see ``LOCAL_BANNER_PATH``).

Logo: optional ``EMBED_LOGO_URL`` — used as footer icon and general-category thumbnail
when set (square PNG recommended, 128–256px). Set on Railway as a public HTTPS URL.

Per-category thumbnail overrides (optional): set ``CATEGORY_THUMBNAIL_OVERRIDES`` to a JSON
object mapping category keys to URLs, e.g.
``{"warframe":"https://…","economy":"https://…"}``.
Individual env vars ``EMBED_THUMB_WARFRAME``, ``EMBED_THUMB_ECONOMY``, etc. also work.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.config import GITHUB_RAW_REPO, PROJECT_ROOT, EMBED_BANNER_URL as _ENV_BANNER, EMBED_LOGO_URL

# Default: GitHub raw after deploy; override with EMBED_BANNER_URL on Railway
_DEFAULT_BANNER = (
    f"https://raw.githubusercontent.com/{GITHUB_RAW_REPO}/main/"
    f"assets/obsidian_embed_banner.png"
)

EMBED_BANNER_URL = _ENV_BANNER or _DEFAULT_BANNER

# Category thumbnails — Twemoji CDN (neutral cross-platform); general may use EMBED_LOGO_URL
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


def _load_category_overrides() -> dict[str, str]:
    """Optional JSON env or per-category EMBED_THUMB_* vars."""
    overrides: dict[str, str] = {}
    raw_json = os.getenv("CATEGORY_THUMBNAIL_OVERRIDES", "").strip()
    if raw_json:
        try:
            import json

            data = json.loads(raw_json)
            if isinstance(data, dict):
                overrides.update({str(k).lower(): str(v) for k, v in data.items() if v})
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    for key in CATEGORY_THUMBNAILS:
        env_val = os.getenv(f"EMBED_THUMB_{key.upper()}", "").strip()
        if env_val:
            overrides[key] = env_val
    return overrides


_CATEGORY_OVERRIDES = _load_category_overrides()


def category_thumbnail(category: str) -> str:
    """Thumbnail URL for a category; ``EMBED_LOGO_URL`` overrides ``general`` when set."""
    cat = (category or "general").strip().lower()
    if cat in _CATEGORY_OVERRIDES:
        return _CATEGORY_OVERRIDES[cat]
    if cat == "general" and EMBED_LOGO_URL:
        return EMBED_LOGO_URL
    return CATEGORY_THUMBNAILS.get(cat, CATEGORY_THUMBNAILS["general"])

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

TICKET_PRIORITY_COLORS: dict[str, str] = {
    "normal": "#52C97B",
    "urgent": "#E05252",
}

TICKET_STATUS_COLORS: dict[str, str] = {
    "open": "#7C83FF",
    "awaiting_staff": "#FAA61A",
    "awaiting_member": "#57F287",
    "closed": "#72767D",
    "claimed": "#FAA61A",
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
