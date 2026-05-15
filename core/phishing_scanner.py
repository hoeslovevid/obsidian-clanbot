"""
Lightweight phishing / scam link heuristics for flag-only moderation helpers.

Never blocks, deletes, or punishes — callers only react or log.  Patterns are
high-signal substring and URL checks after Unicode normalization.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Documented suspicious substrings (case-insensitive after normalization).
# Kept intentionally small — expand only when a pattern is consistently abusive.
# - Typosquats of major platforms
# - “free nitro” style scams
# ---------------------------------------------------------------------------
_PHISH_SUBSTRINGS: tuple[str, ...] = (
    "steamcomnunity",
    "steamcommunty",
    "discord-nitro-free",
    "gift-nitro",
    "free-nitro",
    "dlscord",
)

# Homoglyphs commonly used to spell “discord” / hostnames with Latin lookalikes.
_HOMOGLYPHS = str.maketrans(
    {
        "\u0430": "a",  # Cyrillic small a
        "\u0435": "e",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0443": "y",
        "\u0445": "x",
        "\u0456": "i",
        "\u0458": "j",
    }
)

_URL_RE = re.compile(r"https?://[^\s<>`\"]+|www\.[^\s<>`\"]+", re.IGNORECASE)
# Shorteners + scam-adjacent bait words in the same message (very coarse).
_BITLY_RE = re.compile(r"bit\.ly/[^\s)\]>]+", re.IGNORECASE)
_BAIT_RE = re.compile(
    r"\b(nitro|discord\s*gift|gift\s*discord|steam\s*gift|login|verify|claim|free)\b",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = s.translate(_HOMOGLYPHS)
    return s.casefold()


def _extract_hosts(text: str) -> list[str]:
    hosts: list[str] = []
    for m in _URL_RE.finditer(text):
        raw = m.group(0)
        if raw.lower().startswith("www."):
            u = "http://" + raw
        else:
            u = raw
        try:
            p = urlparse(u)
            h = (p.hostname or "").casefold()
            if h:
                hosts.append(h)
        except Exception:
            continue
    return hosts


def normalize_domain(domain: str) -> str:
    """Hostname for allowlist storage / compare: lowercase, no scheme or path."""
    d = (domain or "").strip()
    if "://" in d:
        try:
            d = urlparse(d).hostname or d
        except Exception:
            d = (domain or "").strip()
    d = d.rstrip(".").split("/")[0].split(":")[0]
    return d.casefold() if d else ""


def message_looks_phishy(content: str, allow_domains: frozenset[str]) -> bool:
    """
    Return True if *content* matches heuristic scam patterns.

    *allow_domains*: set of normalized hostnames (e.g. ``steampowered.com``).
    If every URL host in the message is allowlisted and there is no separate
    substring signal, returns False.
    """
    if not (content or "").strip():
        return False

    folded = _normalize_text(content)

    substring_hit = any(p in folded for p in _PHISH_SUBSTRINGS)
    bitly_hit = bool(_BITLY_RE.search(content))
    bitly_bait = bitly_hit and bool(_BAIT_RE.search(folded))

    hosts = _extract_hosts(content)
    if hosts and allow_domains:
        norm_hosts = [h.casefold() for h in hosts]
        if all(h in allow_domains or any(h.endswith("." + a) for a in allow_domains) for h in norm_hosts):
            # All linked hosts are allowlisted; only flag if we still see typos / bait elsewhere.
            if not substring_hit and not bitly_bait:
                return False

    return substring_hit or bitly_bait
