"""The SQLite database (ADR-029): one connection, owned by one worker thread.

A sqlite3 connection belongs to the thread that created it, so every query runs on a
single-thread executor; coroutines await the result. The schema version lives in SQLite's
own ``user_version`` and migrations are applied in order on start-up.
"""

import asyncio
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MIGRATIONS = [
    # 1: reminders, API usage and small key/value settings
    """
    CREATE TABLE reminders (
        id         INTEGER PRIMARY KEY,
        text       TEXT    NOT NULL,
        due_at     TEXT    NOT NULL,  -- ISO 8601, UTC
        language   TEXT    NOT NULL,
        created_at TEXT    NOT NULL,
        status     TEXT    NOT NULL DEFAULT 'pending'  -- pending | done | cancelled
    );
    CREATE INDEX reminders_due ON reminders (status, due_at);
    CREATE TABLE llm_usage (
        id                 INTEGER PRIMARY KEY,
        at                 TEXT    NOT NULL,
        model              TEXT    NOT NULL,
        input_tokens       INTEGER NOT NULL,
        output_tokens      INTEGER NOT NULL,
        cache_write_tokens INTEGER NOT NULL,
        cache_read_tokens  INTEGER NOT NULL,
        cost_usd           REAL    NOT NULL
    );
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._executor = ThreadPoolExecutor(1, "jarvis-db")
        self._connection: sqlite3.Connection | None = None

    async def open(self) -> None:
        """Create the file if needed and apply pending migrations."""
        await self.run(lambda _: None)

    async def run[T](self, action: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``action`` with the connection, on the database thread, in a transaction."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._call, action)

    def close(self) -> None:
        self._executor.submit(self._close).result()
        self._executor.shutdown()

    def _call[T](self, action: Callable[[sqlite3.Connection], T]) -> T:
        connection = self._connect()
        with connection:  # commits on success, rolls back on error
            return action(connection)

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
            connection.row_factory = sqlite3.Row
            _migrate(connection)
            self._connection = connection
        return self._connection

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        connection.executescript(script)
        connection.execute(f"PRAGMA user_version = {number}")
    connection.commit()
