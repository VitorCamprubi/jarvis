import asyncio

import pytest

from jarvis.brain import BudgetGuard, BudgetState, ConversationMemory
from jarvis.brain.provider import AssistantMessage, TokenUsage, UserMessage
from jarvis.config import BudgetConfig
from jarvis.storage import Database, UsageStore

PRICES = BudgetConfig(
    warn_usd=4.0,
    stop_usd=4.9,
    input_per_mtok=0.10,
    output_per_mtok=0.50,
    cache_write_per_mtok=0.125,
    cache_read_per_mtok=0.01,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_memory_keeps_the_latest_exchanges_in_order() -> None:
    memory = ConversationMemory(max_exchanges=2, ttl_s=600)
    for number in range(3):
        memory.add(f"said {number}", f"replied {number}")

    assert memory.messages() == [
        UserMessage("said 1"),
        AssistantMessage("replied 1"),
        UserMessage("said 2"),
        AssistantMessage("replied 2"),
    ]


def test_memory_forgets_after_a_silence() -> None:
    clock = Clock()
    memory = ConversationMemory(max_exchanges=6, ttl_s=600, clock=clock)
    memory.add("Vai chover hoje?", "Não, senhor.")

    clock.now = 599
    assert len(memory.messages()) == 2
    clock.now = 1200
    assert memory.messages() == []


def test_memory_can_be_disabled() -> None:
    memory = ConversationMemory(max_exchanges=0, ttl_s=600)
    memory.add("Oi", "Olá")

    assert memory.messages() == []


def test_cost_uses_every_token_price() -> None:
    guard = BudgetGuard(UsageStore(Database(":memory:")), PRICES)
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )

    assert guard.cost(usage) == pytest.approx(0.10 + 0.50 + 0.125 + 0.01)


@pytest.mark.parametrize(
    ("spent_tokens", "state"),
    [(0, BudgetState.OK), (40_000_000, BudgetState.WARNING), (49_000_000, BudgetState.EXHAUSTED)],
)
def test_budget_states(spent_tokens: int, state: BudgetState) -> None:
    async def scenario() -> BudgetState:
        guard = BudgetGuard(UsageStore(Database(":memory:")), PRICES)
        status = await guard.record("m", TokenUsage(input_tokens=spent_tokens))
        return status.state

    assert asyncio.run(scenario()) is state


def test_spending_is_remembered_across_restarts() -> None:
    async def scenario() -> float:
        db = Database(":memory:")
        await BudgetGuard(UsageStore(db), PRICES).record("m", TokenUsage(input_tokens=10_000))
        restarted = BudgetGuard(UsageStore(db), PRICES)
        return (await restarted.status()).spent_usd

    assert asyncio.run(scenario()) == pytest.approx(0.001)
