"""Upload Short via YouTube Data API v3 — metadata from SEO JSON only. OAuth, never password."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config_loader import load_config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
ROOT = Path(__file__).resolve().parent.parent


def _cred_paths(cfg: dict) -> tuple[Path, Path]:
    upload = cfg.get("upload") or {}
    cred_dir = ROOT / (upload.get("credentials_dir") or "credentials")
    return cred_dir / "client_secret.json", cred_dir / "youtube_token.json"


def print_setup_help(client_secret: Path) -> None:
    print("ERROR: OAuth client secret missing.")
    print(f"Expected: {client_secret}")
    print("1) Google Cloud Console -> APIs -> enable YouTube Data API v3")
    print("2) Credentials -> Create OAuth client ID -> Desktop app")
    print("3) Download JSON -> save as credentials/client_secret.json")
    print("4) Consent screen Test users: efsaneshorts@gmail.com")
    print(r"5) Run: .\.venv312\Scripts\python.exe src\youtube_auth.py")


def get_credentials(cfg: dict | None = None):
    cfg = cfg or load_config()
    client_secret, token_path = _cred_paths(cfg)
    if not client_secret.exists():
        print_setup_help(client_secret)
        raise SystemExit(1)
    if not token_path.exists():
        print(f"No token at {token_path}")
        print(r"Run first: .\.venv312\Scripts\python.exe src\youtube_auth.py")
        raise SystemExit(1)
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        print("Token invalid. Re-run youtube_auth.py")
        raise SystemExit(1)
    return creds


def ensure_shorts_in_description(description: str) -> str:
    if "#Shorts" in description or "#shorts" in description.lower():
        return description
    return description.rstrip() + "\n\n#Shorts"


def load_seo_metadata(seo_path: Path) -> tuple[str, str, list[str]]:
    data = json.loads(seo_path.read_text(encoding="utf-8"))
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
    if not title or not description or len(tags) < 3:
        raise SystemExit(f"SEO incomplete (need title, description, tags): {seo_path}")
    description = ensure_shorts_in_description(description)
    return title, description, tags


def upload_short(
    video_path: str | Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "public",
    category_id: str = "27",
    cfg: dict | None = None,
) -> str:
    cfg = cfg or load_config()
    upload_cfg = cfg.get("upload") or {}
    privacy = privacy or upload_cfg.get("privacy") or "public"
    category_id = str(category_id or upload_cfg.get("category_id") or "27")
    video_path = Path(video_path)
    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")
    title = (title or "").strip()
    description = ensure_shorts_in_description((description or "").strip())
    tags = [t for t in (tags or []) if t]
    if not title or not description or len(tags) < 3:
        raise SystemExit("Refuse upload: empty/generic metadata (title/description/tags required)")

    creds = get_credentials(cfg)
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/*", resumable=True)
    print(f"[upload] {video_path.name} -> privacy={privacy} category={category_id}")
    print(f"[upload] title: {title}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[upload] {int(status.progress() * 100)}%")
    video_id = response["id"]
    print(f"[upload] OK https://youtu.be/{video_id}")
    return video_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Short using SEO JSON metadata")
    parser.add_argument("--video", required=True, help="Path to mp4")
    parser.add_argument("--seo", required=True, help="Path to seo/{stem}.seo.json")
    parser.add_argument("--privacy", default=None, help="public|private|unlisted")
    args = parser.parse_args()
    cfg = load_config()
    title, description, tags = load_seo_metadata(Path(args.seo))
    privacy = args.privacy or (cfg.get("upload") or {}).get("privacy") or "public"
    upload_short(
        args.video,
        title=title,
        description=description,
        tags=tags,
        privacy=privacy,
        cfg=cfg,
    )


if __name__ == "__main__":
    main()
