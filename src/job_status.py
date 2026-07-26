"""Job status JSONL + latest.json for Atelier status panel."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _istanbul_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:  # noqa: BLE001
        from datetime import timedelta

        return datetime.now(timezone(timedelta(hours=3)))


def logs_dir() -> Path:
    d = ROOT / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def next_run_times(times: list[str] | None = None, n: int = 3) -> list[str]:
    """Next N schedule slots in Istanbul (HH:MM list like 00:00, 08:00, 16:00)."""
    slots = times or ["00:00", "08:00", "16:00"]
    now = _istanbul_now()
    parsed: list[tuple[int, int]] = []
    for t in slots:
        hh, mm = t.split(":")
        parsed.append((int(hh), int(mm)))
    parsed.sort()
    out: list[str] = []
    day = now.date()
    # search up to 3 days ahead
    for _ in range(4):
        for hh, mm in parsed:
            candidate = datetime(
                day.year, day.month, day.day, hh, mm, tzinfo=now.tzinfo
            )
            if candidate > now:
                out.append(candidate.isoformat())
                if len(out) >= n:
                    return out
        # next calendar day
        from datetime import timedelta

        day = day + timedelta(days=1)
    return out


def platform_presence(cfg: dict[str, Any] | None = None) -> dict[str, bool]:
    """Booleans only — never expose secret values."""
    cfg = cfg or {}
    upload = cfg.get("upload") or {}
    cred_dir = ROOT / (upload.get("credentials_dir") or "credentials")
    yt = (cred_dir / "youtube_token.json").exists() and (
        cred_dir / "client_secret.json"
    ).exists()
    # Also treat env-injected cloud secrets as present markers via env flags
    yt_env = bool(
        os.environ.get("YOUTUBE_TOKEN_JSON") or os.environ.get("YOUTUBE_CLIENT_SECRET_JSON")
    )
    return {
        "youtube": yt or yt_env,
        "instagram": bool(os.environ.get("META_ACCESS_TOKEN") and os.environ.get("IG_USER_ID")),
        "tiktok": bool(os.environ.get("TIKTOK_ACCESS_TOKEN")),
        "fal": bool(
            os.environ.get("FAL_KEY")
            or os.environ.get("IMAGE_API_KEY")
            or os.environ.get("FAL_API_KEY")
        ),
    }


def append_job(entry: dict[str, Any]) -> dict[str, Any]:
    """Append one JSON line to jobs.jsonl and refresh latest.json."""
    from budget import load_budget

    now = _istanbul_now()
    record = {
        **entry,
        "ts": entry.get("ts") or now.isoformat(),
        "updated_at": now.isoformat(),
    }
    jl = logs_dir() / "jobs.jsonl"
    with jl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Rebuild recent list (last 40)
    recent: list[dict[str, Any]] = []
    try:
        lines = jl.read_text(encoding="utf-8").splitlines()
        for line in lines[-40:]:
            line = line.strip()
            if not line:
                continue
            try:
                recent.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        recent = [record]

    cfg: dict[str, Any] = {}
    try:
        from config_loader import load_config

        cfg = load_config()
    except Exception:  # noqa: BLE001
        pass

    sched = (cfg.get("schedule") or {}) if cfg else {}
    times = list(sched.get("times") or ["00:00", "08:00", "16:00"])
    budget = load_budget()
    latest = {
        "autopilot": True,
        "require_approval": False,
        "privacy": (sched.get("privacy") or "public"),
        "timezone": sched.get("timezone") or "Europe/Istanbul",
        "schedule_times": times,
        "next_runs": next_run_times(times),
        "platforms_connected": platform_presence(cfg),
        "budget": {
            "month": budget.get("month"),
            "spent_usd": budget.get("estimated_spend_usd"),
            "cap_usd": budget.get("cap_usd"),
            "images_generated": budget.get("images_generated"),
            "cost_per_image_usd": budget.get("cost_per_image_usd"),
            "provider": budget.get("provider"),
        },
        "latest_job": record,
        "recent_jobs": list(reversed(recent)),
        "actions_url": "https://github.com/ArdaYK31/shorts-oto/actions",
        "updated_at": now.isoformat(),
    }
    (logs_dir() / "latest.json").write_text(
        json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return latest


def write_snapshot(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh latest.json without appending a new job (startup / dry-run)."""
    return _write_latest_only(cfg)


def _write_latest_only(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    from budget import load_budget

    now = _istanbul_now()
    jl = logs_dir() / "jobs.jsonl"
    recent: list[dict[str, Any]] = []
    if jl.exists():
        for line in jl.read_text(encoding="utf-8").splitlines()[-40:]:
            line = line.strip()
            if not line:
                continue
            try:
                recent.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    cfg = cfg or {}
    if not cfg:
        try:
            from config_loader import load_config

            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    sched = cfg.get("schedule") or {}
    times = list(sched.get("times") or ["00:00", "08:00", "16:00"])
    budget = load_budget()
    latest = {
        "autopilot": True,
        "require_approval": False,
        "privacy": sched.get("privacy") or "public",
        "timezone": sched.get("timezone") or "Europe/Istanbul",
        "schedule_times": times,
        "next_runs": next_run_times(times),
        "platforms_connected": platform_presence(cfg),
        "budget": {
            "month": budget.get("month"),
            "spent_usd": budget.get("estimated_spend_usd"),
            "cap_usd": budget.get("cap_usd"),
            "images_generated": budget.get("images_generated"),
            "cost_per_image_usd": budget.get("cost_per_image_usd"),
            "provider": budget.get("provider"),
        },
        "latest_job": recent[-1] if recent else None,
        "recent_jobs": list(reversed(recent)),
        "actions_url": "https://github.com/ArdaYK31/shorts-oto/actions",
        "updated_at": now.isoformat(),
    }
    (logs_dir() / "latest.json").write_text(
        json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return latest
