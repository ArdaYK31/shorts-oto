"""Adapt English SEO pack fields for YouTube / Instagram / TikTok captions."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_seo(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not (data.get("title") or "").strip():
        raise ValueError(f"SEO missing title: {path}")
    return data


def _hashtag_list(seo: dict[str, Any], limit: int = 12) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw in list(seo.get("hashtags") or []) + list(seo.get("tags") or []):
        t = str(raw).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + re.sub(r"[^A-Za-z0-9]", "", t.title())
        key = t.lower()
        if len(t) < 2 or key in seen:
            continue
        seen.add(key)
        tags.append(t)
        if len(tags) >= limit:
            break
    if "#Shorts" not in {t.lower() for t in tags} and "#shorts" not in seen:
        # IG/TT: prefer #HistoryShorts over YouTube-only #Shorts if missing
        if "#AmericanHistory" not in seen:
            tags.insert(0, "#AmericanHistory")
    return tags


def youtube_fields(seo: dict[str, Any]) -> tuple[str, str, list[str]]:
    from seo_pack import ensure_shorts_description, ensure_shorts_title

    title = ensure_shorts_title((seo.get("title") or "").strip())
    description = ensure_shorts_description((seo.get("description") or "").strip())
    tags = [str(t).strip() for t in (seo.get("tags") or []) if str(t).strip()]
    return title, description, tags


def instagram_caption(seo: dict[str, Any], max_len: int = 2100) -> str:
    """IG Reels: hook/title + body + hashtags at end."""
    title = (seo.get("title") or "").strip()
    desc = (seo.get("description") or "").strip()
    # Drop YouTube-only CTA noise lightly; keep hook lines
    lines = [ln for ln in desc.splitlines() if ln.strip()]
    body_parts: list[str] = []
    if title:
        body_parts.append(title)
    for ln in lines:
        if ln.strip().startswith("#"):
            continue
        if "subscribe" in ln.lower() and "chronoshorts" in ln.lower():
            continue
        body_parts.append(ln)
    body = "\n".join(body_parts).strip()
    hashes = " ".join(_hashtag_list(seo, limit=15))
    caption = f"{body}\n\n{hashes}".strip() if hashes else body
    if len(caption) > max_len:
        # Keep hashtags; trim body
        room = max_len - len(hashes) - 4
        caption = f"{body[: max(0, room)].rstrip()}…\n\n{hashes}"
    return caption


def tiktok_caption(seo: dict[str, Any], max_len: int = 2200) -> str:
    """TikTok: title-forward caption + hashtags (title field max ~150 in post_info)."""
    title = (seo.get("title") or "").strip()
    hook = (seo.get("hook") or "").strip()
    lead = title or hook
    hashes = " ".join(_hashtag_list(seo, limit=10))
    extra = ""
    if hook and hook.lower() not in lead.lower():
        extra = f"\n{hook}"
    caption = f"{lead}{extra}\n\n{hashes}".strip() if hashes else f"{lead}{extra}".strip()
    return caption[:max_len]


def tiktok_title(seo: dict[str, Any], max_len: int = 150) -> str:
    title = (seo.get("title") or seo.get("hook") or "American History Short").strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) <= max_len:
        return title
    cut = title[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or title[:max_len]).rstrip(".,;:")


def platform_preview(seo: dict[str, Any]) -> dict[str, Any]:
    yt_t, yt_d, yt_tags = youtube_fields(seo)
    return {
        "youtube": {"title": yt_t, "description": yt_d, "tags": yt_tags},
        "instagram": {"caption": instagram_caption(seo)},
        "tiktok": {"title": tiktok_title(seo), "caption": tiktok_caption(seo)},
    }
