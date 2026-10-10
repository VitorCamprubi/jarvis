"""Spoken numbers in Portuguese and English: "30", "30%", "trinta e cinco", "thirty-five"."""

import re

WORDS = {
    # Portuguese
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
    "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15, "dezesseis": 16,
    "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30,
    "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
    "noventa": 90, "cem": 100, "cento": 100,
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
HUNDRED = "hundred"
# "cento" is a number ("cento e vinte"), except in "por cento": drop the phrase first.
PERCENT = re.compile(r"%|\bpor cento\b|\bper ?cent\b")
# Words that may surround a number without changing it.
FILLERS = {"e", "and", "a"}


def parse_number(text: str) -> int | None:
    """The whole number said in ``text``, or None if it holds anything else."""
    tokens = PERCENT.sub(" ", text.lower()).replace("-", " ").split()
    if len(tokens) == 1 and tokens[0].isdigit():
        return int(tokens[0])
    total = 0
    found = False
    for token in tokens:
        if token in WORDS:
            total += WORDS[token]
            found = True
        elif token == HUNDRED:
            total = max(total, 1) * 100  # "a hundred", "one hundred"
            found = True
        elif token not in FILLERS:
            return None
    return total if found else None
