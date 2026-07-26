"""Upload Reels via official Instagram Graph API (Meta Content Publishing).

Uses resumable binary upload (no public video_url required).
Credentials from env (never commit):
  META_ACCESS_TOKEN  — long-lived Page / User token with instagram_content_publish
  IG_USER_ID         — Instagram professional account id
Optional:
  META_GRAPH_VERSION — default v21.0
  INSTAGRAM_VIDEO_URL — if set, use public URL flow instead of resumable

If credentials missing → skip gracefully (return None). Never opens a browser.
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

from seo_adapt import instagram_caption, load_seo

GRAPH_HOST = "https://graph.facebook.com"
RUPLOAD_HOST = "https://rupload.facebook.com"


def credentials_present() -> bool:
    return bool(os.environ.get("META_ACCESS_TOKEN") and os.environ.get("IG_USER_ID"))


def _graph_version() -> str:
    return (os.environ.get("META_GRAPH_VERSION") or "v21.0").strip()


def _token() -> str:
    return (os.environ.get("META_ACCESS_TOKEN") or "").strip()


def _ig_user_id() -> str:
    return (os.environ.get("IG_USER_ID") or "").strip()


def _wait_container(container_id: str, token: str, timeout_sec: int = 600) -> None:
    url = f"{GRAPH_HOST}/{_graph_version()}/{container_id}"
    deadline = time.time() + timeout_sec
    last = ""
    while time.time() < deadline:
        r = requests.get(
            url,
            params={"fields": "status_code,status", "access_token": token},
            timeout=60,
        )
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"IG container status error: {data['error']}")
        code = (data.get("status_code") or "").upper()
        last = code or str(data)
        print(f"[instagram] container status={code}")
        if code == "FINISHED":
            return
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"IG container failed: {data}")
        time.sleep(8)
    raise TimeoutError(f"IG container not ready after {timeout_sec}s (last={last})")


def _create_resumable_container(caption: str, token: str, ig_user: str) -> str:
    url = f"{GRAPH_HOST}/{_graph_version()}/{ig_user}/media"
    payload = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "share_to_feed": "true",
        "access_token": token,
    }
    r = requests.post(url, data=payload, timeout=120)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"IG create container failed: {json.dumps(data)[:800]}")
    return str(data["id"])


def _upload_binary(container_id: str, video_path: Path, token: str) -> None:
    size = video_path.stat().st_size
    url = f"{RUPLOAD_HOST}/ig-api-upload/{_graph_version()}/{container_id}"
    headers = {
        "Authorization": f"OAuth {token}",
        "offset": "0",
        "file_size": str(size),
        "Content-Type": "application/octet-stream",
    }
    with video_path.open("rb") as f:
        r = requests.post(url, headers=headers, data=f, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"IG rupload failed HTTP {r.status_code}: {r.text[:500]}")
    print(f"[instagram] rupload ok bytes={size}")


def _create_url_container(caption: str, video_url: str, token: str, ig_user: str) -> str:
    url = f"{GRAPH_HOST}/{_graph_version()}/{ig_user}/media"
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
        "access_token": token,
    }
    r = requests.post(url, data=payload, timeout=120)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"IG URL container failed: {json.dumps(data)[:800]}")
    return str(data["id"])


def _publish(container_id: str, token: str, ig_user: str) -> str:
    url = f"{GRAPH_HOST}/{_graph_version()}/{ig_user}/media_publish"
    r = requests.post(
        url,
        data={"creation_id": container_id, "access_token": token},
        timeout=120,
    )
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"IG publish failed: {json.dumps(data)[:800]}")
    return str(data["id"])


def upload_reel(
    video_path: str | Path,
    seo_path: str | Path | None = None,
    caption: str | None = None,
    seo: dict[str, Any] | None = None,
) -> str | None:
    """
    Publish a Reel. Returns Instagram media id, or None if credentials missing (skip).
    Raises on API failure when credentials are present.
    """
    if not credentials_present():
        print("[instagram] skipped: missing META_ACCESS_TOKEN or IG_USER_ID")
        return None

    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    if caption is None:
        if seo is None:
            if seo_path is None:
                raise ValueError("Need caption, seo, or seo_path")
            seo = load_seo(seo_path)
        caption = instagram_caption(seo)

    token = _token()
    ig_user = _ig_user_id()
    public_url = (os.environ.get("INSTAGRAM_VIDEO_URL") or "").strip()

    print(f"[instagram] publishing Reel caption_chars={len(caption)}")
    if public_url:
        container_id = _create_url_container(caption, public_url, token, ig_user)
    else:
        container_id = _create_resumable_container(caption, token, ig_user)
        _upload_binary(container_id, video_path, token)

    _wait_container(container_id, token)
    media_id = _publish(container_id, token, ig_user)
    print(f"[instagram] OK media_id={media_id}")
    return media_id


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Upload Instagram Reel from SEO JSON")
    p.add_argument("--video", required=True)
    p.add_argument("--seo", required=True)
    args = p.parse_args()
    mid = upload_reel(args.video, seo_path=args.seo)
    if mid is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
