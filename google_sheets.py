import os
import json
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
]

# Expected Google Sheet columns (row 1 = headers):
# Name | Language | Level | Interests | Doc ID | Chat ID


def get_sheets_service():
    token_raw = os.getenv('GOOGLE_TOKEN')
    if not token_raw:
        raise ValueError("GOOGLE_TOKEN is not set.")

    creds = Credentials.from_authorized_user_info(json.loads(token_raw), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        logger.info("Google OAuth token refreshed.")

    return build('sheets', 'v4', credentials=creds)


def get_all_students(sheet_id): -> list:
    """
    Reads all student rows from the Google Sheet.
    Returns a list of dicts like:
    [
      {
        'name': 'Anna',
        'language': 'Italian',
        'level': 'intermediate',
        'interests': 'music, travel, cooking',
        'doc_id': '1BxiMV...',
        'chat_id': '123456789',
      },
      ...
    ]
    """
    service = get_sheets_service()
    sheet_id = os.getenv('GOOGLE_SHEET_ID')
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not set.")

    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range='Sheet1!A1:F100',   # up to 100 students
    ).execute()

    rows = result.get('values', [])
    if len(rows) < 2:
        raise ValueError("Sheet is empty or has no student rows. Add a header row + at least one student.")

    headers = [h.strip().lower() for h in rows[0]]
    students = []

    for row in rows[1:]:
        # Pad short rows with empty strings
        padded = row + [''] * (len(headers) - len(row))
        student = dict(zip(headers, padded))

        # Skip empty rows
        if not student.get('name', '').strip():
            continue

        students.append({
            'name':      student.get('name', '').strip(),
            'language':  student.get('language', 'Italian').strip(),
            'level':     student.get('level', 'intermediate').strip(),
            'interests': student.get('interests', '').strip(),
            'doc_id':    student.get('doc id', '').strip(),
            'chat_id':   student.get('chat id', '').strip(),
        })

    if not students:
        raise ValueError("No valid students found in the sheet.")

    logger.info(f"Loaded {len(students)} students from sheet.")
    return students


def get_student_by_name(name: str) -> dict:
    students = get_all_students()
    for s in students:
        if s['name'].lower() == name.lower():
            return s
    raise ValueError(f"Student '{name}' not found in sheet.")
