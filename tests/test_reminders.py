import asyncio
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.i18n import Language, Translator
from jarvis.storage import Database, Reminder, ReminderStore
from jarvis.tools.base import ToolResult, render
from jarvis.tools.reminders import (
    CancelReminderParams,
    CancelReminderTool,
    CreateReminderParams,
    CreateReminderTool,
    ListRemindersParams,
    ListRemindersTool,
    ReminderService,
    split_reminder,
    when_reply,
)

BRT = timezone(timedelta(hours=-3))
NOW = datetime(2026, 10, 12, 14, 0, tzinfo=BRT)
TRANSLATOR = Translator.load()


@pytest.mark.parametrize(
    ("spoken", "text", "due"),
    [
        (
            "Me lembra de ligar pra mãe amanhã às 9.",
            "ligar pra mãe",
            datetime(2026, 10, 13, 9, 0, tzinfo=BRT),
        ),
        (
            "Jarvis, me lembra em 20 minutos de tirar a pizza do forno.",
            "tirar a pizza do forno",
            NOW + timedelta(minutes=20),
        ),
        ("Remind me to call John at 6 pm.", "call John", datetime(2026, 10, 12, 18, 0, tzinfo=BRT)),
        (
            "Me lembra, por favor, de ligar pro dentista às 16h.",
            "ligar pro dentista",
            datetime(2026, 10, 12, 16, 0, tzinfo=BRT),
        ),
        (
            "Cria um lembrete pra reunião às 16h30",
            "reunião",
            datetime(2026, 10, 12, 16, 30, tzinfo=BRT),
        ),
    ],
)
def test_split_keeps_the_original_words(spoken: str, text: str, due: datetime) -> None:
    assert split_reminder(spoken, NOW, default_hour=9) == (text, due)


def test_split_without_a_time() -> None:
    assert split_reminder("Me lembra de comprar pão.", NOW, default_hour=9) is None


@pytest.mark.parametrize(
    ("due", "language", "spoken"),
    [
        (NOW + timedelta(minutes=20), Language.PT, "em 20 minutos"),
        (NOW.replace(hour=18, minute=30), Language.PT, "hoje às 18h30"),
        (NOW.replace(hour=18), Language.EN, "today at 6 PM"),
        (NOW + timedelta(days=1, hours=-5), Language.EN, "tomorrow at 9 AM"),
        (NOW + timedelta(days=3), Language.PT, "no dia 15/10 às 14h"),
    ],
)
def test_when_is_said_naturally(due: datetime, language: Language, spoken: str) -> None:
    assert render(when_reply(due, NOW), TRANSLATOR, language) == spoken


class Announcements:
    def __init__(self) -> None:
        self.heard: list[tuple[str, bool]] = []
        self.event = asyncio.Event()

    def __call__(self, reminder: Reminder, overdue: bool) -> None:
        self.heard.append((reminder.text, overdue))
        self.event.set()


def real_now() -> datetime:
    return datetime.now(BRT)


def test_service_announces_when_due_and_overdue_ones_at_start() -> None:
    async def scenario() -> list[tuple[str, bool]]:
        store = ReminderStore(Database(":memory:"))
        await store.add(
            "missed while closed", real_now() - timedelta(hours=1), Language.PT, real_now()
        )
        service = ReminderService(store, clock=real_now)
        announcements = Announcements()
        await service.start(announcements)
        announcements.event.clear()
        await service.add("soon", real_now() + timedelta(milliseconds=50), Language.EN)
        await asyncio.wait_for(announcements.event.wait(), 2)
        service.stop()
        return announcements.heard

    assert asyncio.run(scenario()) == [("missed while closed", True), ("soon", False)]


def run(awaitable: Awaitable[ToolResult]) -> ToolResult:
    async def wait() -> ToolResult:
        return await awaitable

    return asyncio.run(wait())


class Tools:
    def __init__(self) -> None:
        self.service = ReminderService(ReminderStore(Database(":memory:")), clock=lambda: NOW)
        self.create = CreateReminderTool(self.service, lambda: Language.PT, 9, clock=lambda: NOW)
        self.list = ListRemindersTool(self.service, clock=lambda: NOW)
        self.cancel = CancelReminderTool(self.service)

    def texts(self) -> list[str]:
        async def pending() -> list[str]:
            return [r.text for r in await self.service.pending()]

        return asyncio.run(pending())


def test_create_from_a_spoken_sentence() -> None:
    tools = Tools()

    result = run(
        tools.create.run(CreateReminderParams(utterance="Me lembra em 20 minutos de tirar a pizza"))
    )

    assert result.reply.key == "reminders.created"
    assert render(result.reply, TRANSLATOR, Language.PT).endswith("tirar a pizza.")
    assert tools.texts() == ["tirar a pizza"]


def test_create_from_the_llm_with_local_time() -> None:
    tools = Tools()

    run(
        tools.create.run(
            CreateReminderParams(text="ligar pro João", due_at=datetime(2026, 10, 12, 18, 0))
        )
    )

    assert tools.texts() == ["ligar pro João"]


@pytest.mark.parametrize(
    ("params", "key"),
    [
        (CreateReminderParams(utterance="Me lembra de comprar pão"), "reminders.need_time"),
        (CreateReminderParams(utterance="Me lembra em 10 minutos"), "reminders.need_text"),
        (
            CreateReminderParams(text="ontem", due_at=datetime(2026, 10, 11, 9, 0, tzinfo=BRT)),
            "reminders.in_the_past",
        ),
    ],
)
def test_create_explains_what_is_missing(params: CreateReminderParams, key: str) -> None:
    assert run(Tools().create.run(params)).reply.key == key


def test_list_and_cancel() -> None:
    tools = Tools()
    run(tools.create.run(CreateReminderParams(utterance="Me lembra de regar as plantas às 18h")))
    run(tools.create.run(CreateReminderParams(utterance="Me lembra de ligar pro dentista às 16h")))

    listing = run(tools.list.run(ListRemindersParams()))
    assert listing.reply.key == "reminders.list"
    assert listing.reply.params["text"] == "ligar pro dentista"  # soonest first

    cancelled = run(tools.cancel.run(CancelReminderParams(query="plantas")))
    assert cancelled.reply.params == {"text": "regar as plantas"}
    assert tools.texts() == ["ligar pro dentista"]

    run(tools.cancel.run(CancelReminderParams()))  # the latest one
    assert run(tools.list.run(ListRemindersParams())).reply.key == "reminders.none"


def test_cancel_reports_an_unknown_reminder() -> None:
    tools = Tools()
    run(tools.create.run(CreateReminderParams(utterance="Me lembra de regar as plantas às 18h")))

    result = run(tools.cancel.run(CancelReminderParams(query="aniversário")))

    assert result.reply.key == "reminders.not_found"
    assert tools.texts() == ["regar as plantas"]
