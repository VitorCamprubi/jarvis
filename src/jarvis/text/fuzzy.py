"""How well a spoken name matches an app or program name (0-100)."""

from rapidfuzz import fuzz

MIN_PARTIAL_QUERY = 4  # "de" is part of half the app names in Portuguese
PARTIAL_WEIGHT = 0.9  # a partial match is good, but never as good as a full one


def name_score(query: str, name: str, **_: object) -> float:
    """Best of three comparisons of normalised text:

    - the whole name ("calculadora" vs "calculator");
    - the name's first words, as many as were said ("intellij" vs "intellij idea");
    - the query inside the name ("code" in "visual studio code"), but never the other way
      round: "photoshop" must not match "photos".
    """
    head = " ".join(name.split()[: len(query.split())])
    score = max(fuzz.ratio(query, name), fuzz.ratio(query, head))
    if len(query) >= MIN_PARTIAL_QUERY and len(query) < len(name):
        score = max(score, fuzz.partial_ratio(query, name) * PARTIAL_WEIGHT)
    return score
