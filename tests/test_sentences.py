import pytest

from jarvis.text.sentences import CHUNK_MAX_CHARS, sentences, speech_chunks


def test_sentences_end_at_punctuation_but_not_after_titles_or_acronyms() -> None:
    text = "Bom dia, Sr. Camprubi. J.A.R.V.I.S. a postos! Tudo bem? Sim."

    assert sentences(text) == [
        "Bom dia, Sr. Camprubi.",
        "J.A.R.V.I.S. a postos!",
        "Tudo bem?",
        "Sim.",
    ]


def test_numbers_with_dots_stay_whole() -> None:
    assert sentences("O dólar subiu 0.68 por cento hoje. Fechou em alta.") == [
        "O dólar subiu 0.68 por cento hoje.",
        "Fechou em alta.",
    ]


def test_a_short_reply_is_one_chunk() -> None:
    assert speech_chunks("Bom dia, senhor. Todos os sistemas estão online.") == [
        "Bom dia, senhor. Todos os sistemas estão online."
    ]


def test_long_replies_start_short_and_then_group_sentences() -> None:
    text = "Primeira frase bem curta, mas não curtíssima. " + "Mais uma frase do boletim. " * 20

    chunks = speech_chunks(text)

    assert chunks[0] == "Primeira frase bem curta, mas não curtíssima."
    assert len(chunks) > 2
    assert all(len(chunk) <= CHUNK_MAX_CHARS for chunk in chunks[1:])
    assert " ".join(chunks) == text.strip()


@pytest.mark.parametrize("text", ["", "   "])
def test_nothing_to_say(text: str) -> None:
    assert speech_chunks(text) == []
