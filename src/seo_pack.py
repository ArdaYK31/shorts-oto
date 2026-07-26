from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config_loader import load_config

# ChronoShorts viral SEO: query-style title, ≤3 tags, #Shorts everywhere
TITLE_SOFT_MAX = 70
TITLE_HARD_MAX = 100
SHORTS_HASHTAG = "#Shorts"
_SHORTS_TITLE_SUFFIX = f" {SHORTS_HASHTAG}"
MAX_TAGS = 3


def _clamp_title(title: str, limit: int = TITLE_SOFT_MAX) -> str:
    title = re.sub(r"\s+", " ", title.strip())
    if len(title) <= limit:
        return title
    cut = title[: limit - 1].rsplit(" ", 1)[0]
    return (cut or title[:limit]).rstrip(".,;:") + "…"


def ensure_shorts_title(title: str, hard_max: int = TITLE_HARD_MAX) -> str:
    """Append #Shorts to title end (YouTube Shorts convention)."""
    title = re.sub(r"\s+", " ", (title or "").strip())
    if not title:
        return SHORTS_HASHTAG[:hard_max]
    if re.search(r"#shorts\b", title, re.I):
        return title[:hard_max]
    room = max(8, hard_max - len(_SHORTS_TITLE_SUFFIX))
    base = _clamp_title(title, min(TITLE_SOFT_MAX, room))
    if len(base) > room:
        base = _clamp_title(base, room)
    return (base.rstrip(" .—-") + _SHORTS_TITLE_SUFFIX)[:hard_max]


def ensure_shorts_description(description: str) -> str:
    """Put #Shorts at the very start of the description (and keep hashtag block)."""
    desc = (description or "").strip()
    if not desc:
        return SHORTS_HASHTAG
    if re.match(r"(?i)^#shorts\b", desc):
        return desc
    if re.search(r"(?i)#shorts\b", desc):
        body = re.sub(r"(?i)\s*#shorts\b", "", desc, count=1).strip()
        return f"{SHORTS_HASHTAG}\n\n{body}".strip()
    return f"{SHORTS_HASHTAG}\n\n{desc}"


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


def _query_style_title(topic: dict[str, Any], hook: str) -> str:
    """
    Prefer search-query energy titles (who/why/how/what Americans type).
    Keep topic.title when already query-like; else reshape from claim/hook.
    """
    base = (topic.get("title") or "").strip()
    claim = (topic.get("claim") or topic.get("hook") or hook or "").strip()
    keywords = list(topic.get("keywords") or [])
    primary = keywords[0] if keywords else ""

    query_starts = (
        "why ",
        "how ",
        "who ",
        "what ",
        "when ",
        "did ",
        "was ",
        "is ",
        "the ",
    )
    if base and base.lower().startswith(query_starts):
        return base
    if base:
        return base
    # Build from claim
    c = claim.rstrip(".?!")
    for prefix in ("Did you know ", "Did you know? "):
        if c.lower().startswith(prefix.lower()):
            c = c[len(prefix) :].lstrip("?—- ").strip()
            break
    if primary and primary.lower() not in c.lower():
        return f"Why {c}" if not c.lower().startswith("why ") else c
    return c or primary or "History fact Americans miss"


def _series_episode_number(cfg: dict[str, Any], topic_id: str) -> int:
    """1-based episode index = used count + 1 (stable enough for desc branding)."""
    used_dir = cfg["paths_resolved"]["topics"] / "used"
    used = {p.stem for p in used_dir.glob("*.json")} if used_dir.exists() else set()
    # If this id already claimed, use its position among used; else next number
    if topic_id in used:
        return max(len(used), 1)
    return len(used) + 1


def _build_title(topic: dict[str, Any], hook: str) -> str:
    base = _query_style_title(topic, hook)
    keywords = list(topic.get("keywords") or [])
    primary = keywords[0] if keywords else ""
    room = TITLE_HARD_MAX - len(_SHORTS_TITLE_SUFFIX)
    title = _clamp_title(base, min(TITLE_SOFT_MAX, room))
    if primary and primary.lower() not in title.lower() and len(title) < 50:
        candidate = _clamp_title(f"{title} — {primary}", min(TITLE_SOFT_MAX, room))
        if len(candidate) <= min(TITLE_SOFT_MAX, room):
            title = candidate
    return ensure_shorts_title(title, TITLE_HARD_MAX)


def _default_tags(keywords: list[str], defaults: list[str]) -> list[str]:
    """P0 SEO: max 3 tags — Shorts + up to 2 topical."""
    out: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        t = tag.strip()
        key = t.lower()
        if not t or key in seen or len(t) > 60 or len(out) >= MAX_TAGS:
            return
        seen.add(key)
        out.append(t)

    add("Shorts")
    for kw in keywords:
        add(kw)
        if len(out) >= MAX_TAGS:
            break
    for d in defaults:
        if d.lower() == "shorts":
            continue
        add(d)
        if len(out) >= MAX_TAGS:
            break
    # Fill if still short
    for fill in ("history", "History Shorts", "ChronoShorts"):
        add(fill)
        if len(out) >= MAX_TAGS:
            break
    return out[:MAX_TAGS]


