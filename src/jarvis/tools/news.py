"""Tech news of the day from RSS feeds and Google News (ADR-035).

Feeds are fetched in parallel, kept to the last hours, cut to the newest stories of each
source and de-duplicated by similar titles. A summariser (Claude) picks the main stories and
tells them in the reply language; without one, the headlines carried by most sources are read
out instead. Headlines are data: they only ever reach the LLM as a list to summarise.
"""

import asyncio
import calendar
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote_plus

import feedparser
import httpx2
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from jarvis.config import NewsConfig
from jarvis.i18n import Language
from jarvis.text import simplify
from jarvis.tools.base import Intent, Link, Reply, Tool, ToolResult, phrasings

log = logging.getLogger(__name__)

USER_AGENT = "JARVIS/0.1 (personal voice assistant; RSS reader)"
GOOGLE_NEWS = "https://news.google.com/rss/search"
GOOGLE_EDITIONS = {
    Language.PT: "hl=pt-BR&gl=BR&ceid=BR:pt-419",
    Language.EN: "hl=en-US&gl=US&ceid=US:en",
}


@dataclass(frozen=True)
class Story:
    title: str
    source: str
    url: str
    published: datetime  # UTC
    language: Language
    coverage: int = 1  # how many sources carried it


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str
    language: Language
    from_google: bool = False  # Google News titles end in " - Publisher"


class Summarizer(Protocol):
    async def summarize(
        self,
        stories: Sequence[Story],
        count: int,
        language: Language,
        topic: str | None,
        introduce: bool = True,  # False inside the morning briefing, which has its own opening
    ) -> str | None:
        """A spoken bulletin of the main stories, or None when the LLM cannot help."""
        ...


def google_source(query: str, language: Language, hours: float) -> NewsSource:
    search = quote_plus(f"{query} when:{max(1, round(hours))}h")  # Google's own age filter
    url = f"{GOOGLE_NEWS}?q={search}&{GOOGLE_EDITIONS[language]}"
    return NewsSource(f"Google News: {query}", url, language, from_google=True)


def parse_feed(content: bytes, source: NewsSource) -> list[Story]:
    """Stories of one feed, undated entries left out."""
    stories = []
    for entry in feedparser.parse(content).entries:
        moment = entry.get("published_parsed") or entry.get("updated_parsed")
        title = " ".join(str(entry.get("title", "")).split())
        if moment is None or not title or not entry.get("link"):
            continue
        publisher = source.name
        if source.from_google:
            publisher = _google_publisher(entry, title)
            title = title.removesuffix(f" - {publisher}")
        published = datetime.fromtimestamp(calendar.timegm(moment), UTC)
        stories.append(Story(title, publisher, str(entry["link"]), published, source.language))
    return stories


def _google_publisher(entry: Any, title: str) -> str:
    publisher = entry.get("source", {}).get("title")
    if publisher:
        return str(publisher)
    return title.rpartition(" - ")[2] or "Google News"


def merge_duplicates(stories: Sequence[Story], threshold: float) -> list[Story]:
    """One story per headline: near-identical titles (often the same article picked up by
    Google News) count as one, carried by several sources."""
    kept: list[tuple[str, Story]] = []
    for story in stories:
        key = simplify(story.title)
        for index, (other_key, other) in enumerate(kept):
            if fuzz.token_sort_ratio(key, other_key) >= threshold:
                kept[index] = (other_key, replace(other, coverage=other.coverage + 1))
                break
        else:
            kept.append((key, story))
    return [story for _, story in kept]


def top_headlines(stories: Sequence[Story], count: int) -> list[Story]:
    """Without an LLM: the stories most sources carry, newest first among equals."""
    return sorted(stories, key=lambda s: (s.coverage, s.published), reverse=True)[:count]


def listing(stories: Sequence[Story], tz: Any = None) -> str:
    """Every story with its link, for the log."""
    return "\n".join(
        f"- {s.published.astimezone(tz):%H:%M} {s.source}: {s.title}\n  {s.url}" for s in stories
    )


