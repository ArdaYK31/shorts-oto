from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config_loader import load_config

# ChronoShorts-style: keyword-forward hook titles, capped for YouTube
TITLE_SOFT_MAX = 70
TITLE_HARD_MAX = 100


def _clamp_title(title: str, limit: int = TITLE_SOFT_MAX) -> str:
    title = re.sub(r"\s+", " ", title.strip())
    if len(title) <= limit:
        return title
    cut = title[: limit - 1].rsplit(" ", 1)[0]
    return (cut or title[:limit]).rstrip(".,;:") + "…"


def _hook_from_script(narration: str) -> str:
    text = narration.strip()
    parts = re.split(r"(?<=(?<![A-Z])[.!?])\s+(?=[A-Z\"'])", text, maxsplit=1)
    hook = parts[0].strip() if parts else text[:140]
    return hook[:180]


def _context_blurb(narration: str, hook: str) -> str:
    """Second block: more of the script without repeating the hook verbatim."""
    body = narration.strip()
    if body.lower().startswith(hook.lower()):
        body = body[len(hook) :].lstrip(" .—-\n")
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) < 40:
        body = narration.strip()
    if len(body) > 320:
        cut = body[:317].rsplit(" ", 1)[0]
        return cut.rstrip(".,;:") + "…"
    return body


def _build_title(topic: dict[str, Any], hook: str) -> str:
    """Prefer topic hook title; ensure primary keyword appears when space allows."""
    base = (topic.get("title") or "").strip()
    keywords = list(topic.get("keywords") or [])
    primary = keywords[0] if keywords else ""
    if not base:
        # ChronoShorts fallback from hook + keyword
        if primary and primary.lower() not in hook.lower():
            base = f"{hook.rstrip('.')} | {primary}"
        else:
            base = hook
    title = _clamp_title(base, TITLE_SOFT_MAX)
    if primary and primary.lower() not in title.lower() and len(title) < 55:
        candidate = _clamp_title(f"{title} — {primary}", TITLE_SOFT_MAX)
        if len(candidate) <= TITLE_SOFT_MAX:
            title = candidate
    return title[:TITLE_HARD_MAX]


def _default_tags(keywords: list[str], defaults: list[str]) -> list[str]:
    """3–5 broad + 5–10 long-tail (cap ~15 for YouTube)."""
    broad = list(defaults)[:5]
    if len(broad) < 3:
        for fill in ("Shorts", "history", "History Shorts", "ChronoShorts", "documentary"):
            if fill.lower() not in {b.lower() for b in broad}:
                broad.append(fill)
            if len(broad) >= 5:
                break

    long_tail: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        long_tail.extend(
            [
                kw,
                f"{kw} explained",
                f"{kw} Shorts",
                f"{kw} history",
                f"who was {kw}" if " " not in kw or kw[0].isupper() else f"{kw} facts",
            ]
        )
    long_tail.extend(
        [
            "History Shorts",
            "did you know history",
            "world history facts",
            "American history Shorts",
            "history documentary Shorts",
        ]
    )

    seen: set[str] = set()
    out: list[str] = []
    for t in broad + long_tail:
        key = t.lower().strip()
        if not key or key in seen or len(t) > 60:
            continue
        seen.add(key)
        out.append(t.strip())
        if len(out) >= 15:
            break
    return out


def _hashtags(keywords: list[str]) -> list[str]:
    base = ["#Shorts", "#History", "#HistoryShorts", "#DidYouKnow", "#Documentary"]
    for kw in keywords[:3]:
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", kw.title())
        if len(tag) > 2 and tag not in base:
            base.append(tag)
    return base[:8]


