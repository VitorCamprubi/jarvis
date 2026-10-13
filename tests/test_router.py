"""Phrase tables: what each spoken command routes to, in both languages.

The router is built exactly like in production (build_tools and the shipped defaults), with
backends that never touch the system: routing must not run any tool.
"""

import tomllib
from typing import Any

import pytest

from jarvis import paths
from jarvis.config import AppConfig
from jarvis.core.language import LanguagePolicy
from jarvis.i18n import Language
from jarvis.router import Router
from jarvis.storage import Database, ReminderStore
from jarvis.tools import (
    AppIndex,
    FileIndex,
    NewsService,
    ResultList,
    Services,
    WeatherClient,
    build_tools,
)
from jarvis.tools.base import Tool
from jarvis.tools.reminders import ReminderService


def all_tools() -> list[Tool[Any]]:
    with (paths.CONFIG_DIR / "default.toml").open("rb") as file:
        config = AppConfig.model_validate(tomllib.load(file))
    services = Services(
        app_index=AppIndex(85, 1800, loader=list),
        file_index=FileIndex([], [], 600),
        results=ResultList(),
        weather=WeatherClient(),
        reminders=ReminderService(ReminderStore(Database(":memory:"))),
        news=NewsService(config.news),
        language=LanguagePolicy(),
        reply_language=lambda: Language.PT,
    )
    return build_tools(config, services)


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
        ("Fala em inglês.", "set_language", {"language": "en"}),
        ("Responda em português.", "set_language", {"language": "pt"}),
        ("Volta pro automático.", "set_language", {"language": "auto"}),
        ("Idioma automático.", "set_language", {"language": "auto"}),
        ("Me lembra em 20 minutos de tirar a pizza.", "create_reminder", {}),
        ("Cria um lembrete pra reunião às 16h.", "create_reminder", {}),
        ("Quais são os meus lembretes?", "list_reminders", {}),
        ("Cancela o lembrete da reunião.", "cancel_reminder", {"query": "reuniao"}),
        ("Como está o tempo?", "weather", {"when": "now", "city": None}),
        ("Como vai estar o tempo amanhã?", "weather", {"when": "tomorrow"}),
        (
            "Qual a previsão do tempo para amanhã em São Paulo?",
            "weather",
            {"when": "tomorrow", "city": "sao paulo"},
        ),
        ("Vai chover hoje?", "weather", {"when": "today"}),
        ("Procura o arquivo currículo.", "search_files", {"query": "curriculo"}),
        ("Onde está o relatório mensal?", "search_files", {"query": "relatorio mensal"}),
        ("Abre o segundo.", "open_search_result", {"position": 2}),
        ("Abre o primeiro arquivo.", "open_search_result", {"position": 1}),
        ("Quais são as notícias de hoje?", "news", {"topic": None}),
        ("Me dá as principais notícias.", "news", {"topic": None}),
        ("Notícias sobre inteligência artificial.", "news", {"topic": "inteligencia artificial"}),
        ("O que há de novo sobre a Apple?", "news", {"topic": "apple"}),
        ("Jarvis, bom dia!", "morning_briefing", {}),
        ("Bom dia, Jarvis.", "morning_briefing", {}),
        ("Me dá o resumo do dia.", "morning_briefing", {}),
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
        ("Speak English.", "set_language", {"language": "en"}),
        ("Talk to me in Portuguese.", "set_language", {"language": "pt"}),
        ("Automatic language.", "set_language", {"language": "auto"}),
        ("Remind me to call John at 6 pm.", "create_reminder", {}),
        ("What are my reminders?", "list_reminders", {}),
        ("Cancel the reminder about John.", "cancel_reminder", {"query": "john"}),
        ("What's the weather like tomorrow?", "weather", {"when": "tomorrow"}),
        ("Will it rain tomorrow in London?", "weather", {"when": "tomorrow", "city": "london"}),
        ("Find the file report.", "search_files", {"query": "report"}),
        ("Open the second one.", "open_search_result", {"position": 2}),
        ("What's the news today?", "news", {"topic": None}),
        ("Give me the latest tech news.", "news", {"topic": None}),
        ("Any news about Nvidia?", "news", {"topic": "nvidia"}),
        ("What's new in AI?", "news", {"topic": "ai"}),
        ("Good morning, Jarvis.", "morning_briefing", {}),
        ("Morning briefing.", "morning_briefing", {}),
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
        "E amanhã?",  # a follow-up: the LLM answers it with the conversation memory
        "Quem descobriu o Brasil?",  # general knowledge: the LLM
        "Fecha o computador.",  # not a program, and not a power phrasing
        "Abre o.",  # no app name
        "Toca Despacito.",  # playing a specific song is not supported
        "Volume alto.",  # not a number
        "Me conta uma piada.",
        # web search: the LLM searches (ADR-034), never the file search
        "Pesquisa quem ganhou o jogo do Palmeiras.",
        "Procura na internet o preço do dólar.",
        "Busca no Google a previsão do Corinthians.",
        "Search the web for the latest Python release.",
        "Find the opening hours of the Louvre online.",
        "Bom dia, tudo bem com você?",
    ],
)
def test_phrase_matches_no_rule(spoken: str) -> None:
    assert ROUTER.route(spoken) is None