class NewsService:
    def __init__(
        self,
        config: NewsConfig,
        summarizer: Summarizer | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,  # tests pass a MockTransport
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._summarizer = summarizer  # None without an LLM: headlines are read instead
        self._transport = transport
        self._clock = clock
        self._monotonic = monotonic
        self._cache: dict[str, tuple[float, list[Story]]] = {}

    def sources(self, topic: str | None, language: Language) -> list[NewsSource]:
        hours = self._config.max_age_hours
        if topic:
            return [google_source(topic, language, hours)]
        return [NewsSource(f.name, f.url, f.language) for f in self._config.feeds] + [
            google_source(t.query, t.language, hours) for t in self._config.topics
        ]

    async def stories(
        self, topic: str | None = None, language: Language = Language.PT
    ) -> list[Story] | None:
        """Recent, de-duplicated stories; None when no source could be read."""
        sources = self.sources(topic, language)
        async with httpx2.AsyncClient(
            timeout=self._config.request_timeout_s,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            fetched = await asyncio.gather(*(self._read(client, source) for source in sources))
        if all(stories is None for stories in fetched):
            return None
        oldest = self._clock() - timedelta(hours=self._config.max_age_hours)
        recent: list[Story] = []
        for stories in fetched:
            fresh = [story for story in stories or [] if story.published >= oldest]
            fresh.sort(key=lambda story: story.published, reverse=True)
            recent += fresh[: self._config.per_source_limit]
        return merge_duplicates(recent, self._config.duplicate_threshold)

    async def bulletin(
        self, count: int, language: Language, topic: str | None = None, introduce: bool = True
    ) -> ToolResult:
        stories = await self.stories(topic, language)
        if stories is None:
            return ToolResult(Reply("news.unavailable"))
        if not stories:
            if topic:
                return ToolResult(Reply("news.none_about", {"topic": topic}, cacheable=False))
            return ToolResult(Reply("news.none"))
        tz = self._clock().tzinfo
        details = listing(stories, tz)
        links = tuple(
            Link(s.title, s.url, "web", note=f"{s.source} · {s.published.astimezone(tz):%H:%M}")
            for s in stories
        )
        log.info("News: %d stories from the last %g h", len(stories), self._config.max_age_hours)
        text = None
        if self._summarizer is not None:
            text = await self._summarizer.summarize(stories, count, language, topic, introduce)
        if text:
            reply = Reply("news.bulletin", {"text": text}, cacheable=False)
            return ToolResult(reply, details, links=links)
        titles = "; ".join(story.title for story in top_headlines(stories, count))
        reply = Reply("news.headlines", {"titles": titles}, cacheable=False)
        return ToolResult(reply, details, links=links)

    async def _read(self, client: httpx2.AsyncClient, source: NewsSource) -> list[Story] | None:
        cached = self._cache.get(source.url)
        if cached and self._monotonic() - cached[0] < self._config.cache_minutes * 60:
            return cached[1]
        try:
            response = await client.get(source.url)
            response.raise_for_status()
            stories = await asyncio.to_thread(parse_feed, response.content, source)
        except httpx2.HTTPError as exc:
            log.warning("News source %s failed: %s", source.name, exc)
            return None
        self._cache[source.url] = (self._monotonic(), stories)
        return stories


class NewsParams(BaseModel):
    topic: str | None = Field(
        default=None,
        description="Subject to look for, e.g. 'Apple' or 'inteligência artificial'. "
        "Leave empty for the day's main tech news.",
    )


TOPIC_PT = r"(?: (?:sobre|de|do|da|dos|das|em)(?: (?:o|a|os|as))? (?P<topic>.+))?"
TOPIC_EN = r"(?: (?:about|on|in|from)(?: the)? (?P<topic>.+))?"


class NewsTool(Tool[NewsParams]):
    name = "news"
    description = (
        "Reads out today's main tech news from RSS feeds and Google News, optionally about "
        "a topic. Speaks for itself: do not add to its answer."
    )
    params_model = NewsParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:quais (?:sao )?|(?:me )?(?:da|de|conta|fala|le|leia|traz|traga) )?"
                r"(?:as |umas )?(?:principais |ultimas )?noticias(?: de hoje| do dia)?" + TOPIC_PT
            ),
            Intent(r"o que (?:ha|tem) de novo" + TOPIC_PT),
        ),
        en=(
            Intent(
                r"(?:what are |whats |what is |any |(?:give|tell|read) me )?(?:the )?"
                r"(?:latest |top |todays )?(?:tech )?news(?: today)?" + TOPIC_EN
            ),
            Intent(r"whats new" + TOPIC_EN),
        ),
    )

    def __init__(
        self, service: NewsService, language: Callable[[], Language], stories: int
    ) -> None:
        self._service = service
        self._language = language
        self._stories = stories

    async def run(self, params: NewsParams) -> ToolResult:
        return await self._service.bulletin(self._stories, self._language(), params.topic)
