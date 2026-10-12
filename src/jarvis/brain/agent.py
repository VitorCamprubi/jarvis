"""The brain: answers what the rules cannot, with the LLM and the registered tools (ADR-026).

Each request runs a small tool-use loop. Before every LLM call the budget is checked
(ADR-010); only tools from the registry exist (ADR-020); a tool that needs confirmation ends
the loop and goes back to the pipeline, which asks out loud (ADR-025). Action tools speak
their own reply directly, which saves a second LLM call; tools that return facts
(``model_data``) let the LLM word the answer.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from jarvis.brain.budget import BudgetGuard, BudgetState
from jarvis.brain.memory import ConversationMemory
from jarvis.brain.persona import context_note
from jarvis.brain.provider import (
    LlmAuthError,
    LlmError,
    LLMProvider,
    LlmUnavailableError,
    Message,
    ToolCall,
    ToolOutcome,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from jarvis.i18n import Language, Translator
from jarvis.tools.base import Reply, Tool, ToolResult, render

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainAnswer:
    results: tuple[ToolResult, ...]  # spoken in order
    budget_warning: bool = False  # this request crossed the warning threshold


@dataclass(frozen=True)
class _Execution:
    outcome: ToolOutcome  # what the LLM is told
    result: ToolResult | None = None  # what the tool returned, if it ran

    @property
    def needs_model(self) -> bool:
        return self.result is not None and self.result.model_data is not None


def tool_spec(tool: Tool[Any]) -> ToolSpec:
    return ToolSpec(tool.name, tool.description, tool.params_model.model_json_schema())


def _say(key: str, warning: bool = False) -> BrainAnswer:
    return BrainAnswer((ToolResult(Reply(key)),), warning)


class Brain:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: Sequence[Tool[Any]],
        budget: BudgetGuard,
        memory: ConversationMemory,
        translator: Translator,
        system: str,
        max_tool_rounds: int,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._provider = provider
        self._tools = {tool.name: tool for tool in tools}
        self._specs = [tool_spec(tool) for tool in tools]
        self._budget = budget
        self._memory = memory
        self._translator = translator
        self._system = system
        self._max_rounds = max_tool_rounds
        self._clock = clock

    async def answer(self, text: str, language: Language) -> BrainAnswer:
        status = await self._budget.status()
        if status.state is BudgetState.EXHAUSTED:
            return _say("brain.budget_exhausted")
        note = context_note(self._clock(), language)
        messages: list[Message] = [*self._memory.messages(), UserMessage(f"{note}\n{text}")]
        warned = False
        try:
            for _ in range(self._max_rounds):
                completion = await self._provider.complete(self._system, messages, self._specs)
                after = await self._budget.record(self._provider.model, completion.usage)
                warned = warned or (
                    status.state is BudgetState.OK and after.state is not BudgetState.OK
                )
                status = after
                if completion.stop_reason == "refusal":
                    return _say("brain.refused", warned)
                calls = completion.message.tool_calls
                if not calls:
                    return self._final(completion.message.text, warned)

                executions = [await self._execute(call, language) for call in calls]
                for execution in executions:
                    if execution.result is not None and execution.result.on_confirm is not None:
                        return BrainAnswer((execution.result,), warned)  # confirmed by voice
                if all(e.result is not None and not e.needs_model for e in executions):
                    return BrainAnswer(tuple(e.result for e in executions if e.result), warned)
                if status.state is BudgetState.EXHAUSTED:
                    return _say("brain.budget_exhausted", warned)
                outcomes = tuple(execution.outcome for execution in executions)
                messages += [completion.message, ToolResultsMessage(outcomes)]
        except LlmAuthError as exc:
            log.error("The LLM rejected the API key: %s", exc)
            return _say("brain.auth_failed", warned)
        except LlmUnavailableError as exc:
            log.warning("LLM unavailable: %s", exc)
            return _say("brain.unavailable", warned)
        except LlmError:
            log.exception("LLM request failed")
            return _say("errors.generic", warned)
        log.warning("Gave up after %d tool rounds", self._max_rounds)
        return _say("errors.generic", warned)

    def _final(self, text: str, warned: bool) -> BrainAnswer:
        if not text:
            return _say("errors.generic", warned)
        # Generated text is never cached on disk (it may contain anything the user said).
        return BrainAnswer(
            (ToolResult(Reply("brain.say", {"text": text}, cacheable=False)),), warned
        )

    async def _execute(self, call: ToolCall, language: Language) -> _Execution:
        tool = self._tools.get(call.name)
        if tool is None:  # only registered tools exist (ADR-020)
            log.warning("LLM asked for an unknown tool: %s", call.name)
            return _Execution(ToolOutcome(call.id, f"There is no tool named {call.name!r}.", True))
        try:
            params = tool.parse(call.arguments)
        except ValidationError as exc:
            problems = "; ".join(error["msg"] for error in exc.errors(include_url=False))
            return _Execution(ToolOutcome(call.id, f"Invalid arguments: {problems}", True))
        log.info("LLM tool: %s", call.name)
        log.debug("LLM tool arguments: %r", params)
        try:
            result = await tool.run(params)
        except Exception:
            log.exception("Tool %s failed", call.name)
            return _Execution(ToolOutcome(call.id, "The tool failed unexpectedly.", True))
        if result.details:
            log.info("%s details:\n%s", call.name, result.details)
        spoken = render(result.reply, self._translator, language)
        content = result.model_data if result.model_data is not None else f"Done. Said: {spoken}"
        return _Execution(ToolOutcome(call.id, content), result)
