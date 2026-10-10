"""Lock the PC (Windows + L)."""

from collections.abc import Callable

from pydantic import BaseModel

from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.session import lock_workstation


class LockParams(BaseModel):
    pass


class LockTool(Tool[LockParams]):
    name = "lock_pc"
    description = "Lock the PC, returning to the Windows lock screen."
    params_model = LockParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:bloqueia|bloqueie|bloquear|trava|trave|travar)(?: (?:o|a|meu|minha))? "
                r"(?:computador|pc|maquina|tela|sessao|notebook)"
            ),
        ),
        en=(
            Intent(
                r"lock(?: (?:the|my))? (?:computer|pc|machine|screen|workstation|laptop)|lock it"
            ),
        ),
    )

    def __init__(self, lock: Callable[[], None] = lock_workstation) -> None:
        self._lock = lock

    async def run(self, params: LockParams) -> ToolResult:
        self._lock()
        return ToolResult(Reply("lock.locking"))
