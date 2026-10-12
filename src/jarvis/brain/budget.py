"""Local spending guard (ADR-010): prices every response, warns, then stops the LLM.

The Anthropic Console limit is the hard stop; this guard keeps JARVIS from hitting it in
the middle of a sentence and makes the spending visible.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from jarvis.brain.provider import TokenUsage
from jarvis.config import BudgetConfig
from jarvis.storage import UsageStore

log = logging.getLogger(__name__)
MILLION = 1_000_000


class BudgetState(StrEnum):
    OK = "ok"
    WARNING = "warning"  # past the warning threshold, still answering
    EXHAUSTED = "exhausted"  # past the stop threshold: rules only


@dataclass(frozen=True)
class BudgetStatus:
    spent_usd: float
    state: BudgetState


class BudgetGuard:
    def __init__(
        self,
        store: UsageStore,
        config: BudgetConfig,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._store = store
        self._config = config
        self._clock = clock
        self._spent: float | None = None  # loaded from the database on first use

    def cost(self, usage: TokenUsage) -> float:
        config = self._config
        return (
            usage.input_tokens * config.input_per_mtok
            + usage.output_tokens * config.output_per_mtok
            + usage.cache_write_tokens * config.cache_write_per_mtok
            + usage.cache_read_tokens * config.cache_read_per_mtok
        ) / MILLION

    async def status(self) -> BudgetStatus:
        if self._spent is None:
            self._spent = await self._store.total_cost()
        return BudgetStatus(self._spent, self._state(self._spent))

    async def record(self, model: str, usage: TokenUsage) -> BudgetStatus:
        before = await self.status()
        cost = self.cost(usage)
        tokens = (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_write_tokens,
            usage.cache_read_tokens,
        )
        await self._store.add(self._clock(), model, tokens, cost)
        self._spent = before.spent_usd + cost
        log.info(
            "LLM usage: %d in, %d out, %d cache write, %d cache read = US$ %.5f (total US$ %.4f)",
            *tokens,
            cost,
            self._spent,
        )
        return BudgetStatus(self._spent, self._state(self._spent))

    def _state(self, spent: float) -> BudgetState:
        if spent >= self._config.stop_usd:
            return BudgetState.EXHAUSTED
        if spent >= self._config.warn_usd:
            return BudgetState.WARNING
        return BudgetState.OK
