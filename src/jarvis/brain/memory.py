"""Short-term conversation memory (ADR-028): recent exchanges, text only, in memory.

Text only keeps the history append-only for the LLM (no old reasoning is ever resent) and
leaves nothing personal on disk. After some minutes of silence the slate is wiped clean.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.brain.provider import AssistantMessage, Message, UserMessage


@dataclass(frozen=True)
class Exchange:
    said: str  # what the user said
    replied: str  # what JARVIS answered


class ConversationMemory:
    def __init__(
        self,
        max_exchanges: int,
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._exchanges: deque[Exchange] = deque(maxlen=max_exchanges)
        self._ttl_s = ttl_s
        self._clock = clock
        self._last_at = float("-inf")

    def add(self, said: str, replied: str) -> None:
        self._forget_if_stale()
        if self._exchanges.maxlen:
            self._exchanges.append(Exchange(said, replied))
        self._last_at = self._clock()

    def messages(self) -> list[Message]:
        """The remembered exchanges as alternating user and assistant messages."""
        self._forget_if_stale()
        messages: list[Message] = []
        for exchange in self._exchanges:
            messages += [UserMessage(exchange.said), AssistantMessage(exchange.replied)]
        return messages

    def clear(self) -> None:
        self._exchanges.clear()

    def _forget_if_stale(self) -> None:
        if self._clock() - self._last_at > self._ttl_s:
            self._exchanges.clear()
