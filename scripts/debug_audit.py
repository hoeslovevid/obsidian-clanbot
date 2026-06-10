"""One-shot health audit — writes NDJSON to debug-42c590.log."""
from __future__ import annotations

import importlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "debug-42c590.log"
SESSION = "42c590"


def _log(hypothesis_id: str, location: str, message: str, data: dict, run_id: str = "audit") -> None:
    entry = {
        "sessionId": SESSION,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def audit_imports() -> None:
    text = (ROOT / "core" / "commands_loader.py").read_text(encoding="utf-8")
    names = re.findall(r'"(commands\.[^"]+)"', text)
    ordered: list[str] = []
    seen: set[str] = set()
    for n in names:
        if n.startswith("commands.") and n not in seen:
            seen.add(n)
            ordered.append(n)
    errors = []
    for m in ordered:
        try:
            importlib.import_module(m)
        except Exception as e:
            errors.append({"module": m, "error": f"{type(e).__name__}: {e}"})
    _log("H-import", "scripts/debug_audit.py", "command module imports", {
        "total": len(ordered),
        "failed": len(errors),
        "errors": errors,
    })


def audit_dateparser() -> None:
    import dateparser

    cases = [
        ("poll_duration", "2 hours", {"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True, "RELATIVE_BASE": datetime.now(timezone.utc)}),
        ("reminder", "in 1 hour", {"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True, "RELATIVE_BASE": datetime.now(timezone.utc)}),
    ]
    results = []
    for name, text, settings in cases:
        try:
            # Must not pass relative_base kwarg (dateparser 1.2.x)
            parsed = dateparser.parse(text, settings=settings)
            results.append({"case": name, "ok": parsed is not None, "value": str(parsed) if parsed else None})
        except Exception as e:
            results.append({"case": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
    _log("H-dateparser", "scripts/debug_audit.py", "dateparser relative parse", {"results": results})


def audit_refresh_defer() -> None:
    """Scan warframe commands for refresh handlers missing defer()."""
    suspects = []
    for path in (ROOT / "commands").rglob("*.py"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        if "RefreshView" not in src and "refresh_callback" not in src:
            continue
        for match in re.finditer(
            r"async def (on_\w+|refresh_\w+)\([^)]*Interaction[^)]*\):.*?(?=\n    (?:async )?def |\nclass |\Z)",
            src,
            re.DOTALL,
        ):
            body = match.group(0)
            if "RefreshView" in body or "refresh" in match.group(1).lower():
                has_defer = "response.defer" in body
                if not has_defer and "message.edit" in body:
                    suspects.append({
                        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "handler": match.group(1),
                    })
    _log("H-refresh", "scripts/debug_audit.py", "refresh handlers without defer", {"suspects": suspects})


def main() -> None:
    audit_imports()
    audit_dateparser()
    audit_refresh_defer()
    print(f"Audit complete — see {LOG}")


if __name__ == "__main__":
    main()
