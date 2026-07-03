from typing import Any

class YoutubeDL:
    def __init__(self, params: dict[str, Any] | None = None) -> None: ...
    def extract_info(self, url: str, download: bool = True) -> Any: ...

class utils:
    bug_reports_message: Any

def __getattr__(name: str) -> Any: ...
