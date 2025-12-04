# google_auth.py
from __future__ import annotations

import os.path
from typing import Iterable

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Calendar read/write scope
SCOPES: Iterable[str] = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    """
    Return an authenticated Google Calendar v3 service.
    On first run, opens a browser window for OAuth and stores 'token.json'.
    """
    creds: Credentials | None = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Uses 'credentials.json' downloaded from Google Cloud Console
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the credentials for future runs
        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    return service
