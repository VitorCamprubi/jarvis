"""Yes/no answers to "Shall I proceed, sir?", in both languages (ADR-025)."""

from enum import StrEnum

from jarvis.text.normalize import normalize

YES = (
    "sim", "pode", "claro", "confirmo", "confirma", "isso", "positivo", "manda ver",
    "com certeza", "prossiga", "faca", "yes", "yeah", "yep", "yup", "sure", "go ahead",
    "do it", "proceed", "confirm", "confirmed", "affirmative", "of course", "ok", "okay",
)  # fmt: skip
NO = (
    "nao", "cancela", "cancele", "cancelar", "negativo", "espera", "deixa pra la", "no",
    "nope", "cancel", "dont", "do not", "abort", "wait", "negative", "never mind",
)  # fmt: skip


class Answer(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


def classify_answer(text: str) -> Answer:
    """A "no" anywhere wins over a "yes", so "não, pode esperar" never confirms."""
    padded = f" {normalize(text)} "
    if any(f" {word} " in padded for word in NO):
        return Answer.NO
    if any(f" {word} " in padded for word in YES):
        return Answer.YES
    return Answer.UNCLEAR
