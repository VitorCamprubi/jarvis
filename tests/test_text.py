import pytest

from jarvis.text import (
    Answer,
    after_wake_word,
    classify_answer,
    mentions_wake_word,
    name_score,
    normalize,
    parse_number,
)

THRESHOLD = 85  # apps.match_threshold in config/default.toml


@pytest.mark.parametrize(
    ("spoken", "name"),
    [
        ("spotify", "spotify"),
        ("calculadora", "calculator"),
        ("intelij", "intellij idea"),
        ("code", "visual studio code"),
        ("edge", "microsoft edge"),
        ("whats", "whatsapp"),
    ],
)
def test_name_score_accepts_close_names(spoken: str, name: str) -> None:
    assert name_score(spoken, name) >= THRESHOLD


@pytest.mark.parametrize(
    ("spoken", "name"),
    [
        # Real false positives found on the owner's PC with the previous scorer:
        ("photoshop", "photos"),
        ("bloco de notas", "conexao de area de trabalho remota"),
        ("de", "conexao de area de trabalho remota"),
        ("chrome", "microsoft edge"),
    ],
)
def test_name_score_rejects_other_names(spoken: str, name: str) -> None:
    assert name_score(spoken, name) < THRESHOLD


@pytest.mark.parametrize(
    ("spoken", "normalized"),
    [
        ("Jarvis, abre o Spotify, por favor!", "abre o spotify"),
        ("Hey Jarvis, open YouTube.", "open youtube"),
        ("Qual é o volume?", "qual e o volume"),
        ("Volume em 30%.", "volume em 30%"),
        ("Acessa youtube.com", "acessa youtube.com"),
        ("What's the volume, please?", "whats the volume"),
        ("Thirty-five", "thirty five"),
        ("jarvis", ""),
        ("Jarvisson", "jarvisson"),
    ],
)
def test_normalize(spoken: str, normalized: str) -> None:
    assert normalize(spoken) == normalized


@pytest.mark.parametrize(
    ("spoken", "number"),
    [
        ("30", 30),
        ("30%", 30),
        ("trinta", 30),
        ("trinta e cinco", 35),
        ("trinta e cinco por cento", 35),
        ("cem", 100),
        ("thirty five", 35),
        ("thirty-five percent", 35),
        ("a hundred", 100),
        ("one hundred", 100),
        ("zero", 0),
        ("dez", 10),
    ],
)
def test_parse_number(spoken: str, number: int) -> None:
    assert parse_number(spoken) == number


@pytest.mark.parametrize("spoken", ["", "alto", "trinta laranjas", "por cento"])
def test_parse_number_rejects_other_words(spoken: str) -> None:
    assert parse_number(spoken) is None


@pytest.mark.parametrize(
    ("spoken", "answer"),
    [
        ("Sim.", Answer.YES),
        ("Pode, sim.", Answer.YES),
        ("Yes, go ahead.", Answer.YES),
        ("Sure.", Answer.YES),
        ("Não.", Answer.NO),
        ("Não, pode esperar.", Answer.NO),  # "não" wins over "pode"
        ("No, don't.", Answer.NO),
        ("Cancela.", Answer.NO),
        ("Hmm, talvez.", Answer.UNCLEAR),
        ("", Answer.UNCLEAR),
    ],
)
def test_classify_answer(spoken: str, answer: Answer) -> None:
    assert classify_answer(spoken) is answer


@pytest.mark.parametrize(
    ("heard", "wanted"),
    [
        ("Ei Jarvis, abre o Spotify.", "abre o Spotify."),
        ("Rei Jarvis, abre o Spotify.", "abre o Spotify."),  # Whisper's spelling of "Hey"
        ("Hey Jarvis, what's the weather like?", "what's the weather like?"),
        ("...amanhã. Ei Jarvis, que horas são?", "que horas são?"),  # said before the wake
        ("Ei Jarvis.", ""),
        ("Abre o Spotify.", "Abre o Spotify."),  # no name: kept whole
    ],
)
def test_the_request_after_the_wake_word(heard: str, wanted: str) -> None:
    assert after_wake_word(heard) == wanted


@pytest.mark.parametrize(
    ("heard", "mentions"),
    [
        ("Ei, Jarvis, como está o tempo?", True),
        ("Rei Jarvis, abre o Spotify.", True),
        ("Ei Jair, vamos jantar às oito?", False),
        ("Harvey, did you finish the report?", False),
        ("The jars of jam are on the shelf.", False),
    ],
)
def test_wake_word_confirmation(heard: str, mentions: bool) -> None:
    assert mentions_wake_word(heard) is mentions
