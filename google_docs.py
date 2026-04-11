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


def get_latest_lesson(doc_id: str) -> dict:
    """
    Reads the Google Doc and returns the most recent lesson's title, phrases,
    and the insert_index (end of the lesson's phrase block) for appending content.

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

    # Collect phrase paragraphs after this heading
    phrase_paras = paragraphs[first_idx + 1:]

    phrases = []
    insert_index = paragraphs[first_idx]['end']  # fallback: right after heading

    for para in phrase_paras:
        text = para['text'].strip()
        if not text:
            insert_index = para['end']
            continue
        if lezione_re.search(text):
            break  # hit the next lesson — stop

        if '==' in text:
            italian = text.split('==')[0].strip()
            if italian:
                phrases.append(italian)
        else:
            phrases.append(text)

        insert_index = para['end']  # keep advancing to end of last phrase

    if not phrases:
        raise ValueError(f"No phrases found under '{title}'.")

    logger.info(f"Loaded lesson '{title}' with {len(phrases)} phrases. Insert at index {insert_index}.")
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
    Inserts the generated story/dialogue/article into the Google Doc
    right after the lesson's phrase block.

    Format in the doc:
        ─────────────────
        Title

        Italian sentence(s)
        Translation

        Italian sentence(s)
        Translation
        ...

        Esercizi
        ...
    """
    service = get_docs_service()

    title = result.get('title', 'Storia')
    chunks = result.get('chunks', [])
    exercises = result.get('exercises', {})

    lines = [
        '\n\n' + ('─' * 40) + '\n\n',
        f'{title}\n\n',
    ]

    if image_url:
        lines.append(f'[Immagine: {image_url}]\n\n')

    for chunk in chunks:
        italian = chunk.get('italian', '').strip()
        translation = chunk.get('translation', '').strip()
        if italian:
            lines.append(f'{italian}\n')
        if translation:
            lines.append(f'{translation}\n')
        lines.append('\n')

    # Exercises
    fill = exercises.get('fill_in_blank', [])
    tf = exercises.get('true_false', [])
    oq = exercises.get('open_question', '')

    if fill or tf or oq:
        lines.append('Esercizi\n\n')
        if fill:
            lines.append('Completa le frasi:\n')
            for i, s in enumerate(fill, 1):
                lines.append(f'{i}. {s}\n')
            lines.append('\n')
        if tf:
            lines.append('Vero o falso:\n')
            for i, s in enumerate(tf, 1):
                lines.append(f'{i}. {s}\n')
            lines.append('\n')
        if oq:
            lines.append(f'Domanda aperta:\n{oq}\n')

    block = ''.join(lines)

    service.documents().batchUpdate(
        documentId=doc_id,
        body={
            'requests': [
                {
                    'insertText': {
                        'location': {'index': insert_index},
                        'text': block,
                    }
                }
            ]
        }
    ).execute()

    logger.info(f"Content appended to doc {doc_id} at index {insert_index}.")
