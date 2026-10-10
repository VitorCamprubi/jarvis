"""The tool registry: the explicit allowlist of everything JARVIS can do (ADR-020).

To add a tool, write a module with a ``Tool`` subclass and add one line to ``build_tools``.
Nothing else can run: there is no generic shell or code-execution tool, and none deletes files.
"""

from typing import Any

from jarvis.config import AppConfig
from jarvis.tools.apps import AppIndex, OpenAppTool
from jarvis.tools.base import Intent, Reply, Tool, ToolResult
from jarvis.tools.close import CloseAppTool
from jarvis.tools.lock import LockTool
from jarvis.tools.media import MediaTool
from jarvis.tools.power import PowerTool
from jarvis.tools.sites import OpenSiteTool
from jarvis.tools.system import SystemStatusTool
from jarvis.tools.volume import VolumeTool
from jarvis.windows.volume import MasterVolume


def build_tools(config: AppConfig, app_index: AppIndex) -> list[Tool[Any]]:
    """All tools, in the order the router tries them: specific phrasings before generic ones
    ("open <anything>" comes last)."""
    return [
        SystemStatusTool(),
        MediaTool(),
        VolumeTool(MasterVolume(), config.volume.step),
        LockTool(),
        PowerTool(),
        CloseAppTool(config.apps.match_threshold),
        OpenSiteTool(config.sites.favorites),
        OpenAppTool(app_index, config.apps.aliases),
    ]


__all__ = ["AppIndex", "Intent", "Reply", "Tool", "ToolResult", "build_tools"]
