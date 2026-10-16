import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import httpx2
import pytest

from jarvis.config import NewsConfig, NewsFeed, NewsTopic
from jarvis.i18n import Language, Translator
from jarvis.tools.base import ToolResult, render
from jarvis.tools.news import (
    NewsParams,
    NewsService,
    NewsTool,
    Story,
    merge_duplicates,
    top_headlines,
)

BRT = timezone(timedelta(hours=-3))
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=BRT)  # 15:00 UTC
TRANSLATOR = Translator.load()

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Tecnoblog</title>
<item><title>Apple lan\xc3\xa7a novo iPhone</title><link>https://tecnoblog.net/1</link>
  <pubDate>Tue, 13 Oct 2026 12:00:00 +0000</pubDate></item>
<item><title>Vazamento exp\xc3\xb5e dados de clientes</title><link>https://tecnoblog.net/2</link>
  <pubDate>Tue, 13 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Uma not\xc3\xadcia antiga</title><link>https://tecnoblog.net/3</link>
  <pubDate>Fri, 09 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Sem data</title><link>https://tecnoblog.net/4</link></item>
</channel></rss>"""

GOOGLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Apple lan\xc3\xa7a novo iPhone - Folha</title><link>https://news.google.com/a</link>
  <pubDate>Tue, 13 Oct 2026 13:00:00 GMT</pubDate><source url="https://folha.uol.com.br">Folha</source></item>
<item><title>IA muda o mercado de trabalho - g1</title><link>https://news.google.com/b</link>
  <pubDate>Tue, 13 Oct 2026 14:00:00 GMT</pubDate><source url="https://g1.globo.com">g1</source></item>
</channel></rss>"""

CONFIG = NewsConfig(
    max_age_hours=24,
    per_source_limit=15,
    cache_minutes=15,
    request_timeout_s=5,
    duplicate_threshold=85,
    spoken_stories=4,
    briefing_stories=3,
    feeds=[NewsFeed(name="Tecnoblog", url="https://tecnoblog.net/feed/", language=Language.PT)],
    topics=[NewsTopic(query="tecnologia", language=Language.PT)],
)


class Network:
    """Canned feeds by host; ``down`` hosts answer 503. Records every URL asked for."""

    def __init__(self, down: Sequence[str] = ()) -> None:
        self.down = set(down)
        self.asked: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(str(request.url))
        host = request.url.host
        if host in self.down:
            return httpx2.Response(503)
        return httpx2.Response(200, content=GOOGLE if host == "news.google.com" else FEED)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeSummarizer:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.asked: list[tuple[int, Language, str | None]] = []
        self.introduced: list[bool] = []

    async def summarize(
        self,
        stories: Sequence[Story],
        count: int,
        language: Language,
        topic: str | None,
        introduce: bool = True,
    ) -> str | None:
        self.asked.append((count, language, topic))
        self.introduced.append(introduce)
        return self.text


def service(
    network: Network,
    summarizer: FakeSummarizer | None = None,
    config: NewsConfig = CONFIG,
    clock: Clock | None = None,
) -> NewsService:
    return NewsService(
        config,
        summarizer,
        transport=httpx2.MockTransport(network.handler),
        clock=lambda: NOW,
        monotonic=clock or Clock(),
    )


def stories_of(news: NewsService, topic: str | None = None) -> list[Story] | None:
    return asyncio.run(news.stories(topic))


def bulletin(news: NewsService, count: int = 2, topic: str | None = None) -> ToolResult:
    return asyncio.run(news.bulletin(count, Language.PT, topic))


def test_feeds_are_filtered_by_age_and_merged() -> None:
    stories = stories_of(service(Network()))

    assert stories is not None
    assert [(s.title, s.source, s.coverage) for s in stories] == [
        ("Apple lança novo iPhone", "Tecnoblog", 2),  # also on Google News, via Folha
        ("Vazamento expõe dados de clientes", "Tecnoblog", 1),
        ("IA muda o mercado de trabalho", "g1", 1),  # " - g1" removed from the title
    ]


