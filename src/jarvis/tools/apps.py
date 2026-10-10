"""Open any app from the Start menu, by approximate name or configured alias (ADR-021)."""

import asyncio
import logging
import re
import string
import time
import webbrowser
from collections.abc import Callable, Mapping

from pydantic import BaseModel, Field
from rapidfuzz import process

from jarvis.text import name_score, normalize
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.start_menu import StartApp, launch, load_start_apps

log = logging.getLogger(__name__)

VERSION_SUFFIX = re.compile(r"\s+\d+(?:\.\d+)+.*$")


def spoken_name(app_name: str) -> str:
    """'IntelliJ IDEA 2026.2.3' -> 'IntelliJ IDEA': version numbers are not worth saying."""
    return VERSION_SUFFIX.sub("", app_name)


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


class AppIndex:
    """The Start menu's apps, loaded in the background and reloaded when stale."""

    def __init__(
        self,
        threshold: int,
        max_age_s: float,
        loader: Callable[[], list[StartApp]] = load_start_apps,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._max_age_s = max_age_s
        self._loader = loader
        self._clock = clock
        self._apps: list[StartApp] = []
        self._names: list[str] = []
        self._loaded_at = float("-inf")
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        apps = await asyncio.to_thread(self._loader)
        self._apps = apps
        # Version numbers are noise when matching: "intelij" vs "IntelliJ IDEA 2026.2.3".
        self._names = [normalize(spoken_name(app.name)) for app in apps]
        self._loaded_at = self._clock()
        log.info("Start menu index: %d apps", len(apps))

    async def find(self, query: str) -> StartApp | None:
        async with self._lock:  # one reload at a time, even if several requests arrive
            if not self._apps or self._clock() - self._loaded_at > self._max_age_s:
                await self.refresh()
        best = process.extractOne(
            normalize(query), self._names, scorer=name_score, score_cutoff=self._threshold
        )
        return None if best is None else self._apps[best[2]]


class OpenAppParams(BaseModel):
    # Two characters at least: a lone article ("abre o") must not open a random app.
    name: str = Field(min_length=2, description="The app's name as the user said it")


class OpenAppTool(Tool[OpenAppParams]):
    name = "open_app"
    description = "Open an application installed on this PC (anything in the Start menu)."
    params_model = OpenAppParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:abre|abra|abrir|inicia|inicie|iniciar|executa|execute|executar|roda|rode)"
                r"(?: (?:o|a|os|as|meu|minha))?(?: (?:app|aplicativo|programa))?"
                r"(?: (?:do|da|de))? (?P<name>.+)"
            ),
        ),
        en=(
            Intent(
                r"(?:open|launch|start|run|fire up)(?: (?:the|my|up))?"
                r"(?: (?:app|application|program))? (?P<name>.+)"
            ),
        ),
    )

    def __init__(
        self,
        index: AppIndex,
        aliases: Mapping[str, str],
        start: Callable[[StartApp], None] = launch,
        open_url: Callable[[str], object] = webbrowser.open,
    ) -> None:
        self._index = index
        self._aliases = {normalize(spoken): target for spoken, target in aliases.items()}
        self._start = start
        self._open_url = open_url

    async def run(self, params: OpenAppParams) -> ToolResult:
        spoken = normalize(params.name)
        target = self._aliases.get(spoken, params.name)
        if is_url(target):  # e.g. "browser" -> a page in the default browser
            self._open_url(target)
            return ToolResult(Reply("apps.opening", {"app": string.capwords(spoken)}))
        app = await self._index.find(target)
        if app is None:
            return ToolResult(Reply("apps.not_found", {"name": params.name}, cacheable=False))
        self._start(app)
        return ToolResult(Reply("apps.opening", {"app": spoken_name(app.name)}))
