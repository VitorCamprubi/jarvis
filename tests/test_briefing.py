import asyncio
from datetime import datetime, timedelta, timezone

import httpx2
import pytest
from test_news import CONFIG as NEWS_CONFIG
from test_news import NOW as NEWS_NOW
from test_news import FakeSummarizer, Network
from test_weather import DEFAULT, transport

from jarvis.i18n import Language, Translator
from jarvis.storage import Database, ReminderStore
from jarvis.text.when import part_of_day
from jarvis.tools.base import ToolResult, render
from jarvis.tools.briefing import BriefingParams, BriefingTool
from jarvis.tools.news import NewsService
from jarvis.tools.reminders import ReminderService
from jarvis.tools.weather import WeatherClient, WeatherTool

BRT = timezone(timedelta(hours=-3))
MORNING = datetime(2026, 10, 12, 8, 0, tzinfo=BRT)  # the canned forecast's "today"
TRANSLATOR = Translator.load()


def briefing(
    reminders: list[tuple[str, datetime]],
    weather_status: int = 200,
    news_down: bool = False,
) -> ToolResult:
    async def scenario() -> ToolResult:
        service = ReminderService(ReminderStore(Database(":memory:")), clock=lambda: MORNING)
        for text, due in reminders:
            await service.add(text, due, Language.PT)
        network = Network(down=["tecnoblog.net", "news.google.com"] if news_down else [])
        news = NewsService(
            NEWS_CONFIG,
            FakeSummarizer("A Apple lançou um novo iPhone, senhor."),
            transport=httpx2.MockTransport(network.handler),
            clock=lambda: NEWS_NOW,
        )
        weather = WeatherTool(WeatherClient(transport(weather_status)), DEFAULT)
        tool = BriefingTool(weather, service, news, lambda: Language.PT, 3, clock=lambda: MORNING)
        return await tool.run(BriefingParams())

    return asyncio.run(scenario())


def test_greeting_weather_reminders_and_news_in_order() -> None:
    result = briefing(
        [
            ("dentista", MORNING + timedelta(days=1)),
            ("reunião", MORNING.replace(hour=16)),
            ("academia", MORNING.replace(hour=18, minute=30)),
        ]
    )

    spoken = render(result.reply, TRANSLATOR, Language.PT)
    assert spoken.startswith("Bom dia")
    assert spoken.endswith(
        "Hoje em Sorocaba: parcialmente nublado, máxima de 28 e mínima de 16 graus, com 10 por "
        "cento de chance de chuva, senhor. Para hoje há 2 lembretes; o primeiro é reunião, às "
        "16h. A Apple lançou um novo iPhone, senhor."
    )
    assert result.details is not None and "https://tecnoblog.net/1" in result.details


def test_each_part_fails_on_its_own() -> None:
    result = briefing([("reunião", MORNING.replace(hour=16))], weather_status=503, news_down=True)

    spoken = render(result.reply, TRANSLATOR, Language.PT)
    assert "Receio que o serviço de clima não esteja respondendo, senhor." in spoken
    assert "Para hoje há um lembrete: reunião, às 16h." in spoken
    assert "fontes" in spoken or "redação" in spoken  # news.unavailable


def test_a_day_without_reminders() -> None:
    spoken = render(briefing([]).reply, TRANSLATOR, Language.EN)

    assert "You have no reminders today." in spoken


@pytest.mark.parametrize(
    ("hour", "part"),
    [(5, "morning"), (11, "morning"), (12, "afternoon"), (18, "evening"), (2, "night")],
)
def test_parts_of_the_day(hour: int, part: str) -> None:
    assert part_of_day(hour) == part
