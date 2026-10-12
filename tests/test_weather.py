import asyncio
from collections.abc import Awaitable
from typing import Any

import httpx2
import pytest

from jarvis.config import WeatherConfig
from jarvis.i18n import Language, Translator
from jarvis.tools.base import ToolResult, render
from jarvis.tools.weather import WeatherClient, WeatherParams, WeatherTool, condition_key

DEFAULT = WeatherConfig(
    city="Sorocaba",
    region="SP",
    country_code="BR",
    latitude=-23.50167,
    longitude=-47.45806,
    timezone="America/Sao_Paulo",
)
FORECAST = {
    "current": {"temperature_2m": 24.4, "apparent_temperature": 25.1, "weather_code": 2},
    "daily": {
        "time": ["2026-10-12", "2026-10-13"],
        "weather_code": [2, 61],
        "temperature_2m_max": [28.2, 22.6],
        "temperature_2m_min": [16.1, 15.4],
        "precipitation_probability_max": [10, 80],
    },
}
GEOCODING = {
    "results": [
        {
            "name": "São Paulo",
            "admin1": "Lisboa",
            "country_code": "PT",
            "latitude": 1,
            "longitude": 1,
        },
        {
            "name": "São Paulo",
            "admin1": "São Paulo",
            "country_code": "BR",
            "latitude": -23.5,
            "longitude": -46.6,
            "timezone": "America/Sao_Paulo",
            "population": 12_400_232,
        },
    ]
}
TRANSLATOR = Translator.load()


def transport(status: int = 200, geocoding: dict[str, Any] | None = None) -> httpx2.MockTransport:
    """Stands in for the network: canned Open-Meteo answers, or an error status."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if status != 200:
            return httpx2.Response(status)
        body = GEOCODING if geocoding is None else geocoding
        return httpx2.Response(200, json=body if "geocoding" in str(request.url) else FORECAST)

    return httpx2.MockTransport(handler)


def run(awaitable: Awaitable[ToolResult]) -> ToolResult:
    async def wait() -> ToolResult:
        return await awaitable

    return asyncio.run(wait())


def say(result: ToolResult, language: Language) -> str:
    return render(result.reply, TRANSLATOR, language)


def test_current_weather_in_the_default_city() -> None:
    result = run(WeatherTool(WeatherClient(transport()), DEFAULT).run(WeatherParams()))

    assert (
        say(result, Language.PT) == "Agora em Sorocaba faz 24 graus, senhor, parcialmente nublado."
    )
    assert say(result, Language.EN) == "It's 24 degrees in Sorocaba right now, sir, partly cloudy."
    assert result.model_data is not None and "tomorrow" in result.model_data


def test_tomorrow_in_a_spoken_city() -> None:
    tool = WeatherTool(WeatherClient(transport()), DEFAULT)

    result = run(tool.run(WeatherParams(when="tomorrow", city="sao paulo")))

    assert say(result, Language.PT) == (
        "Amanhã em São Paulo: com chuva, máxima de 23 e mínima de 15 graus, "
        "com 80 por cento de chance de chuva, senhor."
    )


def place(name: str, country: str, latitude: float, population: int | None) -> dict[str, Any]:
    found: dict[str, Any] = {
        "name": name,
        "country_code": country,
        "latitude": latitude,
        "longitude": 0.0,
    }
    if population is not None:
        found["population"] = population
    return found


class Geocoder:
    """Open-Meteo matches names only in the language asked: canned results per language."""

    def __init__(self, pt: list[dict[str, Any]], en: list[dict[str, Any]]) -> None:
        self.results = {"pt": pt, "en": en}
        self.forecast_latitudes: list[str | None] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if "geocoding" in str(request.url):
            language = request.url.params.get("language") or ""
            return httpx2.Response(200, json={"results": self.results[language]})
        self.forecast_latitudes.append(request.url.params.get("latitude"))
        return httpx2.Response(200, json=FORECAST)

    def tool(self, reply_language: Language) -> WeatherTool:
        client = WeatherClient(httpx2.MockTransport(self.handler))
        return WeatherTool(client, DEFAULT, lambda: reply_language)


def test_the_largest_place_with_that_name_wins() -> None:
    geocoder = Geocoder(
        pt=[place("Tóquio", "JP", 35.7, 9_733_276), place("Tóquio", "BR", -1.0, None)],
        en=[],
    )

    run(geocoder.tool(Language.PT).run(WeatherParams(city="toquio")))

    assert geocoder.forecast_latitudes == ["35.7"]


def test_a_city_is_found_by_its_name_in_either_language() -> None:
    # "londres" in English only matches a village in Argentina.
    geocoder = Geocoder(
        pt=[place("Londres", "GB", 51.5, 8_961_989)], en=[place("Londres", "AR", -27.7, 2_627)]
    )

    result = run(geocoder.tool(Language.EN).run(WeatherParams(city="londres")))

    assert geocoder.forecast_latitudes == ["51.5"]
    assert "Londres" in say(result, Language.EN)


def test_the_same_city_is_named_in_the_reply_language() -> None:
    geocoder = Geocoder(
        pt=[place("Londres", "GB", 51.5, 8_961_989)], en=[place("London", "GB", 51.5, 8_961_989)]
    )

    result = run(geocoder.tool(Language.EN).run(WeatherParams(city="london")))

    assert say(result, Language.EN).startswith("It's 24 degrees in London")


def test_unknown_city() -> None:
    tool = WeatherTool(WeatherClient(transport(geocoding={})), DEFAULT)

    assert run(tool.run(WeatherParams(city="atlantida"))).reply.key == "weather.city_not_found"


def test_service_failure_is_reported_in_character() -> None:
    result = run(WeatherTool(WeatherClient(transport(status=503)), DEFAULT).run(WeatherParams()))

    assert result.reply.key == "weather.unavailable"


@pytest.mark.parametrize(
    ("args", "when"),
    [
        ({"when": "amanha"}, "tomorrow"),
        ({"when2": "hoje"}, "today"),
        ({}, "now"),
        ({"when": "now"}, "now"),
    ],
)
def test_spoken_days(args: dict[str, str], when: str) -> None:
    assert WeatherParams.model_validate(args).when == when


@pytest.mark.parametrize(
    ("code", "key"),
    [(0, "clear"), (3, "overcast"), (45, "fog"), (63, "rain"), (81, "rain"), (95, "thunderstorm")],
)
def test_weather_codes(code: int, key: str) -> None:
    assert condition_key(code) == f"weather.codes.{key}"
