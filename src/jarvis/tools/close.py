"""Close a running program gracefully, after a spoken "yes" (ADR-024, ADR-025)."""

import asyncio
import string
from collections.abc import Callable, Iterable, Mapping, Sequence

from pydantic import BaseModel, Field

from jarvis.text import name_score, normalize
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.desktop import AppWindow, close_windows, list_app_windows

# Store apps all run inside ApplicationFrameHost: such a window stands only for itself.
STORE_APP_HOST = "applicationframehost"
NOT_PROGRAMS = {"computador", "pc", "maquina", "sistema", "notebook", "computer", "machine"}


def find_app_windows(query: str, windows: Sequence[AppWindow], threshold: float) -> list[AppWindow]:
    """The windows of the program that best matches ``query`` (by process name or title)."""
    spoken = normalize(query)
    best: AppWindow | None = None
    best_score = 0.0
    for window in windows:
        score = max(
            name_score(spoken, normalize(window.process)),
            name_score(spoken, normalize(window.title)),
        )
        if score > best_score:
            best, best_score = window, score
    if best is None or best_score < threshold:
        return []
    if best.process.lower() == STORE_APP_HOST:
        return [best]
    return [window for window in windows if window.process == best.process]


class CloseAppParams(BaseModel):
    name: str = Field(min_length=2, description="The program's name as the user said it")


class CloseAppTool(Tool[CloseAppParams]):
    name = "close_app"
    description = (
        "Close a running program gracefully, like clicking its X (it may ask to save). "
        "JARVIS asks for spoken confirmation first."
    )
    params_model = CloseAppParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:fecha|feche|fechar|encerra|encerre|encerrar|finaliza|finalize|finalizar)"
                r"(?: (?:o|a|os|as|meu|minha))?(?: (?:app|aplicativo|programa|janela))?"
                r"(?: (?:do|da|de))? (?P<name>.+)"
            ),
        ),
        en=(
            Intent(
                r"(?:close|quit|exit|kill|terminate)(?: (?:the|my|out of))?"
                r"(?: (?:app|application|program|window))?(?: (?:of|for))? (?P<name>.+)"
            ),
        ),
    )

    def __init__(
        self,
        threshold: float,
        list_windows: Callable[[], list[AppWindow]] = list_app_windows,
        close: Callable[[Iterable[AppWindow]], None] = close_windows,
    ) -> None:
        self._threshold = threshold
        self._list_windows = list_windows
        self._close = close

    def accepts(self, args: Mapping[str, object]) -> bool:
        return normalize(str(args.get("name", ""))) not in NOT_PROGRAMS

    async def run(self, params: CloseAppParams) -> ToolResult:
        windows = await asyncio.to_thread(self._list_windows)
        targets = find_app_windows(params.name, windows, self._threshold)
        app = string.capwords(normalize(params.name))
        if not targets:
            return ToolResult(Reply("close.not_running", {"app": app}, cacheable=False))

        async def execute() -> ToolResult:
            await asyncio.to_thread(self._close, targets)
            return ToolResult(Reply("close.closing", {"app": app}, cacheable=False))

        return ToolResult(Reply("close.confirm", {"app": app}, cacheable=False), on_confirm=execute)
