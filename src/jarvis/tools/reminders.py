"""Reminders: create, list and cancel by voice; announced when due, even after a restart.

Rule matches hand the whole sentence over; the time expression is found in it (ADR-030) and
the remaining words, with their original accents, become the reminder's text. The LLM passes
the text and an ISO date-time instead.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Self

from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from jarvis.i18n import Language
from jarvis.storage import Reminder, ReminderStore
from jarvis.text import POLITENESS, WAKE_WORDS, name_score, normalize, simplify
from jarvis.text.when import find_time
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]
Announcer = Callable[[Reminder, bool], None]  # reminder, overdue (was due while closed)


def local_now() -> datetime:
    return datetime.now().astimezone()


COMMAND = re.compile(  # an optional "Jarvis", then the command words: neither is reminder text
    rf"^(?:(?:{'|'.join(WAKE_WORDS)})\b ?)?"
    r"(?:(?:me )?(?:lembra|lembre|lembrar|avisa|avise)(?: me)?"
    r"|(?:cria|crie|adiciona|adicione|coloca|coloque|poe|ponha) (?:um )?lembrete"
    r"|remind me|(?:set|create|add) a reminder)?\b"
)
POLITE = re.compile(rf"\b(?:{'|'.join(POLITENESS)})\b")
LATEST_WORDS = {"ultimo", "last", "latest"}  # "cancela o último lembrete"
CANCEL_THRESHOLD = 70.0  # how close the spoken words must be to a reminder's text
LEADING = re.compile(r"^(?:de|do|da|que|pra|para|para que|to|that|about|of)\s+", re.IGNORECASE)


def split_reminder(utterance: str, now: datetime, default_hour: int) -> tuple[str, datetime] | None:
    """("me lembra de ligar pra mãe amanhã às 9") -> ("ligar pra mãe", tomorrow 9:00).

    Each original word is normalised separately, so spans found in the normalised sentence
    map back to original words and the text keeps its accents for the voice.
    """
    words = utterance.split()
    pieces: list[tuple[int, int, int]] = []  # (start, end, word index) in the joined text
    joined = ""
    for index, word in enumerate(words):
        piece = simplify(word)
        if piece:
            start = len(joined) + (1 if joined else 0)
            joined = f"{joined} {piece}" if joined else piece
            pieces.append((start, len(joined), index))
    match = find_time(joined, now, default_hour)
    if match is None:
        return None
    spans = [*match.spans, *(polite.span() for polite in POLITE.finditer(joined))]
    covered = {
        index
        for start, end, index in pieces
        for span_start, span_end in spans
        if start < span_end and span_start < end
    }
    command = COMMAND.match(joined)
    if command:
        covered |= {index for start, end, index in pieces if end <= command.end()}
    text = " ".join(word for index, word in enumerate(words) if index not in covered)
    text = text.strip(" ,.;:!?")
    while (cleaned := LEADING.sub("", text)) != text:
        text = cleaned
    return text, match.due_at


def when_reply(due: datetime, now: datetime) -> Reply:
    """How a due time is said: "in 20 minutes", "at 6 pm", "tomorrow at 9"..."""
    minutes = round((due - now).total_seconds() / 60)
    if minutes < 60:
        return Reply("reminders.when.minutes", {"minutes": max(1, minutes)})
    clock = time_reply(due)
    if due.date() == now.date():
        return Reply("reminders.when.today", {"time": clock})
    if due.date() == now.date() + timedelta(days=1):
        return Reply("reminders.when.tomorrow", {"time": clock})
    return Reply("reminders.when.date", {"day": due.day, "month": due.month, "time": clock})


def time_reply(moment: datetime) -> Reply:
    hour12 = moment.hour % 12 or 12
    params = {
        "h24": moment.hour,
        "h12": hour12,
        "m": moment.minute,
        "ampm": "AM" if moment.hour < 12 else "PM",
    }
    return Reply("time.exact" if moment.minute == 0 else "time.with_minutes", params)


class ReminderService:
    """Stores reminders and announces each one when it falls due."""

    def __init__(self, store: ReminderStore, clock: Clock = local_now) -> None:
        self._store = store
        self._clock = clock
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._announce: Announcer | None = None

    async def start(self, announce: Announcer) -> None:
        """Announce what fell due while JARVIS was closed, then keep watching."""
        self._announce = announce
        now = self._clock()
        for reminder in await self._store.pending():
            if reminder.due_at <= now:
                await self._fire(reminder, overdue=True)
        self._task = asyncio.create_task(self._watch(), name="jarvis-reminders")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def add(self, text: str, due_at: datetime, language: Language) -> Reminder:
        reminder = await self._store.add(text, due_at, language, self._clock())
        self._wake.set()  # the new one may be due before the one being waited for
        log.info("Reminder %d set for %s", reminder.id, due_at.isoformat(timespec="minutes"))
        return reminder

    async def pending(self) -> list[Reminder]:
        return await self._store.pending()

    async def cancel(self, reminder: Reminder) -> None:
        await self._store.set_status(reminder.id, "cancelled")
        self._wake.set()

    async def _watch(self) -> None:
        while True:
            pending = await self._store.pending()
            now = self._clock()
            for reminder in pending:
                if reminder.due_at <= now:
                    await self._fire(reminder, overdue=False)
            upcoming = [r for r in pending if r.due_at > now]
            timeout = (upcoming[0].due_at - now).total_seconds() if upcoming else None
            self._wake.clear()
            # Sleep until the next one is due, or until add()/cancel() changes the list.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout)

    async def _fire(self, reminder: Reminder, overdue: bool) -> None:
        await self._store.set_status(reminder.id, "done")
        log.info("Reminder %d due%s", reminder.id, " (overdue)" if overdue else "")
        if self._announce is not None:
            self._announce(reminder, overdue)


class CreateReminderParams(BaseModel):
    text: str | None = Field(default=None, description="What to remind the user about")
    due_at: datetime | None = Field(
        default=None, description="When, as a local ISO 8601 date-time, e.g. 2026-10-12T18:00"
    )
    # Rule matches pass the whole sentence; it is not part of the LLM's schema.
    utterance: SkipJsonSchema[str | None] = None

    @model_validator(mode="after")
    def _something_to_parse(self) -> Self:
        if self.utterance is None and (not self.text or self.due_at is None):
            raise ValueError("needs 'text' and 'due_at'")
        return self


class CreateReminderTool(Tool[CreateReminderParams]):
    name = "create_reminder"
    description = (
        "Set a reminder. JARVIS announces it out loud when due, even after a restart. "
        "Give the text in the user's words and the local date-time."
    )
    params_model = CreateReminderParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:me )?(?:lembra|lembre|lembrar|avisa|avise)(?: me)? .+"
                r"|(?:cria|crie|adiciona|adicione|coloca|coloque|poe|ponha) (?:um )?lembrete .+"
            ),
        ),
        en=(Intent(r"remind me .+|(?:set|create|add) a reminder .+"),),
    )

    def __init__(
        self,
        service: ReminderService,
        language: Callable[[], Language],
        default_hour: int,
        clock: Clock = local_now,
    ) -> None:
        self._service = service
        self._language = language  # the reply language when the reminder is created
        self._default_hour = default_hour
        self._clock = clock

    async def run(self, params: CreateReminderParams) -> ToolResult:
        now = self._clock()
        if params.utterance is not None:  # a rule match: find the time in the sentence
            parsed = split_reminder(params.utterance, now, self._default_hour)
            if parsed is None:
                return ToolResult(Reply("reminders.need_time"))
            text, due_at = parsed
        elif params.due_at is not None:  # the LLM gives text and local time
            text = params.text or ""
            due_at = (
                params.due_at if params.due_at.tzinfo else params.due_at.replace(tzinfo=now.tzinfo)
            )
        else:
            return ToolResult(Reply("reminders.need_time"))
        if not text:
            return ToolResult(Reply("reminders.need_text"))
        if due_at <= now:
            return ToolResult(Reply("reminders.in_the_past"))
        await self._service.add(text, due_at, self._language())
        when = when_reply(due_at, now)
        return ToolResult(Reply("reminders.created", {"text": text, "when": when}, cacheable=False))


class ListRemindersParams(BaseModel):
    pass


class ListRemindersTool(Tool[ListRemindersParams]):
    name = "list_reminders"
    description = "List the pending reminders, soonest first."
    params_model = ListRemindersParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:quais|que) (?:sao )?(?:os )?(?:meus )?lembretes(?: (?:tenho|eu tenho))?"
                r"|(?:lista|listar|mostra|mostre|fala|diz)(?: os| meus)? lembretes"
                r"|(?:eu )?tenho (?:algum |alguns )?lembretes?"
            ),
        ),
        en=(
            Intent(
                r"(?:what are|list|show|read)(?: me)? (?:my )?reminders"
                r"|(?:do i have )?any reminders|what reminders do i have"
            ),
        ),
    )

    def __init__(self, service: ReminderService, clock: Clock = local_now) -> None:
        self._service = service
        self._clock = clock

    async def run(self, params: ListRemindersParams) -> ToolResult:
        pending = await self._service.pending()
        if not pending:
            return ToolResult(Reply("reminders.none"), model_data="No pending reminders.")
        now = self._clock()
        listing = "\n".join(
            f"- {r.text} at {r.due_at.astimezone():%Y-%m-%d %H:%M}" for r in pending
        )
        first = pending[0]
        reply = Reply(
            "reminders.list_one" if len(pending) == 1 else "reminders.list",
            {"count": len(pending), "text": first.text, "when": when_reply(first.due_at, now)},
            cacheable=False,
        )
        return ToolResult(reply, details=listing, model_data=listing)


class CancelReminderParams(BaseModel):
    query: str | None = Field(
        default=None, description="Words from the reminder's text; omit to cancel the latest one"
    )


class CancelReminderTool(Tool[CancelReminderParams]):
    name = "cancel_reminder"
    description = "Cancel a pending reminder, found by words from its text (or the latest one)."
    params_model = CancelReminderParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:cancela|cancele|cancelar|apaga|apague|remove|remova|tira|tire) "
                r"(?:o |esse |este |aquele )?lembrete(?: (?:de|do|da|para|pra|sobre))?"
                r"(?: (?P<query>.+))?"
            ),
        ),
        en=(
            Intent(
                r"(?:cancel|delete|remove) (?:the |my |that |this )?reminder"
                r"(?: (?:about|to|for|of))?(?: (?P<query>.+))?"
            ),
        ),
    )

    def __init__(self, service: ReminderService) -> None:
        self._service = service

    async def run(self, params: CancelReminderParams) -> ToolResult:
        pending = await self._service.pending()
        if not pending:
            return ToolResult(Reply("reminders.none"))
        query = normalize(params.query or "")
        if not query or query in LATEST_WORDS:
            target = max(pending, key=lambda r: r.created_at)
        else:
            scored = [(name_score(query, normalize(r.text)), r) for r in pending]
            score, target = max(scored, key=lambda pair: pair[0])
            if score < CANCEL_THRESHOLD:
                return ToolResult(
                    Reply("reminders.not_found", {"query": params.query}, cacheable=False)
                )
        await self._service.cancel(target)
        return ToolResult(Reply("reminders.cancelled", {"text": target.text}, cacheable=False))
