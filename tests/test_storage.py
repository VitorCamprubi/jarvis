import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.core.language import LanguagePolicy
from jarvis.i18n import Language
from jarvis.storage import Database, ReminderStore, SettingsStore, UsageStore

NOW = datetime(2026, 10, 12, 17, 0, tzinfo=UTC)


def test_reminders_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"

    async def first_run() -> None:
        db = Database(path)
        await db.open()
        store = ReminderStore(db)
        await store.add("tirar a pizza", NOW + timedelta(minutes=20), Language.PT, NOW)
        await store.add("call mum", NOW + timedelta(minutes=5), Language.EN, NOW)
        db.close()

    async def second_run() -> list[str]:
        db = Database(path)
        await db.open()
        pending = await ReminderStore(db).pending()
        db.close()
        return [reminder.text for reminder in pending]

    asyncio.run(first_run())
    assert asyncio.run(second_run()) == ["call mum", "tirar a pizza"]  # soonest first


def test_finished_reminders_leave_the_pending_list() -> None:
    async def scenario() -> tuple[bool, bool, int]:
        store = ReminderStore(Database(":memory:"))
        reminder = await store.add("chá", NOW, Language.PT, NOW)
        first = await store.set_status(reminder.id, "done")
        again = await store.set_status(reminder.id, "cancelled")  # already finished
        return first, again, len(await store.pending())

    assert asyncio.run(scenario()) == (True, False, 0)


def test_usage_costs_add_up() -> None:
    async def scenario() -> float:
        store = UsageStore(Database(":memory:"))
        await store.add(NOW, "claude-haiku-5-5", (1000, 100, 0, 0), 0.00015)
        await store.add(NOW, "claude-haiku-5-5", (2000, 200, 0, 0), 0.0003)
        return await store.total_cost()

    assert abs(asyncio.run(scenario()) - 0.00045) < 1e-12


def test_language_lock_is_stored() -> None:
    async def scenario() -> tuple[Language | None, Language | None]:
        db = Database(":memory:")
        await LanguagePolicy(SettingsStore(db)).lock(Language.EN)
        restored = LanguagePolicy(SettingsStore(db))
        await restored.load()
        locked = restored.locked
        await restored.lock(None)
        unlocked = LanguagePolicy(SettingsStore(db))
        await unlocked.load()
        return locked, unlocked.locked

    assert asyncio.run(scenario()) == (Language.EN, None)


def test_reply_language_follows_the_lock() -> None:
    policy = LanguagePolicy()

    assert policy.reply_language(Language.PT) is Language.PT
    asyncio.run(policy.lock(Language.EN))
    assert policy.reply_language(Language.PT) is Language.EN