def _hashtags(keywords: list[str]) -> list[str]:
    """Keep description hashtags light; #Shorts always first."""
    base = ["#Shorts", "#History", "#HistoryShorts"]
    for kw in keywords[:2]:
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", kw.title())
        if len(tag) > 2 and tag not in base:
            base.append(tag)
    return base[:5]


def build_description(
    hook: str,
    narration: str,
    topic: dict[str, Any],
    hashtags: list[str],
    *,
    series_name: str = "History Hooks",
    episode: int | None = None,
) -> str:
    """SEO description: #Shorts first, claim hook, soft comment CTA, series #."""
    target = (topic.get("keywords") or ["American history"])[0]
    topic_line = topic.get("topic") or target
    context = _context_blurb(narration, hook)
    hash_line = " ".join(hashtags)
    if not re.search(r"(?i)#shorts\b", hash_line):
        hash_line = f"{SHORTS_HASHTAG} {hash_line}".strip()

    series_line = f"{series_name} #{episode}" if episode else series_name
    source = str(topic.get("source") or "").strip()

    lines = [
        SHORTS_HASHTAG,
        "",
        hook,
        "",
        context,
        "",
        f"About this Short: {topic_line}",
        f"Series: {series_line}",
    ]
    if source:
        lines.extend(["", f"Source: {source}"])
    lines.extend(
        [
            "",
            "Comment the year you thought this happened.",
            "More history that hits different — subscribe for ChronoShorts.",
            "",
            hash_line,
        ]
    )
    return ensure_shorts_description("\n".join(lines))


def build_seo_pack(
    topic: dict[str, Any],
    narration: str,
    scenario_id: str | None = None,
    cfg: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """English-only YouTube SEO pack — query title, ≤3 tags, #Shorts."""
    cfg = cfg or load_config()
    upload = cfg.get("upload") or {}
    defaults = list(
        upload.get("default_tags")
        or ["Shorts", "history", "History Shorts"]
    )
    # Cap defaults at 3 for SEO discipline
    defaults = defaults[:MAX_TAGS]
    keywords = list(topic.get("keywords") or [])
    target = keywords[0] if keywords else "American history"
    hook = (meta or {}).get("claim") or (topic.get("claim") or _hook_from_script(narration))
    if isinstance(hook, str) and len(hook) < 8:
        hook = _hook_from_script(narration)
    title = _build_title(topic, str(hook))
    hashtags = _hashtags(keywords)
    series_name = (cfg.get("project") or {}).get("series") or "History Hooks"
    episode = _series_episode_number(cfg, str(topic.get("id") or ""))
    # Merge source onto topic for description
    topic_for_desc = dict(topic)
    if meta and meta.get("source"):
        topic_for_desc["source"] = meta["source"]
    description = build_description(
        str(hook),
        narration,
        topic_for_desc,
        hashtags,
        series_name=series_name,
        episode=episode,
    )
    tags = _default_tags(keywords, defaults)

    if not title.strip():
        raise ValueError("SEO title empty — refuse to publish without metadata")
    if not description.strip() or len(description.strip()) < 40:
        raise ValueError("SEO description too weak — refuse empty/generic metadata")
    if len(tags) < 1:
        raise ValueError("SEO tags insufficient — need at least Shorts")

    thumb_words = title.replace("…", "").replace("#Shorts", "").split()
    thumbnail_text = " ".join(thumb_words[:5]).upper()

    sched = cfg.get("schedule") or {}
    require_approval = bool(sched.get("require_approval", False))
    auto_upload = bool(sched.get("auto_upload", True))
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
        "series": series_name,
        "episode_number": episode,
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "thumbnail_text": thumbnail_text,
        "target_keyword": target,
        "hook": hook,
        "claim": (meta or {}).get("claim") or topic.get("claim") or hook,
        "source": (meta or {}).get("source") or topic.get("source"),
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
        "seo_rules": {
            "max_tags": MAX_TAGS,
            "query_title": True,
            "shorts_hashtag": True,
        },
    }
    return pack


def write_seo_pack(
    topic: dict[str, Any],
    narration: str,
    scenario_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    cfg = load_config()
    seo_dir = cfg["paths_resolved"].get("seo") or (cfg["_root"] / "seo")
    seo_dir.mkdir(parents=True, exist_ok=True)
    pack = build_seo_pack(
        topic, narration, scenario_id=scenario_id, cfg=cfg, meta=meta
    )
    out = seo_dir / f"{topic['id']}.seo.json"
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[seo] Wrote {out}")
    print(f"[seo] title: {pack['title']}")
    print(f"[seo] tags({len(pack['tags'])}): {pack['tags']} | desc chars: {len(pack['description'])}")
    return out


def load_seo_pack(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SEO pack not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    title = (data.get("title") or "").strip()
    desc = (data.get("description") or "").strip()
    tags = [t for t in (data.get("tags") or []) if str(t).strip()]
    if not title or not desc or len(tags) < 1:
        raise ValueError(
            f"SEO pack incomplete (title/description/tags required): {p}"
        )
    return data