def test_sources_are_cached_for_a_while() -> None:
    network, clock = Network(), Clock()
    news = service(network, clock=clock)

    stories_of(news)
    stories_of(news)
    assert len(network.asked) == 2
    clock.now = 16 * 60
    stories_of(news)
    assert len(network.asked) == 4


def test_a_failing_source_is_skipped() -> None:
    stories = stories_of(service(Network(down=["tecnoblog.net"])))

    assert stories is not None and {s.source for s in stories} == {"Folha", "g1"}


def test_all_sources_failing_is_reported() -> None:
    news = service(Network(down=["tecnoblog.net", "news.google.com"]))

    assert stories_of(news) is None
    assert bulletin(news).reply.key == "news.unavailable"


def test_a_spoken_topic_searches_google_news_in_the_reply_language() -> None:
    sources = service(Network()).sources("inteligencia artificial", Language.EN)

    assert len(sources) == 1
    assert "q=inteligencia+artificial+when%3A24h" in sources[0].url
    assert "hl=en-US" in sources[0].url


def test_the_summarizer_tells_the_main_stories() -> None:
    summarizer = FakeSummarizer("Bom dia, senhor. A Apple lançou um novo iPhone.")

    result = bulletin(service(Network(), summarizer), count=3)

    assert result.reply.key == "news.bulletin"
    assert summarizer.asked == [(3, Language.PT, None)]
    assert result.details is not None and "https://tecnoblog.net/2" in result.details


@pytest.mark.parametrize("summarizer", [None, FakeSummarizer(None)])
def test_without_a_summary_the_most_carried_headlines_are_read(
    summarizer: FakeSummarizer | None,
) -> None:
    result = bulletin(service(Network(), summarizer), count=2)

    assert render(result.reply, TRANSLATOR, Language.PT) == (
        "As principais manchetes, senhor: Apple lança novo iPhone; IA muda o mercado de trabalho."
    )


def test_no_recent_news() -> None:
    old = CONFIG.model_copy(update={"max_age_hours": 0.5})

    assert bulletin(service(Network(), config=old)).reply.key == "news.none"
    assert bulletin(service(Network(), config=old), topic="apple").reply.key == "news.none_about"


def test_the_tool_uses_the_spoken_count_and_reply_language() -> None:
    summarizer = FakeSummarizer("Boletim.")
    tool = NewsTool(service(Network(), summarizer), lambda: Language.EN, stories=4)

    asyncio.run(tool.run(NewsParams(topic="apple")))

    assert summarizer.asked == [(4, Language.EN, "apple")]


def story(title: str, minutes_ago: int = 0, coverage: int = 1) -> Story:
    published = NOW - timedelta(minutes=minutes_ago)
    return Story(title, "src", "https://x", published, Language.EN, coverage)


def test_near_identical_titles_count_as_one_story() -> None:
    merged = merge_duplicates(
        [story("OpenAI releases GPT update"), story("OpenAI releases GPT update!"), story("Other")],
        threshold=85,
    )

    assert [(s.title, s.coverage) for s in merged] == [
        ("OpenAI releases GPT update", 2),
        ("Other", 1),
    ]


def test_top_headlines_prefer_coverage_then_recency() -> None:
    stories = [story("old", 300), story("wide", 600, coverage=3), story("new", 5)]

    assert [s.title for s in top_headlines(stories, 2)] == ["wide", "new"]


def test_the_briefing_can_skip_the_bulletins_introduction() -> None:
    summarizer = FakeSummarizer("Boletim.")

    asyncio.run(service(Network(), summarizer).bulletin(3, Language.PT, introduce=False))

    assert summarizer.introduced == [False]


def test_the_background_refresh_reads_the_feeds_again() -> None:
    network = Network()
    news = service(network)

    stories_of(news)
    asyncio.run(news.stories(refresh=True))  # what keep_fresh does before the cache expires

    assert len(network.asked) == 4  # both sources, twice
