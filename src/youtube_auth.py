"""One-time YouTube OAuth (desktop). Sign in as efsaneshorts@gmail.com."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
ROOT = Path(__file__).resolve().parent.parent
CRED_DIR = ROOT / "credentials"
CLIENT_SECRET = CRED_DIR / "client_secret.json"
TOKEN_PATH = CRED_DIR / "youtube_token.json"
ACCOUNT = "efsaneshorts@gmail.com"


def main() -> None:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    if not CLIENT_SECRET.exists():
        print("MISSING:", CLIENT_SECRET)
        print("Put Google OAuth Desktop client JSON there, then re-run:")
        print(r'  .\.venv312\Scripts\python.exe src\youtube_auth.py')
        print(f"Sign in as: {ACCOUNT}")
        sys.exit(1)

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.valid:
        print(f"Already authorized. Token: {TOKEN_PATH}")
        print(f"Account to use for uploads: {ACCOUNT}")
        return
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        print(f"Opening browser — sign in as {ACCOUNT} (Test user on consent screen).")
        print("Do NOT open YouTube Shorts; only complete Google consent.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved token -> {TOKEN_PATH}")
    print("OAuth OK. You can close the browser tab.")


if __name__ == "__main__":
    main()
