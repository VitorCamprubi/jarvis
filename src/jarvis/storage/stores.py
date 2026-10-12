"""Repositories over the database: reminders, API usage and settings (ADR-029)."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from jarvis.i18n import Language
from jarvis.storage.db import Database

ReminderStatus = Literal["pending", "done", "cancelled"]


def _to_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _from_text(text: str) -> datetime:
    return datetime.fromisoformat(text)


@dataclass(frozen=True)
class Reminder:
    id: int
    text: str
    due_at: datetime  # timezone-aware
    language: Language
    created_at: datetime


def _reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        text=row["text"],
        due_at=_from_text(row["due_at"]),
        language=Language(row["language"]),
        created_at=_from_text(row["created_at"]),
    )


class ReminderStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, text: str, due_at: datetime, language: Language, now: datetime) -> Reminder:
        def insert(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                "INSERT INTO reminders (text, due_at, language, created_at) VALUES (?, ?, ?, ?)",
                (text, _to_text(due_at), language.value, _to_text(now)),
            )
            return int(cursor.lastrowid or 0)

        reminder_id = await self._db.run(insert)
        return Reminder(reminder_id, text, due_at, language, now)

    async def pending(self) -> list[Reminder]:
        """Pending reminders, soonest first."""
        rows = await self._db.run(
            lambda connection: connection.execute(
                "SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_at"
            ).fetchall()
        )
        return [_reminder(row) for row in rows]

    async def set_status(self, reminder_id: int, status: ReminderStatus) -> bool:
        def update(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "UPDATE reminders SET status = ? WHERE id = ? AND status = 'pending'",
                (status, reminder_id),
            )
            return cursor.rowcount > 0

        return await self._db.run(update)


class UsageStore:
    """Tokens and estimated cost of every LLM request (ADR-010)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        at: datetime,
        model: str,
        tokens: tuple[int, int, int, int],  # input, output, cache write, cache read
        cost_usd: float,
    ) -> None:
        await self._db.run(
            lambda connection: connection.execute(
                "INSERT INTO llm_usage (at, model, input_tokens, output_tokens, "
                "cache_write_tokens, cache_read_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_to_text(at), model, *tokens, cost_usd),
            )
        )

    async def total_cost(self) -> float:
        total = await self._db.run(
            lambda connection: connection.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage"
            ).fetchone()[0]
        )
        return float(total)


class SettingsStore:
    """Small values that must survive a restart, such as the language lock."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> str | None:
        row = await self._db.run(
            lambda connection: connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        )
        return None if row is None else str(row["value"])

    async def set(self, key: str, value: str) -> None:
        await self._db.run(
            lambda connection: connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        )

    async def delete(self, key: str) -> None:
        await self._db.run(
            lambda connection: connection.execute("DELETE FROM settings WHERE key = ?", (key,))
        )
