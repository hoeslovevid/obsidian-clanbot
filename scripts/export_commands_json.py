"""Generate web/assets/commands.json from bot sources (no Discord import)."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "assets" / "commands.json"


def main() -> None:
    surf = (ROOT / "core" / "command_surface.py").read_text(encoding="utf-8")
    discovery = [
        {"path": a, "blurb": b}
        for a, b in re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', surf)
    ]

    loader = (ROOT / "core" / "commands_loader.py").read_text(encoding="utf-8")
    groups = [
        {"path": m.group(1), "description": m.group(2)}
        for m in re.finditer(
            r'Group\(\s*name="([a-z0-9_]+)",\s*description="([^"]+)"',
            loader,
        )
    ]

    cmds: list[dict] = []
    seen: set[str] = set()
    for p in (ROOT / "commands").rglob("*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
            r'\.command\(\s*name\s*=\s*["\']([^"\']+)["\']\s*,\s*description\s*=\s*["\']([^"\']+)["\']',
            text,
        ):
            name, desc = m.group(1), m.group(2)
            if name in seen:
                continue
            seen.add(name)
            cmds.append({"name": name, "description": desc})

    # Also catch @app_commands.command style
    for p in (ROOT / "commands").rglob("*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
            r'@app_commands\.command\(\s*name\s*=\s*["\']([^"\']+)["\']\s*,\s*description\s*=\s*["\']([^"\']+)["\']',
            text,
        ):
            name, desc = m.group(1), m.group(2)
            if name in seen:
                continue
            seen.add(name)
            cmds.append({"name": name, "description": desc})

    cmds.sort(key=lambda x: x["name"])
    OUT.write_text(
        json.dumps(
            {
                "generated": True,
                "discovery": discovery,
                "groups": groups,
                "commands": cmds,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT} discovery={len(discovery)} groups={len(groups)} commands={len(cmds)}")


if __name__ == "__main__":
    main()
