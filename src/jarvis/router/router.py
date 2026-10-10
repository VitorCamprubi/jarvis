"""Bilingual rule router (ADR-019): maps an utterance to a tool and its validated parameters.

Every pattern of every tool is tried in order, in both languages; the reply language is the
one the user spoke. A rule only wins if its arguments also validate, so a loose pattern
cannot hijack a sentence meant for another tool.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from jarvis.text import normalize
from jarvis.tools.base import Tool


@dataclass(frozen=True)
class Route:
    tool: Tool[Any]
    params: BaseModel


class Router:
    def __init__(self, tools: Sequence[Tool[Any]]) -> None:
        self._rules = [
            (tool, re.compile(intent.pattern), intent.args)
            for tool in tools
            for intents in tool.intents.values()
            for intent in intents
        ]

    def route(self, text: str) -> Route | None:
        normalized = normalize(text)
        for tool, pattern, fixed_args in self._rules:
            match = pattern.fullmatch(normalized)
            if match is None:
                continue
            spoken = {name: value for name, value in match.groupdict().items() if value}
            args = {**fixed_args, **spoken}
            if not tool.accepts(args):
                continue
            try:
                return Route(tool, tool.parse(args))
            except ValidationError:
                continue
        return None
