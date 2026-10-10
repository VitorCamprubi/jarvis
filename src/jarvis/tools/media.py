"""Play/pause, next and previous track through the media keys (ADR-022)."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.keys import (
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    press_key,
)

KEYS = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "previous": VK_MEDIA_PREV_TRACK,
}
PLAY_PAUSE = {"action": "play_pause"}
NEXT = {"action": "next"}
PREVIOUS = {"action": "previous"}


class MediaParams(BaseModel):
    # Play and pause are the same key: the player decides from its current state.
    action: Literal["play_pause", "next", "previous"]


class MediaTool(Tool[MediaParams]):
    name = "media"
    description = "Control the music or video player: toggle play/pause, next or previous track."
    params_model = MediaParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:pausa|pause|pausar)(?: (?:a|o))?(?: (?:musica|som|video|reproducao))?",
                PLAY_PAUSE,
            ),
            Intent(r"(?:para|pare|parar) (?:a|o) (?:musica|som|video|reproducao)", PLAY_PAUSE),
            Intent(
                r"(?:toca|toque|tocar|continua|continue|continuar|retoma|retome|retomar|despausa"
                r"|despause)(?: (?:a|o))?(?: (?:musica|som|video|reproducao))?",
                PLAY_PAUSE,
            ),
            Intent(r"(?:da|de|aperta) (?:o )?play|play", PLAY_PAUSE),
            Intent(
                r"(?:proxima|proximo)(?: (?:musica|faixa|video))?|(?:musica|faixa) seguinte", NEXT
            ),
            Intent(
                r"(?:pula|pule|pular|avanca|avance|avancar|passa|passe)"
                r"(?: (?:a|o|essa|esta))?(?: (?:musica|faixa|video))?",
                NEXT,
            ),
            Intent(r"(?:musica|faixa|video) anterior|anterior", PREVIOUS),
            Intent(
                r"(?:volta|volte|voltar)(?: (?:a|o|uma|para a|pra))? (?:musica|faixa|video)"
                r"(?: anterior)?",
                PREVIOUS,
            ),
        ),
        en=(
            Intent(
                r"(?:pause|play|resume|unpause|continue)"
                r"(?: (?:the )?(?:music|song|video|playback|track))?",
                PLAY_PAUSE,
            ),
            Intent(r"stop (?:the )?(?:music|song|video|playback)", PLAY_PAUSE),
            Intent(
                r"(?:next|skip)(?: (?:this |the )?(?:song|track|video|one))?"
                r"|play (?:the )?next (?:song|track)",
                NEXT,
            ),
            Intent(
                r"(?:previous|last)(?: (?:song|track|video))?|go back(?: (?:a|one) (?:song|track))?"
                r"|play (?:the )?previous (?:song|track)",
                PREVIOUS,
            ),
        ),
    )

    def __init__(self, press: Callable[[int], None] = press_key) -> None:
        self._press = press

    async def run(self, params: MediaParams) -> ToolResult:
        self._press(KEYS[params.action])
        return ToolResult(Reply(f"media.{params.action}"))