def build_description(
    hook: str,
    narration: str,
    topic: dict[str, Any],
    hashtags: list[str],
) -> str:
    """SEO description: strong first lines, context, CTA, #Shorts."""
    target = (topic.get("keywords") or ["American history"])[0]
    topic_line = topic.get("topic") or target
    context = _context_blurb(narration, hook)
    hash_line = " ".join(hashtags)
    if "#Shorts" not in hash_line and "shorts" not in hash_line.lower():
        hash_line = "#Shorts " + hash_line

    lines = [
        hook,
        "",
        context,
        "",
        f"About this Short: {topic_line}",
        "",
        "More history that hits different — subscribe for ChronoShorts.",
        "Like & follow if you want the stories textbooks rush past.",
        "",
        hash_line,
    ]
    desc = "\n".join(lines)
    # Ensure #Shorts somewhere (YouTube Shorts discovery)
    if "#Shorts" not in desc and "#shorts" not in desc.lower():
        desc = desc.rstrip() + "\n\n#Shorts"
    return desc


def build_seo_pack(
    topic: dict[str, Any],
    narration: str,
    scenario_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """English-only YouTube SEO pack — system owns title/description/tags."""
    cfg = cfg or load_config()
    upload = cfg.get("upload") or {}
    defaults = list(
        upload.get("default_tags")
        or ["Shorts", "history", "American history", "US history", "documentary"]
    )
    keywords = list(topic.get("keywords") or [])
    target = keywords[0] if keywords else "American history"
    hook = _hook_from_script(narration)
    title = _build_title(topic, hook)
    hashtags = _hashtags(keywords)
    description = build_description(hook, narration, topic, hashtags)
    tags = _default_tags(keywords, defaults)

    if not title.strip():
        raise ValueError("SEO title empty — refuse to publish without metadata")
    if not description.strip() or len(description.strip()) < 40:
        raise ValueError("SEO description too weak — refuse empty/generic metadata")
    if len(tags) < 5:
        raise ValueError("SEO tags insufficient — need broad + long-tail tags")

    thumb_words = title.replace("…", "").split()
    thumbnail_text = " ".join(thumb_words[:5]).upper()

    sched = cfg.get("schedule") or {}
    require_approval = bool(sched.get("require_approval", False))
    auto_upload = bool(sched.get("auto_upload", True))
    # Cloud autopilot: never pending_human_review when approval is off
    if auto_upload and not require_approval:
        approval_status = "auto_approved"
        upload_mode = "autopilot"
        approval_note = (
            "FULL AUTOPILOT: scheduled_run uploads immediately to enabled platforms. "
            "No human Approve step. OAuth only — never password. "
            "Atelier review queue is optional for manual local experiments only."
        )
    else:
        approval_status = "pending_human_review"
        upload_mode = upload.get("mode", "manual")
        approval_note = (
            "Semi-auto: SEO ready; human Approve before upload (local/manual path)."
        )

    pack = {
        "language": "en",
        "episode_id": topic["id"],
        "scenario_id": scenario_id,
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "thumbnail_text": thumbnail_text,
        "target_keyword": target,
        "hook": hook,
        "channel_account": upload.get("google_account") or None,
        "approval": {
            "status": approval_status,
            "upload_mode": upload_mode,
            "require_approval": require_approval,
            "auto_upload": auto_upload,
            "privacy": upload.get("privacy") or sched.get("privacy") or "public",
            "note": approval_note,
        },
        "paid_apis": False,
    }
    return pack


def write_seo_pack(
    topic: dict[str, Any],
    narration: str,
    scenario_id: str | None = None,
) -> Path:
    cfg = load_config()
    seo_dir = cfg["paths_resolved"].get("seo") or (cfg["_root"] / "seo")
    seo_dir.mkdir(parents=True, exist_ok=True)
    pack = build_seo_pack(topic, narration, scenario_id=scenario_id, cfg=cfg)
    out = seo_dir / f"{topic['id']}.seo.json"
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[seo] Wrote {out}")
    print(f"[seo] title: {pack['title']}")
    print(f"[seo] tags: {len(pack['tags'])} | desc chars: {len(pack['description'])}")
    return out


def load_seo_pack(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SEO pack not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    title = (data.get("title") or "").strip()
    desc = (data.get("description") or "").strip()
    tags = [t for t in (data.get("tags") or []) if str(t).strip()]
    if not title or not desc or len(tags) < 3:
        raise ValueError(
            f"SEO pack incomplete (title/description/tags required): {p}"
        )
    return data
