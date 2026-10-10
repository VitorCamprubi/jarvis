"""Phrase tables: what each spoken command routes to, in both languages."""

from typing import Any

import pytest
from fakes import FakeVolume

from jarvis.router import Router
from jarvis.tools import AppIndex
from jarvis.tools.apps import OpenAppTool
from jarvis.tools.base import Tool
from jarvis.tools.close import CloseAppTool
from jarvis.tools.lock import LockTool
from jarvis.tools.media import MediaTool
from jarvis.tools.power import PowerTool
from jarvis.tools.sites import OpenSiteTool
from jarvis.tools.system import SystemStatusTool
from jarvis.tools.volume import VolumeTool
from jarvis.windows.metrics import SystemStats


def no_op(*args: Any) -> None:
    return None


def unused_stats() -> SystemStats:
    raise AssertionError("routing must not run the tool")


def all_tools() -> list[Tool[Any]]:
    """The production tool list and order (see jarvis.tools.build_tools), with fake backends."""
    return [
        SystemStatusTool(unused_stats),
        MediaTool(no_op),
        VolumeTool(FakeVolume(), 10),
        LockTool(no_op),
        PowerTool(no_op),
        CloseAppTool(80, list_windows=list, close=no_op),
        OpenSiteTool({"youtube": "https://www.youtube.com", "github": "https://github.com"}, no_op),
        OpenAppTool(AppIndex(80, 1800, loader=list), {}, start=no_op, open_url=no_op),
    ]


ROUTER = Router(all_tools())


@pytest.mark.parametrize(
    ("spoken", "tool", "args"),
    [
        # Portuguese
        ("Jarvis, abre o Spotify.", "open_app", {"name": "spotify"}),
        ("Abre o aplicativo do WhatsApp.", "open_app", {"name": "whatsapp"}),
        ("Inicia o Visual Studio Code.", "open_app", {"name": "visual studio code"}),
        ("Abre o YouTube.", "open_site", {"site": "youtube"}),
        ("Entra no GitHub.", "open_site", {"site": "github"}),
        ("Abre o site do G1 ponto com ponto br.", "open_site", {"site": "g1 ponto com ponto br"}),
        ("Acessa youtube.com", "open_site", {"site": "youtube.com"}),
        ("Como está o PC?", "system_status", {}),
        ("Faz um diagnóstico.", "system_status", {}),
        ("Pausa a música.", "media", {"action": "play_pause"}),
        ("Toca a música.", "media", {"action": "play_pause"}),
        ("Próxima música.", "media", {"action": "next"}),
        ("Pula essa faixa.", "media", {"action": "next"}),
        ("Música anterior.", "media", {"action": "previous"}),
        ("Volta a música.", "media", {"action": "previous"}),
        ("Volume em 30%.", "volume", {"action": "set", "level": 30}),
        ("Coloca o volume em trinta.", "volume", {"action": "set", "level": 30}),
        ("Aumenta o volume.", "volume", {"action": "up", "step": None}),
        ("Aumenta o volume em 20.", "volume", {"action": "up", "step": 20}),
        ("Abaixa o som.", "volume", {"action": "down"}),
        ("Diminui o volume para 10.", "volume", {"action": "set", "level": 10}),
        ("Silencia o som.", "volume", {"action": "mute"}),
        ("Tira do mudo.", "volume", {"action": "unmute"}),
        ("Qual é o volume?", "volume", {"action": "get"}),
        ("Bloqueia o computador.", "lock_pc", {}),
        ("Trava a tela.", "lock_pc", {}),
        ("Desliga o computador.", "power", {"action": "shutdown"}),
        ("Reinicia o PC.", "power", {"action": "restart"}),
        ("Fecha o Spotify.", "close_app", {"name": "spotify"}),
        ("Fecha o programa do Discord.", "close_app", {"name": "discord"}),
        # English
        ("Open Spotify.", "open_app", {"name": "spotify"}),
        ("Launch Visual Studio Code.", "open_app", {"name": "visual studio code"}),
        ("Open YouTube.", "open_site", {"site": "youtube"}),
        ("Go to github dot com.", "open_site", {"site": "github dot com"}),
        ("How's the computer doing?", "system_status", {}),
        ("System status.", "system_status", {}),
        ("Pause the music.", "media", {"action": "play_pause"}),
        ("Resume.", "media", {"action": "play_pause"}),
        ("Next song.", "media", {"action": "next"}),
        ("Skip.", "media", {"action": "next"}),
        ("Previous track.", "media", {"action": "previous"}),
        ("Set the volume to 40 percent.", "volume", {"action": "set", "level": 40}),
        ("Volume up.", "volume", {"action": "up"}),
        ("Turn the volume up by fifteen.", "volume", {"action": "up", "step": 15}),
        ("Turn it down.", "volume", {"action": "down"}),
        ("Louder.", "volume", {"action": "up"}),
        ("Mute.", "volume", {"action": "mute"}),
        ("Unmute the sound.", "volume", {"action": "unmute"}),
        ("What's the volume?", "volume", {"action": "get"}),
        ("Lock the computer.", "lock_pc", {}),
        ("Shut down the computer.", "power", {"action": "shutdown"}),
        ("Restart my PC.", "power", {"action": "restart"}),
        ("Close Spotify.", "close_app", {"name": "spotify"}),
        ("Quit Discord.", "close_app", {"name": "discord"}),
    ],
)
def test_phrase_routes_to_tool(spoken: str, tool: str, args: dict[str, object]) -> None:
    route = ROUTER.route(spoken)

    assert route is not None, spoken
    assert route.tool.name == tool
    assert route.params.model_dump().items() >= args.items()


@pytest.mark.parametrize(
    "spoken",
    [
        "Qual a previsão do tempo para amanhã?",  # weather: LLM and tools of Phase 3
        "What's the weather like?",
        "Fecha o computador.",  # not a program, and not a power phrasing
        "Abre o.",  # no app name
        "Toca Despacito.",  # playing a specific song is not supported
        "Volume alto.",  # not a number
        "Me conta uma piada.",
    ],
)
def test_phrase_matches_no_rule(spoken: str) -> None:
    assert ROUTER.route(spoken) is None
