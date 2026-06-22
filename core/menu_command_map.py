"""Map slash command paths to /menu labels for discovery hints."""
from __future__ import annotations

from commands.general.menu import MENU_ITEMS


def menu_label_for_command(qualified_name: str) -> str | None:
    """Return a /menu label when this command appears in MENU_ITEMS."""
    q = (qualified_name or "").strip().lower()
    if not q:
        return None
    parts = q.split()
    slug = parts[-1] if parts else q
    for label, _emoji, path, _hint in MENU_ITEMS:
        if not path:
            continue
        path_slug = path[-1].lower()
        path_full = " ".join(path).lower()
        if path_full == q or path_slug == slug or (len(parts) == 1 and path_slug == q):
            return label
    return None
