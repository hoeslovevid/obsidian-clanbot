"""Dojo research progress helpers."""
from __future__ import annotations

import json
import re
from typing import Any


def _parse_resources(raw: str | None) -> dict[str, float]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {str(k): float(v) for k, v in data.items() if _is_number(v)}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    out: dict[str, float] = {}
    for part in re.split(r"[,;\n]+", text):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, val = part.split(":", 1)
        elif "=" in part:
            key, val = part.split("=", 1)
        else:
            continue
        key = key.strip()
        val = val.strip().replace(",", "")
        if key and _is_number(val):
            out[key] = float(val)
    return out


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def compute_dojo_progress(required: str | None, current: str | None) -> tuple[float, str]:
    """Return overall percent (0–100) and a short resource summary line."""
    req = _parse_resources(required)
    cur = _parse_resources(current)
    if not req:
        return 0.0, "No resource targets set"
    parts: list[str] = []
    pcts: list[float] = []
    for key, need in req.items():
        have = cur.get(key, 0.0)
        pct = min(100.0, (100.0 * have / need) if need > 0 else 100.0)
        pcts.append(pct)
        parts.append(f"{key}: {int(have):,}/{int(need):,}")
    overall = sum(pcts) / len(pcts) if pcts else 0.0
    return overall, " · ".join(parts[:4])
