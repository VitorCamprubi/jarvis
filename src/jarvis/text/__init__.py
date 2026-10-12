"""Text helpers for transcribed speech: normalisation, spoken numbers, yes/no answers."""

from jarvis.text.answers import Answer, classify_answer
from jarvis.text.fuzzy import name_score
from jarvis.text.normalize import POLITENESS, WAKE_WORDS, normalize, simplify, strip_accents
from jarvis.text.numbers import parse_number

__all__ = [
    "POLITENESS",
    "WAKE_WORDS",
    "Answer",
    "classify_answer",
    "name_score",
    "normalize",
    "parse_number",
    "simplify",
    "strip_accents",
]
