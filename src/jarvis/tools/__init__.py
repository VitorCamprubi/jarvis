"""The tool registry: the explicit allowlist of everything JARVIS can do (ADR-020).

To add a tool, write a module with a ``Tool`` subclass and add one line to ``build_tools``.
Nothing else can run: there is no generic shell or code-execution tool, and none deletes files.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.config import AppConfig
from jarvis.core.language import LanguagePolicy
from jarvis.i18n import Language
from jarvis.tools.apps import AppIndex, OpenAppTool
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, render
from jarvis.tools.close import CloseAppTool
from jarvis.tools.files import FileIndex, OpenResultTool, ResultList, SearchFilesTool
from jarvis.tools.language import SetLanguageTool
from jarvis.tools.lock import LockTool
from jarvis.tools.media import MediaTool
from jarvis.tools.power import PowerTool
from jarvis.tools.reminders import (
    CancelReminderTool,
    CreateReminderTool,
    ListRemindersTool,
    ReminderService,
)
from jarvis.tools.sites import OpenSiteTool
from jarvis.tools.system import SystemStatusTool
from jarvis.tools.volume import VolumeTool
from jarvis.tools.weather import WeatherClient, WeatherTool
from jarvis.windows.volume import MasterVolume


@dataclass(frozen=True)
class Services:
    """Long-lived objects the tools share, built by the composition root (app.py)."""

    app_index: AppIndex
    file_index: FileIndex
    results: ResultList
    weather: WeatherClient
    reminders: ReminderService
    language: LanguagePolicy
    reply_language: Callable[[], Language]  # the language JARVIS is answering in right now


def build_tools(config: AppConfig, services: Services) -> list[Tool[Any]]:
    """All tools, in the order the router tries them: specific phrasings before generic ones
    ("open the second one" before "open <anything>", which comes last)."""
    return [
        SystemStatusTool(),
        MediaTool(),
        VolumeTool(MasterVolume(), config.volume.step),
        LockTool(),
        PowerTool(),
        CloseAppTool(config.apps.match_threshold),
        SetLanguageTool(services.language),
        CreateReminderTool(
            services.reminders, services.reply_language, config.reminders.default_hour
        ),
        ListRemindersTool(services.reminders),
        CancelReminderTool(services.reminders),
        WeatherTool(services.weather, config.weather, services.reply_language),
        OpenResultTool(services.results),
        SearchFilesTool(
            services.file_index,
            services.results,
            config.files.max_results,
            config.files.match_threshold,
        ),
        OpenSiteTool(config.sites.favorites),
        OpenAppTool(services.app_index, config.apps.aliases),
    ]


__all__ = [
    "AppIndex",
    "FileIndex",
    "Intent",
    "Reply",
    "ResultList",
    "Services",
    "Tool",
    "ToolResult",
    "WeatherClient",
    "build_tools",
    "render",
]
