"""NDJSON debug logging for agent debug sessions (remove after verification)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from core.config import PROJECT_ROOT

_SESSION = "42c590"
_LOG = PROJECT_ROOT / "data" / "debug-42c590.log"


def agent_log(
    location: str,
    message: str,
    *,
    data: dict | None = None,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION,
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
            "runId": run_id,
        }
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
    # #endregion
