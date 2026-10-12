"""Times said out loud, in Portuguese and English, for reminders (ADR-030).

Works on normalised text (see ``normalize``): "daqui a vinte minutos", "às 18h30",
"amanhã às 9", "às 6 da tarde", "in half an hour", "tomorrow at 6:30 pm"...
Returns the moment and the character spans of the time expression, so the caller can
remove it and keep the rest of the sentence as the reminder's text.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from jarvis.text.numbers import parse_number

ONE = {"um", "uma", "a", "an", "one"}
NUMBER = r"[a-z0-9]+(?: (?:e|and) [a-z0-9]+)?"

HALF_HOUR = re.compile(
    r"\b(?:em|daqui a|daqui|dentro de) meia hora\b|\bin (?:half an|a half) hour\b"
)
RELATIVE = re.compile(
    rf"\b(?:em|daqui a|daqui|dentro de|in|within) (?P<amount>{NUMBER}) "
    r"(?P<unit>segundos?|minutos?|horas?|seconds?|secs?|minutes?|mins?|hours?|hrs?)"
    r"(?P<half> e meia| and a half)?\b"
)
DAY = re.compile(
    r"\b(?P<day>depois de amanha|amanha|hoje|day after tomorrow|tomorrow|today|tonight)\b"
)
CLOCK = re.compile(
    r"\b(?:as|a|ao|pelas|at|by) (?P<hour>\d{1,2}|[a-z]+)(?:h| horas?)?(?: ?(?P<minute>\d{2}))?"
    r"(?: e (?P<minute_word>meia|[a-z]+))?"
    r"(?: (?:da|de|in the) "
    r"(?P<period>manha|tarde|noite|madrugada|morning|afternoon|evening|night))?"
    r"(?: ?(?P<ampm>a\.?m|p\.?m))?\b"
)
COMPACT = re.compile(r"\b(?P<hour>\d{1,2})h(?P<minute>\d{2})?\b")  # "18h", "18h30"
NOON = re.compile(r"\b(?:(?:ao|at) )?(?:meio dia|noon)\b")
MIDNIGHT = re.compile(r"\b(?:(?:a|at) )?(?:meia noite|midnight)\b")

LATER = {"tarde", "noite", "afternoon", "evening", "night", "pm", "p.m"}
EARLIER = {"manha", "morning", "am", "a.m"}
DAY_OFFSET = {
    "hoje": 0, "today": 0, "tonight": 0,
    "amanha": 1, "tomorrow": 1,
    "depois de amanha": 2, "day after tomorrow": 2,
}  # fmt: skip
TONIGHT = time(20, 0)

Span = tuple[int, int]


@dataclass(frozen=True)
class TimeMatch:
    due_at: datetime
    spans: tuple[Span, ...]  # where the time expression is, in the normalised text


def find_time(text: str, now: datetime, default_hour: int) -> TimeMatch | None:
    """The moment described in ``text`` (normalised), or None if there is none."""
    relative = _relative(text, now)
    if relative is not None:
        return relative

    day = DAY.search(text)
    clock = _clock(text)
    if clock is None and day is None:
        return None
    spans = [match_span for match_span in (day and day.span(), clock and clock[1]) if match_span]
    offset = DAY_OFFSET[day["day"]] if day else 0
    target = now.date() + timedelta(days=offset)

    if clock is None:
        if day is not None and day["day"] == "tonight":
            wanted = TONIGHT
        elif offset > 0:
            wanted = time(default_hour, 0)
        else:
            return None  # "today" alone is not a time
        return TimeMatch(_at(target, wanted, now), tuple(spans))

    (hour, minute, period_given), _ = clock
    due = _at(target, time(hour, minute), now)
    if day is None and due <= now:
        later = (
            _at(target, time(hour + 12, minute), now) if hour < 12 and not period_given else None
        )
        # "às 6" at 2 pm means 6 pm today; otherwise the next occurrence, tomorrow.
        due = later if later is not None and later > now else due + timedelta(days=1)
    if due <= now:
        return None  # a moment in the past, e.g. "today at 8" said at noon
    return TimeMatch(due, tuple(spans))


def _relative(text: str, now: datetime) -> TimeMatch | None:
    half = HALF_HOUR.search(text)
    if half:
        return TimeMatch(now + timedelta(minutes=30), (half.span(),))
    for match in RELATIVE.finditer(text):
        amount = 1 if match["amount"] in ONE else parse_number(match["amount"])
        if amount is None or amount <= 0:
            continue
        unit = match["unit"]
        minutes = amount / 60 if unit.startswith(("seg", "sec")) else amount
        if unit.startswith(("hora", "hour", "hr")):
            minutes = amount * 60 + (30 if match["half"] else 0)
        return TimeMatch(now + timedelta(minutes=minutes), (match.span(),))
    return None


def _clock(text: str) -> tuple[tuple[int, int, bool], Span] | None:
    """((hour, minute, period given), span) of the first valid clock time."""
    for pattern, hour, minute in ((NOON, 12, 0), (MIDNIGHT, 0, 0)):
        match = pattern.search(text)
        if match:
            return (hour, minute, True), match.span()
    for match in CLOCK.finditer(text):
        parsed = _clock_parts(match)
        if parsed is not None:
            return parsed, match.span()
    for match in COMPACT.finditer(text):
        hour, minute = int(match["hour"]), int(match["minute"] or 0)
        if hour < 24 and minute < 60:
            return (hour, minute, False), match.span()
    return None


def _clock_parts(match: re.Match[str]) -> tuple[int, int, bool] | None:
    hour = parse_number(match["hour"])
    if hour is None or hour > 23:
        return None  # "a casa", "as compras": a preposition, not a time
    if match["minute"]:
        minute = int(match["minute"])
    elif match["minute_word"]:
        spoken = 30 if match["minute_word"] == "meia" else parse_number(match["minute_word"])
        minute = -1 if spoken is None else spoken
    else:
        minute = 0
    if not 0 <= minute < 60:
        return None
    period = match["period"] or match["ampm"]
    if period in LATER and hour < 12:
        hour += 12
    elif period in EARLIER and hour == 12:
        hour = 0
    return hour, minute, period is not None


def _at(day: date, moment: time, now: datetime) -> datetime:
    return datetime.combine(day, moment, tzinfo=now.tzinfo)
