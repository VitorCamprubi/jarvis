"""Apps listed in the Start menu, from PowerShell's Get-StartApps (ADR-021)."""

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

GET_START_APPS = [
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress",
]
TIMEOUT_S = 30
NOT_APPS = re.compile(r"uninstall|desinstal", re.IGNORECASE)


@dataclass(frozen=True)
class StartApp:
    name: str  # as shown in the Start menu
    app_id: str  # AppUserModelID or path, launchable through shell:AppsFolder


def parse_start_apps(raw_json: str) -> list[StartApp]:
    data: Any = json.loads(raw_json) if raw_json.strip() else []
    if isinstance(data, dict):  # ConvertTo-Json emits an object, not a list, for one item
        data = [data]
    apps = []
    for item in data:
        name = str(item.get("Name") or "").strip()
        app_id = str(item.get("AppID") or "").strip()
        if not name or not app_id or NOT_APPS.search(name):
            continue
        if app_id.lower().startswith(("http://", "https://")):
            continue  # web links in the Start menu, not apps
        apps.append(StartApp(name, app_id))
    return apps


def load_start_apps(
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[StartApp]:
    """Blocking (~1 s): runs PowerShell."""
    result = run(
        GET_START_APPS,
        capture_output=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return parse_start_apps(result.stdout)


def launch(app: StartApp) -> None:
    """Start an app the way the Start menu does; returns immediately."""
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.app_id}"])
