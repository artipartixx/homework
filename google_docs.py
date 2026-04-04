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
        raise ValueError("GOOGLE_TOKEN environment variable is not set.")
 
    creds = Credentials.from_authorized_user_info(json.loads(token_raw), SCOPES)
 
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
    service = get_docs_service()
    doc = service.documents().get(documentId=doc_id).execute()
    body_content = doc.get('body', {}).get('content', [])
 
    paragraphs = []
    for element in body_content:
        if 'paragraph' in element:
            text = _para_text(element['paragraph']).strip()
            if text:
                paragraphs.append({'text': text})
 
    lezione_re = re.compile(r'Lezione\s+\d+', re.IGNORECASE)
    heading_indices = [i for i, p in enumerate(paragraphs) if lezione_re.search(p['text'])]
 
    if not heading_indices:
        raise ValueError("No lesson headings found. Expected format: __Lezione 39, apr 2__")
 
    # First heading = most recent lesson (newest at top of doc)
    first_idx = heading_indices[0]
    title = re.sub(r'[_*#]', '', paragraphs[first_idx]['text']).strip()
 
    # Collect phrases until the next heading
    phrases = []
    for para in paragraphs[first_idx + 1:]:
        text = para['text'].strip()
        if not text:
            continue
        if lezione_re.search(text):
            break
        if '==' in text:
            italian = text.split('==')[0].strip()
            if italian:
                phrases.append(italian)
        else:
            phrases.append(text)
 
    if not phrases:
        raise ValueError(f"No phrases found under '{title}'.")
 
    logger.info(f"Loaded '{title}' — {len(phrases)} phrases.")
    return {'title': title, 'phrases': phrases}
 
 
def _utf16_len(s: str) -> int:
    """Return the number of UTF-16 code units in a string (what Google Docs uses for indices)."""
    return len(s.encode('utf-16-le')) // 2
 
 
def append_story_to_doc(
    doc_id: str,
    lesson_title: str,
    story: str,
    translation: str,
    exercises: list,
    image_url: str = None,
) -> None:
    service = get_docs_service()
 
    # Get current end of document
    doc = service.documents().get(documentId=doc_id).execute()
    end_index = doc['body']['content'][-1]['endIndex'] - 1
 
    ex_lines = ''.join(f'{i}. {ex}\n' for i, ex in enumerate(exercises, 1))
 
    before_image = (
        '\n\n' + ('─' * 35) + '\n\n'
        f'📖 Storia — {lesson_title}\n\n'
    )
    after_image = (
        f'\n\n{story}\n\n'
        f'🇷🇺 Traduzione\n\n'
        f'{translation}\n\n'
        f'📝 Esercizi\n\n'
        f'{ex_lines}'
    )
 
    if image_url:
        before_len = _utf16_len(before_image)
        requests = [
            {
                'insertText': {
                    'location': {'index': end_index},
                    'text': before_image,
                }
            },
            {
                'insertInlineImage': {
                    'location': {'index': end_index + before_len},
                    'uri': image_url,
                    'objectSize': {
                        'height': {'magnitude': 300, 'unit': 'PT'},
                        'width':  {'magnitude': 300, 'unit': 'PT'},
                    },
                }
            },
            {
                'insertText': {
                    'location': {'index': end_index + before_len + 1},
                    'text': after_image,
                }
            },
        ]
    else:
        requests = [
            {
                'insertText': {
                    'location': {'index': end_index},
                    'text': before_image + after_image,
                }
            }
        ]
 
    service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests}
    ).execute()
 
    logger.info(f"Story appended to doc {doc_id}.")
 
