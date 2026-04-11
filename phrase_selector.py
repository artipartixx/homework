import re

# Only strip actual teaching annotations — not real vocabulary
METALINGUISTIC_PATTERNS = [
    r'->',
    r'=>',
    r'\bsignifica\b',
    r'\bcome si dice\b',
    r'\bcioe\b',
    r'\bovvero\b',
    r'\bin altre parole\b',
    r'\besempio:',
    r'\bes\.',
    r'\bcome\b.*\bsi usa\b',
]


def clean_phrases(phrases):
    """
    Remove only metalinguistic teaching annotations.
    Single words and short phrases are kept — Claude will judge relevance.
    Returns a flat list of clean phrase strings.
    """
    cleaned = []
    for p in phrases:
        text = p.strip()
        if not text:
            continue
        lower = text.lower()
        if any(re.search(pat, lower) for pat in METALINGUISTIC_PATTERNS):
            continue
        cleaned.append(text)
    return cleaned
