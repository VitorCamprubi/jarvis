"""Master volume: set a percentage, up/down, mute/unmute, or say the current level (ADR-022)."""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from jarvis.text import parse_number
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.volume import Volume

AMOUNT = r"(?P<{name}>[a-z0-9 ]+?)(?: ?%| por cento| percent)?"
LEVEL = AMOUNT.format(name="level")
STEP = AMOUNT.format(name="step")
SOUND_PT = r"(?:o )?(?:volume|som|audio)"
SOUND_EN = r"(?:the )?(?:volume|sound|audio)"


class VolumeParams(BaseModel):
    action: Literal["set", "up", "down", "mute", "unmute", "get"]
    level: int | None = Field(default=None, ge=0, le=100, description="Target %, for 'set'")
    step: int | None = Field(
        default=None, ge=1, le=100, description="Change in percentage points, for 'up'/'down'"
    )

    @field_validator("level", "step", mode="before")
    @classmethod
    def _spoken_number(cls, value: object) -> object:
        """The router passes what was said ("trinta", "30%"); the LLM passes numbers."""
        if isinstance(value, str):
            number = parse_number(value)
            if number is None:
                raise ValueError(f"not a number: {value!r}")
            return number
        return value

    @model_validator(mode="after")
    def _set_needs_level(self) -> Self:
        if self.action == "set" and self.level is None:
            raise ValueError("'set' needs a level")
        return self


def _intents(action: str, *patterns: str) -> tuple[Intent, ...]:
    return tuple(Intent(pattern, {"action": action}) for pattern in patterns)


class VolumeTool(Tool[VolumeParams]):
    name = "volume"
    description = "Change or report the PC's master volume (percent), or mute/unmute it."
    params_model = VolumeParams
    # Specific phrasings come first; the bare "volume <level>" pattern is last.
    intents = phrasings(
        pt=(
            *_intents(
                "get",
                r"qual (?:e |eh )?o volume(?: atual)?",
                r"(?:em )?quanto (?:esta|ta) o volume",
            ),
            *_intents(
                "unmute",
                rf"(?:desmuta|desmute|desmutar)(?: {SOUND_PT}| o (?:pc|computador))?",
                r"(?:tira|tire) do mudo|(?:volta|ativa|liga|religa) o (?:som|audio)",
            ),
            *_intents(
                "mute",
                rf"(?:muta|mute|mutar|silencia|silencie|silenciar)"
                rf"(?: {SOUND_PT}| o (?:pc|computador))?",
                r"(?:tira|tire|corta|corte) o (?:som|audio)|(?:modo )?(?:mudo|silencio)",
            ),
            *_intents(
                "set",
                rf"(?:aumenta|aumente|sobe|suba|diminui|diminua|abaixa|abaixe|baixa|baixe) "
                rf"{SOUND_PT} (?:para|pra|ate) {LEVEL}",
            ),
            *_intents(
                "up",
                rf"(?:aumenta|aumente|aumentar|sobe|suba|subir)(?: um pouco)? {SOUND_PT}"
                rf"(?: em {STEP})?",
                r"(?:mais alto|aumenta|sobe o som)",
            ),
            *_intents(
                "down",
                rf"(?:diminui|diminua|diminuir|abaixa|abaixe|abaixar|baixa|baixe)(?: um pouco)? "
                rf"{SOUND_PT}(?: em {STEP})?",
                r"(?:mais baixo|abaixa|diminui)",
            ),
            *_intents(
                "set",
                rf"(?:(?:coloca|coloque|poe|ponha|deixa|deixe|bota|ajusta|ajuste|muda|mude|define"
                rf"|defina) )?(?:o )?volume (?:em |para |pra |no |a )?{LEVEL}",
            ),
        ),
        en=(
            *_intents("get", r"what(?:s| is) the (?:current )?volume|how loud is it"),
            *_intents(
                "unmute",
                rf"unmute(?: {SOUND_EN}| (?:the )?(?:pc|computer))?|turn the sound back on",
            ),
            *_intents(
                "mute",
                rf"(?:mute|silence)(?: {SOUND_EN}| (?:the )?(?:pc|computer))?",
            ),
            *_intents(
                "up",
                rf"(?:turn (?:it |{SOUND_EN} )?up|volume up|louder|(?:raise|increase|boost) "
                rf"{SOUND_EN})(?: by {STEP})?",
            ),
            *_intents(
                "down",
                rf"(?:turn (?:it |{SOUND_EN} )?down|volume down|quieter|softer|(?:lower|decrease"
                rf"|reduce) {SOUND_EN})(?: by {STEP})?",
            ),
            *_intents(
                "set",
                rf"(?:(?:set|put|change|turn) )?(?:the )?volume (?:to |at )?{LEVEL}",
            ),
        ),
    )

    def __init__(self, volume: Volume, default_step: int) -> None:
        self._volume = volume
        self._default_step = default_step

    async def run(self, params: VolumeParams) -> ToolResult:
        state = await self._volume.get()
        match params.action:
            case "get":
                key = "volume.current_muted" if state.muted else "volume.current"
                return ToolResult(Reply(key, {"level": state.level}))
            case "mute":
                await self._volume.set_muted(True)
                return ToolResult(Reply("volume.muted"))
            case "unmute":
                await self._volume.set_muted(False)
                return ToolResult(Reply("volume.unmuted"))
            case "set":
                level = params.level if params.level is not None else state.level
            case "up":
                level = min(100, state.level + (params.step or self._default_step))
            case "down":
                level = max(0, state.level - (params.step or self._default_step))
        await self._volume.set_level(level)
        if state.muted:  # asking for a level means wanting to hear it
            await self._volume.set_muted(False)
        return ToolResult(Reply("volume.set", {"level": level}))
