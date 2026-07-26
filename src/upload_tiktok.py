"""Upload via official TikTok Content Posting API (Direct Post / FILE_UPLOAD).

Credentials from env (never commit):
  TIKTOK_ACCESS_TOKEN  — user access token with video.publish (or video.upload)
Optional:
  TIKTOK_PRIVACY_LEVEL — default PUBLIC_TO_EVERYONE (herkese açık)
                         | MUTUAL_FOLLOW_FRIENDS | SELF_ONLY
                         (must be allowed for the creator; queried when possible)
  TIKTOK_DISABLE_COMMENT / TIKTOK_DISABLE_DUET / TIKTOK_DISABLE_STITCH — true/false
  TIKTOK_MODE — direct (default) | inbox (draft upload, easier audit)

If token missing → skip gracefully (return None). Never opens a browser.
App review may be required before Direct Post works in production.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seo_adapt import load_seo, tiktok_caption, tiktok_title

API = "https://open.tiktokapis.com"


def credentials_present() -> bool:
    return bool(os.environ.get("TIKTOK_ACCESS_TOKEN"))


def _token() -> str:
    return (os.environ.get("TIKTOK_ACCESS_TOKEN") or "").strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def query_creator_info(token: str) -> dict[str, Any]:
    r = requests.post(
        f"{API}/v2/post/publish/creator_info/query/",
        headers=_headers(token),
        json={},
        timeout=60,
    )
    data = r.json()
    if data.get("error", {}).get("code") not in (None, "ok"):
        print(f"[tiktok] creator_info warning: {data.get('error')}")
    return data.get("data") or {}


def _pick_privacy(creator: dict[str, Any]) -> str:
    # Default: public (herkese açık). Override only via TIKTOK_PRIVACY_LEVEL.
    preferred = (os.environ.get("TIKTOK_PRIVACY_LEVEL") or "PUBLIC_TO_EVERYONE").strip()
    allowed = list(creator.get("privacy_level_options") or [])
    if preferred and (not allowed or preferred in allowed):
        return preferred
    for cand in (
        "PUBLIC_TO_EVERYONE",
        "MUTUAL_FOLLOW_FRIENDS",
        "FOLLOWER_OF_CREATOR",
        "SELF_ONLY",
    ):
        if not allowed or cand in allowed:
            return cand
    return "PUBLIC_TO_EVERYONE"


def _init_direct(
    token: str,
    title: str,
    privacy: str,
    video_size: int,
    chunk_size: int,
) -> tuple[str, str]:
    body = {
        "post_info": {
            "title": title[:150],
            "privacy_level": privacy,
            "disable_duet": _bool_env("TIKTOK_DISABLE_DUET", False),
            "disable_comment": _bool_env("TIKTOK_DISABLE_COMMENT", False),
            "disable_stitch": _bool_env("TIKTOK_DISABLE_STITCH", False),
            "video_made_with_ai": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": 1,
        },
    }
    r = requests.post(
        f"{API}/v2/post/publish/video/init/",
        headers=_headers(token),
        json=body,
        timeout=120,
    )
    data = r.json()
    err = data.get("error") or {}
    if err.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {json.dumps(data)[:800]}")
    d = data.get("data") or {}
    publish_id = d.get("publish_id")
    upload_url = d.get("upload_url")
    if not publish_id or not upload_url:
        raise RuntimeError(f"TikTok init missing publish_id/upload_url: {data}")
    return str(publish_id), str(upload_url)


def _init_inbox(token: str, video_size: int, chunk_size: int) -> tuple[str, str]:
    """Draft/inbox upload — often available before full Direct Post audit."""
    body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": 1,
        },
    }
    r = requests.post(
        f"{API}/v2/post/publish/inbox/video/init/",
        headers=_headers(token),
        json=body,
        timeout=120,
    )
    data = r.json()
    err = data.get("error") or {}
    if err.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok inbox init failed: {json.dumps(data)[:800]}")
    d = data.get("data") or {}
    publish_id = d.get("publish_id")
    upload_url = d.get("upload_url")
    if not publish_id or not upload_url:
        raise RuntimeError(f"TikTok inbox init missing fields: {data}")
    return str(publish_id), str(upload_url)


def _put_video(upload_url: str, video_path: Path) -> None:
    size = video_path.stat().st_size
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}",
    }
    with video_path.open("rb") as f:
        r = requests.put(upload_url, headers=headers, data=f, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"TikTok upload PUT failed HTTP {r.status_code}: {r.text[:500]}")
    print(f"[tiktok] upload ok bytes={size}")


def _wait_publish(token: str, publish_id: str, timeout_sec: int = 600) -> str:
    deadline = time.time() + timeout_sec
    last = ""
    while time.time() < deadline:
        r = requests.post(
            f"{API}/v2/post/publish/status/fetch/",
            headers=_headers(token),
            json={"publish_id": publish_id},
            timeout=60,
        )
        data = r.json()
        status = ((data.get("data") or {}).get("status") or "").upper()
        last = status or str(data)[:200]
        print(f"[tiktok] status={status}")
        if status in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}:
            return status
        if status in {"FAILED", "PUBLISH_FAILED"}:
            raise RuntimeError(f"TikTok publish failed: {data}")
        time.sleep(8)
    raise TimeoutError(f"TikTok publish timeout (last={last})")


def upload_video(
    video_path: str | Path,
    seo_path: str | Path | None = None,
    seo: dict[str, Any] | None = None,
    title: str | None = None,
    caption: str | None = None,
) -> str | None:
    """
    Upload/post to TikTok. Returns publish_id, or None if credentials missing.
    """
    if not credentials_present():
        print("[tiktok] skipped: missing TIKTOK_ACCESS_TOKEN")
        return None

    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    if seo is None and seo_path is not None:
        seo = load_seo(seo_path)
    if seo is not None:
        title = title or tiktok_title(seo)
        caption = caption or tiktok_caption(seo)
    title = (title or "American History Short").strip()[:150]
    # Direct Post uses title; include hashtags from caption when space allows
    if caption and len(title) < 120:
        # Append a few hashtags into title field (TikTok caption = title)
        extra = caption[len(title) :].strip() if caption.startswith(title) else ""
        if not extra:
            # take hashtag line from caption
            for ln in caption.splitlines():
                if ln.strip().startswith("#"):
                    extra = ln.strip()
                    break
        if extra:
            combined = f"{title} {extra}".strip()
            title = combined[:150]

    token = _token()
    size = video_path.stat().st_size
    chunk_size = size  # single chunk for Shorts-sized files
    mode = (os.environ.get("TIKTOK_MODE") or "direct").strip().lower()

    print(f"[tiktok] mode={mode} title={title!r}")
    creator = {}
    if mode != "inbox":
        try:
            creator = query_creator_info(token)
        except Exception as exc:  # noqa: BLE001
            print(f"[tiktok] creator_info skipped: {exc}")

    privacy = _pick_privacy(creator)
    try:
        if mode == "inbox":
            publish_id, upload_url = _init_inbox(token, size, chunk_size)
        else:
            publish_id, upload_url = _init_direct(
                token, title, privacy, size, chunk_size
            )
    except RuntimeError as exc:
        # Fallback to inbox if Direct Post blocked (audit / scope)
        if mode != "inbox":
            print(f"[tiktok] Direct Post failed ({exc}); trying inbox draft…")
            publish_id, upload_url = _init_inbox(token, size, chunk_size)
            mode = "inbox"
        else:
            raise

    _put_video(upload_url, video_path)
    status = _wait_publish(token, publish_id)
    print(f"[tiktok] OK publish_id={publish_id} status={status} mode={mode}")
    return publish_id


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Upload TikTok video from SEO JSON")
    p.add_argument("--video", required=True)
    p.add_argument("--seo", required=True)
    args = p.parse_args()
    pid = upload_video(args.video, seo_path=args.seo)
    if pid is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
