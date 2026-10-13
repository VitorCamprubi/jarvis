"""The morning briefing (ADR-036): greeting, today's weather, today's reminders, main news.

The running order is fixed and assembled here; weather and news are fetched in parallel, and
each part reports its own failure in character without spoiling the rest.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel

from jarvis.i18n import Language
from jarvis.text.when import part_of_day
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.tools.news import NewsService
from jarvis.tools.reminders import ReminderService, time_reply
from jarvis.tools.weather import WeatherParams, WeatherTool


class BriefingParams(BaseModel):
    pass


class BriefingTool(Tool[BriefingParams]):
    name = "morning_briefing"
    description = (
        "Gives the daily briefing: greeting, today's weather, today's reminders and the main "
        "tech news. Speaks for itself: do not add to its answer."
    )
    params_model = BriefingParams
    intents = phrasings(
        pt=(
            Intent(r"bom dia(?: jarvis)?"),
            Intent(
                r"(?:(?:me )?(?:da|de|faz|faca|le|leia) )?(?:o |um |meu )?"
                r"(?:briefing|resumo do dia)(?: do dia| matinal| de hoje)?"
            ),
        ),
        en=(
            Intent(r"good morning(?: jarvis)?"),
            Intent(r"(?:(?:give|read) me )?(?:the |my )?(?:morning |daily )?briefing"),
        ),
    )

    def __init__(
        self,
        weather: WeatherTool,
        reminders: ReminderService,
        news: NewsService,
        language: Callable[[], Language],
        stories: int,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._weather = weather
        self._reminders = reminders
        self._news = news
        self._language = language
        self._stories = stories
        self._clock = clock

    async def run(self, params: BriefingParams) -> ToolResult:
        now = self._clock()
        weather, news = await asyncio.gather(
            self._weather.run(WeatherParams(when="today")),
            self._news.bulletin(self._stories, self._language(), introduce=False),
        )
        reply = Reply(
            "briefing.full",
            {
                "greeting": Reply(f"briefing.greeting.{part_of_day(now.hour)}"),
                "weather": weather.reply,
                "reminders": await self._todays_reminders(now),
                "news": news.reply,
            },
            cacheable=False,
        )
        details = "\n\n".join(part for part in (weather.details, news.details) if part)
        return ToolResult(reply, details=details or None)

    async def _todays_reminders(self, now: datetime) -> Reply:
        today = [
            reminder
            for reminder in await self._reminders.pending()
            if reminder.due_at.astimezone(now.tzinfo).date() == now.date()
        ]
        if not today:
            return Reply("briefing.reminders.none")
        first = today[0]  # soonest first
        params = {
            "count": len(today),
            "text": first.text,
            "time": time_reply(first.due_at.astimezone(now.tzinfo)),
        }
        key = "briefing.reminders.one" if len(today) == 1 else "briefing.reminders.many"
        return Reply(key, params, cacheable=False)
