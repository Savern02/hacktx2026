"""Name normalization shared by the resolver, upsert, and validator."""

import re
import unicodedata

# Census legal suffixes on place names (LSAD), longest first so
# "metropolitan government (balance)" wins over "government".
_PLACE_SUFFIXES = sorted(
    [
        "city",
        "town",
        "village",
        "borough",
        "CDP",
        "municipality",
        "comunidad",
        "zona urbana",
        "plantation",
        "corporation",
        "urban county",
        "city and borough",
        "consolidated government",
        "consolidated government (balance)",
        "metro government",
        "metro government (balance)",
        "metropolitan government",
        "metropolitan government (balance)",
        "unified government",
        "unified government (balance)",
        "city (balance)",
        "town (balance)",
    ],
    key=len,
    reverse=True,
)
_SUFFIX_RE = re.compile(
    r"\s+(" + "|".join(re.escape(s) for s in _PLACE_SUFFIXES) + r")$", re.IGNORECASE
)


def normalize_name(name: str) -> str:
    """Spec Section 9: lowercase, NFKC, & -> and, strip punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKC", name).lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = s.replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def strip_place_suffix(name: str) -> str:
    """'Austin city' -> 'Austin'; 'Nashville-Davidson metropolitan government (balance)' -> 'Nashville-Davidson'."""
    return _SUFFIX_RE.sub("", name.strip())


def place_display_name(name: str, state_code: str) -> str:
    return f"{strip_place_suffix(name)}, {state_code}"


def normalize_city(name: str) -> str:
    """For USPS city name -> place matching: drop suffix, treat ST and SAINT as equal."""
    s = normalize_name(strip_place_suffix(name))
    s = re.sub(r"\bst\b", "saint", s)
    s = re.sub(r"\bste\b", "sainte", s)
    s = re.sub(r"\bft\b", "fort", s)
    s = re.sub(r"\bmt\b", "mount", s)
    return s
