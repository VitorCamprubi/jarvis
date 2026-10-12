"""Weather now, today and tomorrow, from Open-Meteo (free, no key; ADR-032)."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Self

import httpx2
from pydantic import BaseModel, Field, model_validator

from jarvis.config import WeatherConfig
from jarvis.i18n import Language
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_S = 8.0

WHEN_WORDS = {
    "agora": "now", "now": "now", "right now": "now",
    "hoje": "today", "today": "today",
    "amanha": "tomorrow", "tomorrow": "tomorrow",
}  # fmt: skip


def condition_key(code: int) -> str:
    """WMO weather interpretation code -> i18n key of a spoken condition."""
    if code == 0:
        group = "clear"
    elif code in (1, 2):
        group = "partly_cloudy"
    elif code == 3:
        group = "overcast"
    elif code in (45, 48):
        group = "fog"
    elif 51 <= code <= 57:
        group = "drizzle"
    elif 61 <= code <= 67 or 80 <= code <= 82:
        group = "rain"
    elif 71 <= code <= 77 or code in (85, 86):
        group = "snow"
    elif code >= 95:
        group = "thunderstorm"
    else:
        group = "unknown"
    return f"weather.codes.{group}"


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    latitude: float
    longitude: float
    timezone: str


@dataclass(frozen=True)
class DayForecast:
    day: date
    code: int
    max_c: float
    min_c: float
    rain_chance: int


@dataclass(frozen=True)
class Forecast:
    temperature_c: float
    feels_like_c: float
    code: int
    days: tuple[DayForecast, ...]  # today, tomorrow


class WeatherClient:
    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests pass a MockTransport

    async def geocode(self, name: str, language: Language = Language.PT) -> Place | None:
        """The most populous place with that name in Portuguese or English.

        Open-Meteo only matches names in the language asked: "londres" in English is a village
        in Argentina, "new york" in Portuguese is not found. Asking in both and keeping the
        largest place picks the city people mean; on a tie (the same city found in both), the
        name in the reply language wins: "London" in English, "Londres" in Portuguese.
        """
        languages = [language, *(other for other in Language if other is not language)]
        answers = await asyncio.gather(
            *(
                self._get(
                    GEOCODING_URL, {"name": name, "count": 5, "language": lang, "format": "json"}
                )
                for lang in languages
            )
        )
        results = [result for data in answers for result in data.get("results") or []]
        if not results:
            return None
        best = max(results, key=lambda result: result.get("population") or 0)
        return Place(
            best["name"],
            best.get("admin1", ""),
            best["latitude"],
            best["longitude"],
            best.get("timezone", "auto"),
        )

    async def forecast(self, place: Place) -> Forecast:
        data = await self._get(
            FORECAST_URL,
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "timezone": place.timezone,
                "current": "temperature_2m,apparent_temperature,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max",
                "forecast_days": 2,
            },
        )
        current, daily = data["current"], data["daily"]
        days = tuple(
            DayForecast(
                date.fromisoformat(daily["time"][i]),
                int(daily["weather_code"][i]),
                float(daily["temperature_2m_max"][i]),
                float(daily["temperature_2m_min"][i]),
                int(daily["precipitation_probability_max"][i] or 0),
            )
            for i in range(len(daily["time"]))
        )
        return Forecast(
            float(current["temperature_2m"]),
            float(current["apparent_temperature"]),
            int(current["weather_code"]),
            days,
        )

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx2.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data


class WeatherParams(BaseModel):
    when: Literal["now", "today", "tomorrow"] = Field(
        default="now", description="Current conditions, today's or tomorrow's forecast"
    )
    city: str | None = Field(default=None, description="City name; omit for the default city")

    @model_validator(mode="before")
    @classmethod
    def _spoken(cls, data: Any) -> Any:
        """Rule matches give "hoje"/"amanha"/... in "when" or, later in the sentence, "when2"."""
        if isinstance(data, dict):
            data = dict(data)
            spoken = data.pop("when2", None) or data.get("when")
            if spoken is not None:
                data["when"] = WHEN_WORDS.get(str(spoken), spoken)
        return data

    @model_validator(mode="after")
    def _blank_city_means_default(self) -> Self:
        if self.city is not None and not self.city.strip():
            self.city = None
        return self


WHEN_PT = r"(?P<when>hoje|amanha|agora)"
WHEN_EN = r"(?P<when>today|tomorrow|now|right now)"
PLACE_PT = (
    rf"(?: (?:para|pra))?(?: {WHEN_PT})?(?: (?:em|no|na) (?P<city>[a-z ]+?))?"
    r"(?: (?P<when2>hoje|amanha|agora))?"
)
PLACE_EN = (
    rf"(?: for)?(?: {WHEN_EN})?(?: in (?P<city>[a-z ]+?))?(?: (?P<when2>today|tomorrow|now))?"
)


class WeatherTool(Tool[WeatherParams]):
    name = "weather"
    description = (
        "Weather for a city: current conditions, or today's or tomorrow's forecast (high, low, "
        "chance of rain). Returns the figures for you to answer the user's actual question."
    )
    params_model = WeatherParams
    intents = phrasings(
        pt=(
            Intent(rf"vai chover{PLACE_PT}", {"when": "today"}),
            Intent(
                r"(?:como (?:esta|ta|vai estar|vai ficar|fica) o (?:tempo|clima)|qual (?:e )?"
                r"(?:a )?previsao(?: do tempo)?|previsao do tempo|quantos graus"
                r"(?: (?:esta fazendo|faz|esta))?|(?:esta|ta) (?:fazendo )?(?:calor|frio))"
                rf"{PLACE_PT}"
            ),
        ),
        en=(
            Intent(rf"(?:will it|is it going to) rain{PLACE_EN}", {"when": "today"}),
            Intent(
                r"(?:(?:whats|what is) the (?:weather|forecast)(?: like)?|hows the weather"
                rf"|how (?:hot|cold|warm) is it(?: outside)?){PLACE_EN}"
            ),
        ),
    )

    def __init__(
        self,
        client: WeatherClient,
        default: WeatherConfig,
        language: Callable[[], Language] = lambda: Language.PT,
    ) -> None:
        self._client = client
        self._language = language  # the reply language, for the city's name
        self._default = Place(
            default.city, default.region, default.latitude, default.longitude, default.timezone
        )

    async def run(self, params: WeatherParams) -> ToolResult:
        try:
            place = (
                self._default
                if params.city is None
                else await self._client.geocode(params.city, self._language())
            )
            if place is None:
                return ToolResult(
                    Reply("weather.city_not_found", {"city": params.city}, cacheable=False),
                    model_data=f"City {params.city!r} not found.",
                )
            forecast = await self._client.forecast(place)
        except (httpx2.HTTPError, KeyError, ValueError, IndexError) as exc:
            log.warning("Weather service failed: %s", exc)
            return ToolResult(
                Reply("weather.unavailable"), model_data="The weather service did not respond."
            )
        return ToolResult(
            self._reply(place, forecast, params.when),
            details=describe(place, forecast),
            model_data=describe(place, forecast),
        )

    @staticmethod
    def _reply(place: Place, forecast: Forecast, when: str) -> Reply:
        if when == "now":
            return Reply(
                "weather.now",
                {
                    "place": place.name,
                    "temp": round(forecast.temperature_c),
                    "condition": Reply(condition_key(forecast.code)),
                },
                cacheable=False,
            )
        index = 0 if when == "today" else 1
        day = forecast.days[min(index, len(forecast.days) - 1)]
        return Reply(
            "weather.day",
            {
                "place": place.name,
                "day": Reply(f"weather.days.{when}"),
                "condition": Reply(condition_key(day.code)),
                "max": round(day.max_c),
                "min": round(day.min_c),
                "rain": day.rain_chance,
            },
            cacheable=False,
        )


def describe(place: Place, forecast: Forecast) -> str:
    lines = [
        f"{place.name}, {place.region}: now {forecast.temperature_c:.0f} C (feels like "
        f"{forecast.feels_like_c:.0f} C), {condition_key(forecast.code).rsplit('.', 1)[-1]}"
    ]
    for label, day in zip(("today", "tomorrow"), forecast.days, strict=False):
        lines.append(
            f"{label} ({day.day:%A}): {condition_key(day.code).rsplit('.', 1)[-1]}, high "
            f"{day.max_c:.0f} C, low {day.min_c:.0f} C, chance of rain {day.rain_chance}%"
        )
    return "\n".join(lines)
