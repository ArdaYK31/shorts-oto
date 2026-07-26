"""Upload Short via YouTube Data API v3 — metadata from SEO JSON only. OAuth, never password."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config_loader import load_config
from seo_pack import ensure_shorts_description, ensure_shorts_title

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
        # CI mounts credentials :ro — persist is best-effort; in-memory creds still upload.
        try:
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except OSError as exc:
            print(
                f"[youtube] token refreshed in memory; could not write {token_path} ({exc})"
            )
    if not creds.valid:
        print("Token invalid. Re-run youtube_auth.py")
        raise SystemExit(1)
    return creds


def soft_max_duration_sec(cfg: dict | None = None) -> float:
    cfg = cfg or load_config()
    gates = cfg.get("quality_gates") or {}
    project = cfg.get("project") or {}
    return float(
        gates.get("max_duration_sec")
        or project.get("max_duration_sec")
        or 60
    )


def probe_video_meta(video_path: Path) -> dict[str, float | int | None]:
    """Return width/height/duration via ffprobe (best-effort)."""
    out: dict[str, float | int | None] = {
        "width": None,
        "height": None,
        "duration": None,
    }
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        data = json.loads(raw)
        streams = data.get("streams") or []
        if streams:
            out["width"] = int(streams[0].get("width") or 0) or None
            out["height"] = int(streams[0].get("height") or 0) or None
        dur = (data.get("format") or {}).get("duration")
        if dur is not None:
            out["duration"] = float(dur)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"[upload] ffprobe warning: {exc}")
    return out


def warn_if_not_shorts_shape(video_path: Path, cfg: dict | None = None) -> None:
    """Soft checks: vertical 9:16 preferred, duration ≤ soft max (warn only)."""
    cfg = cfg or load_config()
    meta = probe_video_meta(video_path)
    w, h, dur = meta["width"], meta["height"], meta["duration"]
    if w and h:
        if h <= w:
            print(
                f"[upload] WARN: {w}x{h} is not vertical 9:16 — "
                "YouTube may treat this as a normal video, not a Short"
            )
        elif abs((h / w) - (16 / 9)) > 0.08:
            print(f"[upload] WARN: aspect {w}x{h} is vertical but not ~9:16")
        else:
            print(f"[upload] shape OK: {w}x{h} (~9:16)")
    max_dur = soft_max_duration_sec(cfg)
    if dur is not None:
        if dur > max_dur:
            print(
                f"[upload] WARN: duration {dur:.1f}s > soft max {max_dur:.0f}s — "
                "Shorts eligibility may fail; trim narration next run"
            )
        else:
            print(f"[upload] duration OK: {dur:.1f}s <= {max_dur:.0f}s soft max")


def load_seo_metadata(seo_path: Path) -> tuple[str, str, list[str]]:
    data = json.loads(seo_path.read_text(encoding="utf-8"))
    title = ensure_shorts_title((data.get("title") or "").strip())
    description = ensure_shorts_description((data.get("description") or "").strip())
    tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
    if not title or not description or len(tags) < 3:
        raise SystemExit(f"SEO incomplete (need title, description, tags): {seo_path}")
    return title, description, tags


def update_short_metadata(
    video_id: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    category_id: str = "27",
    cfg: dict | None = None,
) -> bool:
    """Try videos().update snippet. Returns False if scope/API rejects (no re-auth)."""
    cfg = cfg or load_config()
    title = ensure_shorts_title((title or "").strip())
    description = ensure_shorts_description((description or "").strip())
    tags = [t for t in (tags or []) if t]
    creds = get_credentials(cfg)
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "id": video_id,
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": str(category_id),
        },
    }
    if tags:
        body["snippet"]["tags"] = tags[:30]
    try:
        youtube.videos().update(part="snippet", body=body).execute()
        print(f"[upload] updated metadata for {video_id}")
        print(f"[upload] title: {title}")
        return True
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        print(f"[upload] update failed ({status}): {exc}")
        if status in (401, 403):
            print(
                "[upload] Token lacks videos.update scope "
                "(youtube.upload is insert-only). Will re-upload instead."
            )
        return False


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
    title = ensure_shorts_title((title or "").strip())
    description = ensure_shorts_description((description or "").strip())
    tags = [t for t in (tags or []) if t]
    if not title or not description or len(tags) < 3:
        raise SystemExit("Refuse upload: empty/generic metadata (title/description/tags required)")
    if not re.search(r"(?i)#shorts\b", title) or not re.search(r"(?i)#shorts\b", description):
        raise SystemExit("Refuse upload: #Shorts required in both title and description")

    warn_if_not_shorts_shape(video_path, cfg)

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
    print(f"[upload] {video_path.name} -> privacy={privacy} category={category_id} (Shorts)")
    print(f"[upload] title: {title}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[upload] {int(status.progress() * 100)}%")
    video_id = response["id"]
    print(f"[upload] OK https://youtube.com/shorts/{video_id}")
    print(f"[upload] OK https://youtu.be/{video_id}")
    return video_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Short using SEO JSON metadata")
    parser.add_argument("--video", required=True, help="Path to mp4")
    parser.add_argument("--seo", required=True, help="Path to seo/{stem}.seo.json")
    parser.add_argument("--privacy", default=None, help="public|private|unlisted")
    parser.add_argument(
        "--update-id",
        default=None,
        help="Try videos().update on existing id before insert (falls back to upload)",
    )
    args = parser.parse_args()
    cfg = load_config()
    title, description, tags = load_seo_metadata(Path(args.seo))
    privacy = args.privacy or (cfg.get("upload") or {}).get("privacy") or "public"
    if args.update_id:
        ok = update_short_metadata(
            args.update_id,
            title=title,
            description=description,
            tags=tags,
            cfg=cfg,
        )
        if ok:
            print(f"[upload] metadata patched: https://youtube.com/shorts/{args.update_id}")
            return
        print("[upload] falling back to new Short upload…")
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
