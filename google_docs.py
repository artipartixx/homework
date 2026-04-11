import os
import re
import json
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/documents']


def get_docs_service():
    token_raw = os.getenv('GOOGLE_TOKEN')
    if not token_raw:
        raise ValueError(
            "GOOGLE_TOKEN environment variable is not set.\n"
            "Run auth.py locally, then paste the token.json contents into Railway."
        )
    token_info = json.loads(token_raw)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        logger.info("Google OAuth token refreshed.")
    return build('docs', 'v1', credentials=creds)


def _para_text(paragraph: dict) -> str:
    return ''.join(
        el['textRun']['content']
        for el in paragraph.get('elements', [])
        if 'textRun' in el
    )


def _utf16_len(s: str) -> int:
    """Google Docs API uses UTF-16 code units for indices."""
    return len(s.encode('utf-16-le')) // 2


def get_latest_lesson(doc_id: str) -> dict:
    """
    Reads the Google Doc and returns the most recent lesson's title, phrases,
    and insert_index (end of the lesson phrase block).

    Latest lesson = first heading in the doc (top of document).
    Heading format: __Lezione 39, apr 2__
    Phrase format:  frase italiana == русский перевод
    """
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    body_content = doc.get('body', {}).get('content', [])

    paragraphs = []
    for element in body_content:
        if 'paragraph' in element:
            text = _para_text(element['paragraph']).strip()
            paragraphs.append({
                'text': text,
                'start': element.get('startIndex', 0),
                'end': element.get('endIndex', 0),
            })

    lezione_re = re.compile(r'Lezione\s+\d+', re.IGNORECASE)
    heading_indices = [i for i, p in enumerate(paragraphs) if lezione_re.search(p['text'])]

    if not heading_indices:
        raise ValueError(
            "No lesson headings found in the document.\n"
            "Expected format: __Lezione 39, apr 2__"
        )

    # First heading = latest lesson (top of doc)
    first_idx = heading_indices[0]
    raw_title = paragraphs[first_idx]['text']
    title = re.sub(r'[_*#]', '', raw_title).strip()

    phrase_paras = paragraphs[first_idx + 1:]

    phrases = []
    insert_index = paragraphs[first_idx]['end']

    for para in phrase_paras:
        text = para['text'].strip()
        if not text:
            insert_index = para['end']
            continue
        if lezione_re.search(text):
            break

        if '==' in text:
            italian = text.split('==')[0].strip()
            if italian:
                phrases.append(italian)
        else:
            phrases.append(text)

        insert_index = para['end']

    if not phrases:
        raise ValueError(f"No phrases found under '{title}'.")

    logger.info(f"Loaded lesson '{title}' with {len(phrases)} phrases. Insert at {insert_index}.")
    return {
        'title': title,
        'phrases': phrases,
        'insert_index': insert_index,
    }


def append_story_to_doc(
    doc_id: str,
    result: dict,
    insert_index: int,
    image_url: str = None,
) -> None:
    """
    Inserts the generated content into the Google Doc right after the lesson phrases.

    Structure:
        ────────────────────────────────────────
        Title
        [inline image if available]

        Italian sentence
        Translation

        ...

        Esercizi
        ...
    """
    service = get_docs_service()

    title = result.get('title', 'Storia')
    chunks = result.get('chunks', [])
    exercises = result.get('exercises', {})

    # --- Build before-image text ---
    before_image = '\n\n' + ('─' * 40) + '\n\n' + title + '\n\n'

    # --- Build after-image text ---
    after_lines = []

    for chunk in chunks:
        italian = chunk.get('italian', '').strip()
        translation = chunk.get('translation', '').strip()
        if italian:
            after_lines.append(italian + '\n')
        if translation:
            after_lines.append(translation + '\n')
        after_lines.append('\n')

    fill = exercises.get('fill_in_blank', [])
    tf = exercises.get('true_false', [])
    oq = exercises.get('open_question', '')

    if fill or tf or oq:
        after_lines.append('Esercizi\n\n')
        if fill:
            after_lines.append('Completa le frasi:\n')
            for i, s in enumerate(fill, 1):
                after_lines.append(f'{i}. {s}\n')
            after_lines.append('\n')
        if tf:
            after_lines.append('Vero o falso:\n')
            for i, s in enumerate(tf, 1):
                after_lines.append(f'{i}. {s}\n')
            after_lines.append('\n')
        if oq:
            after_lines.append(f'Domanda aperta:\n{oq}\n')

    after_image = ''.join(after_lines)

    # --- Build batchUpdate requests ---
    # Requests are processed sequentially; each index is relative to doc state
    # after previous requests in the same batch.
    requests = []

    # 1. Insert text before the image
    requests.append({
        'insertText': {
            'location': {'index': insert_index},
            'text': before_image,
        }
    })

    if image_url:
        # 2. Insert inline image right after before_image text
        img_index = insert_index + _utf16_len(before_image)
        requests.append({
            'insertInlineImage': {
                'location': {'index': img_index},
                'uri': image_url,
                'objectSize': {
                    'height': {'magnitude': 300, 'unit': 'PT'},
                    'width': {'magnitude': 300, 'unit': 'PT'},
                },
            }
        })
        # 3. Insert remaining text after image (image occupies 1 index position)
        after_index = img_index + 1
    else:
        after_index = insert_index + _utf16_len(before_image)

    # Insert text after image (or after title if no image)
    requests.append({
        'insertText': {
            'location': {'index': after_index},
            'text': after_image,
        }
    })

    service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests}
    ).execute()

    logger.info(f"Content appended to doc {doc_id} at index {insert_index}.")
