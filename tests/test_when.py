from datetime import date, datetime, time, timedelta, timezone

import pytest

from jarvis.text import normalize
from jarvis.text.when import find_time

BRT = timezone(timedelta(hours=-3))
NOW = datetime(2026, 10, 12, 14, 0, tzinfo=BRT)  # a Monday, 2 pm
TODAY = NOW.date()
TOMORROW = TODAY + timedelta(days=1)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=BRT)


def due(spoken: str) -> datetime | None:
    match = find_time(normalize(spoken), NOW, default_hour=9)
    return None if match is None else match.due_at


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        # relative
        ("me lembra em 20 minutos de tirar a pizza", NOW + timedelta(minutes=20)),
        ("daqui a vinte minutos", NOW + timedelta(minutes=20)),
        ("daqui a meia hora", NOW + timedelta(minutes=30)),
        ("em uma hora", NOW + timedelta(hours=1)),
        ("dentro de 2 horas e meia", NOW + timedelta(hours=2, minutes=30)),
        ("in 20 minutes", NOW + timedelta(minutes=20)),
        ("in half an hour", NOW + timedelta(minutes=30)),
        ("in an hour", NOW + timedelta(hours=1)),
        # clock times today
        ("às 18h", at(TODAY, 18)),
        ("às 18h30", at(TODAY, 18, 30)),
        ("às 18:30", at(TODAY, 18, 30)),
        ("às 6 da tarde", at(TODAY, 18)),
        ("às seis e meia da tarde", at(TODAY, 18, 30)),
        ("at 6 pm", at(TODAY, 18)),
        ("at 6:30 p.m.", at(TODAY, 18, 30)),
        ("ao meio-dia", at(TOMORROW, 12)),  # noon has passed: tomorrow
        ("à meia-noite", at(TOMORROW, 0)),
        # an ambiguous hour that already passed this morning means this evening
        ("às 6", at(TODAY, 18)),
        # a time that passed even in the evening reading is tomorrow
        ("às 13h", at(TOMORROW, 13)),
        # days
        ("amanhã às 9", at(TOMORROW, 9)),
        ("amanhã às 9 da manhã", at(TOMORROW, 9)),
        ("tomorrow at 9", at(TOMORROW, 9)),
        ("amanhã", at(TOMORROW, 9)),  # default hour
        ("depois de amanhã às 10h", at(TODAY + timedelta(days=2), 10)),
        ("tonight", at(TODAY, 20)),
    ],
)
def test_find_time(spoken: str, expected: datetime) -> None:
    assert due(spoken) == expected


@pytest.mark.parametrize(
    "spoken",
    [
        "me lembra de comprar pão",  # no time at all
        "hoje",  # a day is not a time
        "hoje às 8",  # already past
        "vou a casa",  # "a casa" is not a clock time
        "em banana minutos",
    ],
)
def test_no_time(spoken: str) -> None:
    assert due(spoken) is None


def test_spans_cover_the_time_expression() -> None:
    text = normalize("me lembra de ligar pra mãe amanhã às 9")
    match = find_time(text, NOW, default_hour=9)

    assert match is not None
    covered = sorted(text[start:end] for start, end in match.spans)
    assert covered == ["amanha", "as 9"]
