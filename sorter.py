import os
import json
import re
import logging
import anthropic

logger = logging.getLogger(__name__)

CATEGORIES = ['verb', 'noun', 'adjective', 'phrase', 'other']

# RGB colors for each category (Google Docs API uses 0-1 float scale)
CATEGORY_COLORS = {
    'verb':      {'red': 0.0,  'green': 0.6, 'blue': 0.0},   # green
    'noun':      {'red': 0.0,  'green': 0.3, 'blue': 0.9},   # blue
    'adjective': {'red': 0.9,  'green': 0.0, 'blue': 0.0},   # red
    'phrase':    {'red': 0.6,  'green': 0.0, 'blue': 0.8},   # purple
    'other':     {'red': 0.8,  'green': 0.7, 'blue': 0.0},   # yellow
}


def _get_text(response):
    parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            parts.append(block.text)
    return ''.join(parts).strip()


def _strip_fences(raw: str) -> str:
    raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$', '', raw.strip())
    return raw.strip()


def _extract_json(raw: str):
    """Find and parse the first JSON array in the response, even if there's preamble."""
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(raw)  # last resort, will raise if truly malformed


# ---------------------------------------------------------------------------
# Step 1 — Ask Claude to classify and generate examples
# ---------------------------------------------------------------------------

def classify_vocab(phrases: list, level: str = 'B1', native_language: str = 'Russian') -> list:
    """
    Sends the lesson vocab to Claude.
    Returns a list of dicts:
    [
      {
        "word": "andare",
        "category": "verb",
        "examples": ["sentence 1", "sentence 2", "sentence 3"]
      },
      ...
    ]
    """
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    word_list = '\n'.join(f'- {p}' for p in phrases)

    prompt = f"""You are an Italian language teacher. Classify each item in this vocabulary list and write 3 example sentences for each.

VOCABULARY LIST:
{word_list}

STUDENT LEVEL: {level}
NATIVE LANGUAGE: {native_language}

CATEGORIES (pick exactly one per item):
- verb: any verb or verbal expression
- noun: any noun or noun phrase
- adjective: any adjective or descriptive expression
- phrase: multi-word expressions, idioms, full phrases
- other: adverbs, conjunctions, prepositions, interjections, anything that doesn't fit above

RULES:
- Examples must be in Italian, appropriate for {level} level
- Examples should be natural, everyday sentences
- Each example max 10 words
- Do NOT translate — Italian only in examples

Return ONLY a valid JSON array, no explanation, no markdown, no code fences:
[
  {{
    "word": "the word or phrase exactly as given",
    "category": "verb|noun|adjective|phrase|other",
    "examples": [
      "example sentence 1",
      "example sentence 2",
      "example sentence 3"
    ]
  }}
]"""

    response = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=4096,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = _strip_fences(_get_text(response))

    try:
        result = _extract_json(raw)
        logger.info(f"Classified {len(result)} vocab items.")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse Claude vocab response: {e}")
        raise


# ---------------------------------------------------------------------------
# Step 2 — Write classified vocab into Google Doc with color formatting
# ---------------------------------------------------------------------------

def insert_vocab_to_doc(doc_id: str, vocab: list, insert_index: int) -> None:
    """
    Inserts color-coded vocab into the Google Doc at insert_index.

    Format per word:
        WORD  (colored by category)
        1. Example sentence
        2. Example sentence
        3. Example sentence
        (blank line)
    """
    from google_docs import get_docs_service

    service = get_docs_service()

    # We build a list of (text, color) tuples to insert
    # then convert to batchUpdate requests
    segments = []

    # Header
    segments.append(('\n\nVocabolario\n\n', None))

    # Group by category for a cleaner layout
    from collections import defaultdict
    by_category = defaultdict(list)
    for item in vocab:
        cat = item.get('category', 'other').lower()
        if cat not in CATEGORY_COLORS:
            cat = 'other'
        by_category[cat].append(item)

    category_order = ['verb', 'noun', 'adjective', 'phrase', 'other']
    category_labels = {
        'verb': 'Verbi',
        'noun': 'Sostantivi',
        'adjective': 'Aggettivi',
        'phrase': 'Frasi ed espressioni',
        'other': 'Altro',
    }

    for cat in category_order:
        items = by_category.get(cat, [])
        if not items:
            continue

        # Category header (no color — plain bold handled separately)
        segments.append((f'{category_labels[cat]}\n', None))

        for item in items:
            word = item.get('word', '')
            examples = item.get('examples', [])
            color = CATEGORY_COLORS[cat]

            # Word in its category color
            segments.append((word + '\n', color))

            # Examples in plain black
            for i, ex in enumerate(examples[:3], 1):
                segments.append((f'{i}. {ex}\n', None))

            segments.append(('\n', None))

    # --- Build batchUpdate requests ---
    # Strategy: insert all text first as one block,
    # then apply color formatting with updateTextStyle requests.

    # First pass: build full text and track character positions for coloring
    full_text = ''
    colored_ranges = []  # list of (start_offset, end_offset, color)

    current_offset = 0
    for text, color in segments:
        start = current_offset
        end = start + len(text.encode('utf-16-le')) // 2  # UTF-16 length
        if color:
            colored_ranges.append((start, end, color))
        full_text += text
        current_offset = end

    # Request 1: insert all text at once
    requests = [
        {
            'insertText': {
                'location': {'index': insert_index},
                'text': full_text,
            }
        }
    ]

    # Requests 2+: color each colored segment
    for start_offset, end_offset, color in colored_ranges:
        requests.append({
            'updateTextStyle': {
                'range': {
                    'startIndex': insert_index + start_offset,
                    'endIndex': insert_index + end_offset,
                },
                'textStyle': {
                    'foregroundColor': {
                        'color': {
                            'rgbColor': color
                        }
                    },
                    'bold': True,
                },
                'fields': 'foregroundColor,bold',
            }
        })

    service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests}
    ).execute()

    logger.info(f"Vocab inserted to doc {doc_id} with color formatting.")
