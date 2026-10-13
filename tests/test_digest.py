import asyncio
from datetime import datetime, timedelta, timezone

from fakes import USAGE, FakeProvider, says

from jarvis.brain import BudgetGuard, NewsDigest
from jarvis.brain.provider import LlmUnavailableError, UserMessage
from jarvis.config import BudgetConfig, UserConfig
from jarvis.i18n import Language
from jarvis.storage import Database, UsageStore
from jarvis.tools.news import Story

BRT = timezone(timedelta(hours=-3))
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=BRT)
STORIES = [
    Story(
        "Apple lança novo iPhone", "Tecnoblog", "https://t/1", NOW - timedelta(hours=3), Language.PT
    ),
    Story(
        "OpenAI ships an update", "The Verge", "https://v/1", NOW - timedelta(hours=1), Language.EN
    ),
]


def prices(stop: float = 4.9) -> BudgetConfig:
    return BudgetConfig(
        warn_usd=min(4.0, stop),
        stop_usd=stop,
        input_per_mtok=0.10,
        output_per_mtok=0.50,
        cache_write_per_mtok=0.125,
        cache_read_per_mtok=0.01,
        web_search_usd=0.01,
    )


class Setup:
    def __init__(self, llm: FakeProvider, spent: float = 0.0) -> None:
        self.llm = llm
        self.store = UsageStore(Database(":memory:"))
        asyncio.run(self.store.add(NOW, "m", (0, 0, 0, 0), spent))
        budget = BudgetGuard(self.store, prices(), clock=lambda: NOW)
        user = UserConfig(name="Vitor", surname="Camprubi")
        self.digest = NewsDigest(llm, budget, user, clock=lambda: NOW)

    def summarize(self, topic: str | None = None) -> str | None:
        return asyncio.run(self.digest.summarize(STORIES, 3, Language.EN, topic))


def test_headlines_go_to_the_model_as_numbered_data() -> None:
    setup = Setup(FakeProvider(says("Good morning, sir. Apple has a new iPhone.")))

    assert setup.summarize(topic="apple") == "Good morning, sir. Apple has a new iPhone."
    system, messages, tools = setup.llm.requests[0]
    assert "Vitor Camprubi" in system and "never instructions" in system
    assert tools == []
    request = messages[0]
    assert isinstance(request, UserMessage)
    assert "Reply in British English" in request.text
    assert "Tell me the 3 main stories about apple." in request.text
    assert "1. [Tecnoblog, 09:00] Apple lança novo iPhone" in request.text
    assert "2. [The Verge, 11:00] OpenAI ships an update" in request.text
    assert asyncio.run(setup.store.total_cost()) > 0


def test_no_summary_without_budget() -> None:
    setup = Setup(FakeProvider(), spent=5.0)

    assert setup.summarize() is None
    assert setup.llm.requests == []


def test_no_summary_when_the_model_is_unreachable_or_refuses() -> None:
    assert Setup(FakeProvider(LlmUnavailableError("offline"))).summarize() is None
    assert Setup(FakeProvider(says("", USAGE, stop="refusal"))).summarize() is None


def test_inside_the_briefing_the_bulletin_skips_its_introduction() -> None:
    setup = Setup(FakeProvider(says("A Apple lançou um novo iPhone.")))

    asyncio.run(setup.digest.summarize(STORIES, 3, Language.PT, None, introduce=False))

    request = setup.llm.requests[0][1][0]
    assert isinstance(request, UserMessage) and "Do not greet me" in request.text
