"""Shut down or restart the PC, only after a spoken "yes" (ADR-025)."""

import asyncio
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.session import shut_down

DELAY_S = 5  # long enough for JARVIS to finish saying goodbye
TARGET_PT = r"(?: (?:o|a|meu|minha))? (?:computador|pc|maquina|sistema|notebook)(?: agora)?"
TARGET_EN = r"(?: (?:the|my))? (?:computer|pc|machine|system|laptop)(?: now)?"


class PowerParams(BaseModel):
    action: Literal["shutdown", "restart"]


class PowerTool(Tool[PowerParams]):
    name = "power"
    description = "Shut down or restart the PC. JARVIS asks for spoken confirmation first."
    params_model = PowerParams
    intents = phrasings(
        pt=(
            Intent(rf"(?:desliga|desligue|desligar){TARGET_PT}", {"action": "shutdown"}),
            Intent(
                rf"(?:reinicia|reinicie|reiniciar|reinicializa|reinicialize){TARGET_PT}",
                {"action": "restart"},
            ),
        ),
        en=(
            Intent(
                rf"(?:shut ?down|turn off|power off|switch off){TARGET_EN}"
                r"|shut (?:the |my )?(?:computer|pc) down",
                {"action": "shutdown"},
            ),
            Intent(rf"(?:restart|reboot){TARGET_EN}", {"action": "restart"}),
        ),
    )

    def __init__(self, shutdown: Callable[[bool, int], None] = shut_down) -> None:
        self._shutdown = shutdown

    async def run(self, params: PowerParams) -> ToolResult:
        restart = params.action == "restart"

        async def execute() -> ToolResult:
            await asyncio.to_thread(self._shutdown, restart, DELAY_S)
            return ToolResult(Reply("power.restarting" if restart else "power.shutting_down"))

        return ToolResult(Reply(f"power.confirm_{params.action}"), on_confirm=execute)
