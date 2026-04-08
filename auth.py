"""
Run this script ONCE on your local machine to authenticate with Google.
It opens a browser, you log in, then it prints your token to paste into Railway.

Usage:
    pip3 install google-auth-oauthlib google-api-python-client
    python3 auth.py
"""

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Both Docs and Sheets scopes
SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
]

TOKEN_FILE = 'token.json'
CREDS_FILE = 'oauth_credentials.json'


def main():
    if not os.path.exists(CREDS_FILE):
        print(f"\nERROR: '{CREDS_FILE}' not found.")
        print("Download it from Google Cloud Console:")
        print("  APIs & Services -> Credentials -> your OAuth client -> Download JSON")
        print(f"  Rename it to '{CREDS_FILE}' and put it in this folder.\n")
        return

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())

    print("\nAuthentication successful!")
    print("\nCopy everything between the lines and paste it as GOOGLE_TOKEN in Railway:\n")
    print("-" * 60)
    with open(TOKEN_FILE) as f:
        print(f.read())
    print("-" * 60)
    print("\nDone. You only need to run this once.\n")


if __name__ == '__main__':
    main()
