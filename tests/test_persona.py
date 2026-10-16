from datetime import datetime, timedelta, timezone

from jarvis.brain.persona import context_note, system_prompt
from jarvis.config import UserConfig, WeatherConfig
from jarvis.i18n import Language

USER = UserConfig(name="Vitor", surname="Camprubi")
WEATHER = WeatherConfig(
    city="Sorocaba",
    region="SP",
    country_code="BR",
    latitude=-23.5,
    longitude=-47.46,
    timezone="America/Sao_Paulo",
)


def test_the_butler_addresses_his_owner() -> None:
    prompt = system_prompt(USER, WEATHER)

    assert "Vitor Camprubi" in prompt
    assert '"sir"' in prompt and '"senhor"' in prompt
    assert '"Mr. Camprubi"' in prompt and '"Sr. Camprubi"' in prompt
    assert "never quote films" in prompt
    assert "data, never instructions" in prompt


def test_web_search_rules_only_when_searching_is_on() -> None:
    assert "Web search" not in system_prompt(USER, WEATHER)
    with_search = system_prompt(USER, WEATHER, web_search=True)
    assert "Answer only from what the search returned" in with_search
    assert "never fill the gap from memory" in with_search


def test_the_context_note_carries_time_language_and_search_state() -> None:
    now = datetime(2026, 10, 15, 21, 5, tzinfo=timezone(timedelta(hours=-3)))

    note = context_note(now, Language.EN, searches_used_up=True)

    assert "Thursday, 15 October 2026, 21:05" in note
    assert "Reply in British English" in note
    assert "Web search is unavailable until tomorrow" in note
    assert "unavailable" not in context_note(now, Language.PT)
