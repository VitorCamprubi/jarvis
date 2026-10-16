"""Cutting a reply into chunks that are synthesised one after another (ADR-042).

The first chunk is short, so the voice starts quickly; the next ones are longer, since each
is synthesised while the previous one plays.
"""

import re

# Words whose final dot does not end a sentence ("Sr. Camprubi", "Dr. House").
ABBREVIATIONS = {"sr", "sra", "srta", "dr", "dra", "mr", "mrs", "ms", "prof", "st", "vs", "etc"}
FIRST_MIN_CHARS = 40  # a shorter first sentence ("Bom dia, senhor.") takes the next one along
CHUNK_MAX_CHARS = 240

_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str) -> list[str]:
    merged: list[str] = []
    for part in _BOUNDARY.split(text.strip()):
        if merged and _not_an_end(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        elif part:
            merged.append(part)
    return merged


def _not_an_end(sentence: str) -> bool:
    last = sentence.rsplit(" ", 1)[-1].rstrip(".").lower()
    return last in ABBREVIATIONS or "." in last  # an acronym: "J.A.R.V.I.S."


def speech_chunks(text: str) -> list[str]:
    parts = sentences(text)
    if not parts:
        return []
    first, rest = parts[0], parts[1:]
    while len(first) < FIRST_MIN_CHARS and rest:
        first = f"{first} {rest.pop(0)}"
    chunks = [first]
    current = ""
    for part in rest:
        if current and len(current) + 1 + len(part) > CHUNK_MAX_CHARS:
            chunks.append(current)
            current = part
        else:
            current = f"{current} {part}" if current else part
    if current:
        chunks.append(current)
    return chunks
