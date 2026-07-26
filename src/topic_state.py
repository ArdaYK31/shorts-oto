"""Persistent topic rotation — each scheduled run must use a DIFFERENT topic.

State lives under topics/:
  used/{id}.json      — claimed/rendered (skip on next pick)
  uploaded.jsonl      — successfully uploaded (never re-upload same id)

GitHub Actions commits these back so cloud runs don't repeat the same video.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def used_dir(cfg: dict) -> Path:
    d = cfg["paths_resolved"]["topics"] / "used"
    d.mkdir(parents=True, exist_ok=True)
    return d


def uploaded_path(cfg: dict) -> Path:
    return cfg["paths_resolved"]["topics"] / "uploaded.jsonl"


def load_used_ids(cfg: dict) -> set[str]:
    return {p.stem for p in used_dir(cfg).glob("*.json")}


def load_uploaded_ids(cfg: dict) -> set[str]:
    path = uploaded_path(cfg)
    ids: set[str] = set()
    if not path.exists():
        return ids
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            tid = row.get("topic_id") or row.get("id")
            if tid:
                ids.add(str(tid))
        except json.JSONDecodeError:
            continue
    return ids


def blocked_ids(cfg: dict) -> set[str]:
    """Topics that must not be picked again until queue cycles."""
    return load_used_ids(cfg) | load_uploaded_ids(cfg)


def mark_claimed(cfg: dict, topic: dict[str, Any], *, reason: str = "claimed") -> Path:
    """Reserve topic immediately so the next cron cannot pick the same one."""
    path = used_dir(cfg) / f"{topic['id']}.json"
    payload = {
        "id": topic["id"],
        "title": topic.get("title"),
        "status": reason,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def mark_uploaded(
    cfg: dict,
    topic_id: str,
    *,
    youtube_id: str | None = None,
    title: str | None = None,
) -> None:
    path = uploaded_path(cfg)
    row = {
        "topic_id": topic_id,
        "title": title,
        "youtube_id": youtube_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Keep used marker too
    used = used_dir(cfg) / f"{topic_id}.json"
    if used.exists():
        try:
            data = json.loads(used.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"id": topic_id}
        data["status"] = "uploaded"
        data["youtube_id"] = youtube_id
        used.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_used(cfg: dict) -> None:
    for p in used_dir(cfg).glob("*.json"):
        try:
            p.unlink()
        except OSError as exc:
            print(f"[topics] Could not clear {p}: {exc}")
