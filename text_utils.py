"""
text_utils.py — Shared text handling for GrowGPT.

Two jobs, both of which used to be done wrong in several places at once:

  * Language codes. brain.py, quests.py and prices.py all indexed dicts with
    `[lang]` straight from the request body. Anything other than "fr" or "en"
    — "EN", "fr-FR", "es", or a missing value — raised a KeyError and turned
    into a 500. normalize_lang() makes that impossible.

  * Word matching. Keyword lookup was an exact string match, so "planter"
    was understood but "plantes" was not, and any accent or typo missed.
    Normalising the player's words *and* the keyword lists through the same
    function fixes that without a heavier NLP dependency.
"""
import re
import unicodedata

SUPPORTED_LANGS = ("fr", "en")
DEFAULT_LANG = "fr"


def normalize_lang(lang) -> str:
    """
    Coerce anything a client might send into a language we actually have
    strings for. Never raises — an unknown language falls back to French.
    """
    if not isinstance(lang, str):
        return DEFAULT_LANG
    code = lang.strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_token(word: str) -> str:
    """
    Fold a single word to its comparison form: no accents, no case, no plural.

    The trailing -s/-x strip is crude and will mangle words like "prix" into
    "pri". That is harmless *as long as the keyword lists go through this same
    function*, because both sides end up mangled identically and still match.
    Never use this to produce text shown to a player.
    """
    w = strip_accents(word.lower())
    if len(w) > 3 and w[-1] in ("s", "x"):
        w = w[:-1]
    return w


def tokenize(message: str) -> list:
    """Normalised words plus bigrams, which is what intent scoring matches on."""
    cleaned = re.sub(r"[^\w\s]", " ", strip_accents(message.lower()))
    words = [normalize_token(w) for w in cleaned.split() if w]
    bigrams = [words[i] + " " + words[i + 1] for i in range(len(words) - 1)]
    return words + bigrams


def normalize_phrase(phrase: str) -> str:
    """Normalise a keyword, which may be several words long, the same way."""
    return " ".join(normalize_token(w) for w in strip_accents(phrase.lower()).split())


def close_enough(a: str, b: str, max_distance: int = 1) -> bool:
    """
    Bounded edit distance, used only as a last resort when no intent scored at
    all. Short words are excluded because at length 4 a single edit turns one
    real word into a different real word far too often.
    """
    if len(a) < 5 or len(b) < 5:
        return False
    if abs(len(a) - len(b)) > max_distance:
        return False

    # Classic DP, but we stop as soon as the whole row exceeds the budget.
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            ))
        if min(current) > max_distance:
            return False
        previous = current
    return previous[-1] <= max_distance
