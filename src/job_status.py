"""Job status JSONL + latest.json for Atelier status panel."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _istanbul_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone(timedelta(hours=3)))


def logs_dir() -> Path:
    d = ROOT / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def github_run_url() -> str | None:
    """Build Actions run URL from GitHub-provided env (cloud) when present."""
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    repo = os.environ.get("GITHUB_REPOSITORY") or "ArdaYK31/shorts-oto"
    server = (os.environ.get("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    return f"{server}/{repo}/actions/runs/{run_id}"


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
    for _ in range(4):
        for hh, mm in parsed:
            candidate = datetime(
                day.year, day.month, day.day, hh, mm, tzinfo=now.tzinfo
            )
            if candidate > now:
                out.append(candidate.isoformat())
                if len(out) >= n:
                    return out
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


def load_skip_slots_file() -> dict[str, Any]:
    path = logs_dir() / "skip_slots.json"
    if not path.exists():
        return {"dates": {}, "timezone": "Europe/Istanbul"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"dates": {}, "timezone": "Europe/Istanbul"}
    if not isinstance(data, dict):
        return {"dates": {}, "timezone": "Europe/Istanbul"}
    dates = data.get("dates") or {}
    cleaned: dict[str, list[str]] = {}
    if isinstance(dates, dict):
        for day, slots in dates.items():
            if isinstance(slots, list):
                cleaned[str(day)] = [str(s).strip() for s in slots if str(s).strip()]
    return {
        "dates": cleaned,
        "timezone": data.get("timezone") or "Europe/Istanbul",
        "note": data.get("note"),
    }


def _parse_job_dt(job: dict[str, Any]) -> datetime | None:
    raw = job.get("updated_at") or job.get("ts")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
        return dt.astimezone(_istanbul_now().tzinfo)
    except Exception:  # noqa: BLE001
        return None


def _hour_distance(a: int, b: int) -> int:
    return min((a - b) % 24, (b - a) % 24)


def _slot_hour(slot: str) -> int | None:
    try:
        return int(str(slot).split(":")[0])
    except (TypeError, ValueError):
        return None


def _terminal_jobs(recent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep meaningful outcomes (drop queued/rendering chatter)."""
    keep = {
        "uploaded",
        "failed",
        "rendered",
        "dry_run",
        "skipped_slot",
        "preview",
    }
    out: list[dict[str, Any]] = []
    for j in recent:
        st = str(j.get("status") or "")
        if st in keep or j.get("error"):
            out.append(j)
    return out


def build_today_slots(
    times: list[str],
    recent: list[dict[str, Any]],
    skip_data: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Per-slot view for today: skip state, last result, countdown."""
    now = now or _istanbul_now()
    day = now.strftime("%Y-%m-%d")
    skipped = list((skip_data.get("dates") or {}).get(day) or [])
    terminals = _terminal_jobs(recent)
    today_jobs = []
    for j in terminals:
        dt = _parse_job_dt(j)
        if dt and dt.strftime("%Y-%m-%d") == day:
            today_jobs.append((dt, j))

    slots_out: list[dict[str, Any]] = []
    for slot in times:
        hh = _slot_hour(slot)
        if hh is None:
            continue
        mm = int(str(slot).split(":")[1]) if ":" in str(slot) else 0
        slot_dt = datetime(now.year, now.month, now.day, hh, mm, tzinfo=now.tzinfo)
        is_skip = slot in skipped

        matched: dict[str, Any] | None = None
        matched_dt: datetime | None = None
        for dt, j in today_jobs:
            job_slot = j.get("slot")
            if job_slot and str(job_slot) == slot:
                matched, matched_dt = j, dt
                break
            if _hour_distance(dt.hour, hh) <= 1:
                if matched is None or (matched_dt and dt > matched_dt):
                    matched, matched_dt = j, dt

        if slot_dt > now:
            state = "upcoming"
        elif is_skip or (matched and matched.get("status") == "skipped_slot"):
            state = "skipped"
        elif matched:
            st = str(matched.get("status") or "")
            if st == "uploaded":
                state = "success"
            elif st == "failed" or matched.get("error"):
                state = "failed"
            elif st in {"rendered", "dry_run", "preview"}:
                state = st
            else:
                state = st or "done"
        else:
            state = "missed"

        countdown_sec = max(0, int((slot_dt - now).total_seconds())) if slot_dt > now else 0
        slots_out.append(
            {
                "time": slot,
                "at": slot_dt.isoformat(),
                "state": state,
                "skipped": is_skip or state == "skipped",
                "countdown_sec": countdown_sec,
                "result": (
                    {
                        "status": matched.get("status"),
                        "topic_id": matched.get("topic_id"),
                        "title": matched.get("title"),
                        "error": matched.get("error"),
                        "links": matched.get("links"),
                        "platforms": matched.get("platforms"),
                        "updated_at": matched.get("updated_at") or matched.get("ts"),
                        "run_url": matched.get("run_url"),
                    }
                    if matched
                    else None
                ),
            }
        )
    return slots_out


def peek_next_topic(cfg: dict[str, Any] | None = None) -> dict[str, str] | None:
    """Next queue topic that is not blocked — read-only, never claims."""
    # Prefer filesystem paths so snapshot works even without PyYAML locally.
    try:
        queue_path = ROOT / "topics" / "queue.json"
        used_dir = ROOT / "topics" / "used"
        uploaded = ROOT / "topics" / "uploaded.jsonl"
        queue: list[dict[str, Any]] = []
        if queue_path.exists():
            raw = json.loads(queue_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                queue = [x for x in raw if isinstance(x, dict) and x.get("id")]
        blocked: set[str] = set()
        if used_dir.exists():
            blocked |= {p.stem for p in used_dir.glob("*.json")}
        if uploaded.exists():
            for line in uploaded.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    tid = row.get("topic_id") or row.get("id")
                    if tid:
                        blocked.add(str(tid))
                except json.JSONDecodeError:
                    continue
        for item in queue:
            tid = str(item["id"])
            if tid not in blocked:
                return {"id": tid, "title": str(item.get("title") or tid)}
        if queue:
            item = queue[0]
            return {"id": str(item["id"]), "title": str(item.get("title") or item["id"])}
    except Exception:  # noqa: BLE001
        pass
    try:
        from generate_script import load_queue
        from topic_state import blocked_ids

        cfg = cfg or {}
        if not cfg:
            from config_loader import load_config

            cfg = load_config()
        queue = load_queue(cfg)
        blocked = blocked_ids(cfg)
        for item in queue:
            tid = item.get("id")
            if tid and tid not in blocked:
                return {"id": str(tid), "title": str(item.get("title") or tid)}
        if queue:
            item = queue[0]
            return {"id": str(item["id"]), "title": str(item.get("title") or item["id"])}
    except Exception:  # noqa: BLE001
        return None
    return None


def _last_error_and_success(
    recent: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    last_error = None
    last_success = None
    for j in recent:
        if last_error is None and (j.get("error") or str(j.get("status") or "") == "failed"):
            last_error = {
                "message": j.get("error") or j.get("status"),
                "topic_id": j.get("topic_id"),
                "title": j.get("title"),
                "status": j.get("status"),
                "ts": j.get("updated_at") or j.get("ts"),
                "run_url": j.get("run_url"),
            }
        if last_success is None and str(j.get("status") or "") == "uploaded":
            last_success = {
                "topic_id": j.get("topic_id"),
                "title": j.get("title"),
                "ts": j.get("updated_at") or j.get("ts"),
                "links": j.get("links"),
                "platforms": j.get("platforms"),
                "run_url": j.get("run_url"),
            }
        if last_error and last_success:
            break
    return last_error, last_success


def _read_recent(limit: int = 40) -> list[dict[str, Any]]:
    jl = logs_dir() / "jobs.jsonl"
    recent: list[dict[str, Any]] = []
    if not jl.exists():
        return recent
    try:
        lines = jl.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                recent.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return recent


def _build_latest_payload(
    cfg: dict[str, Any],
    recent: list[dict[str, Any]],
    *,
    latest_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from budget import load_budget

    now = _istanbul_now()
    sched = (cfg.get("schedule") or {}) if cfg else {}
    times = list(sched.get("times") or ["00:00", "08:00", "16:00"])
    budget = load_budget()
    skip_data = load_skip_slots_file()
    chronological = list(recent)
    newest_first = list(reversed(chronological))
    if latest_job is None:
        latest_job = chronological[-1] if chronological else None

    last_error, last_success = _last_error_and_success(newest_first)
    # Prefer explicit error on latest_job if present
    if latest_job and (latest_job.get("error") or str(latest_job.get("status") or "") == "failed"):
        last_error = {
            "message": latest_job.get("error") or latest_job.get("status"),
            "topic_id": latest_job.get("topic_id"),
            "title": latest_job.get("title"),
            "status": latest_job.get("status"),
            "ts": latest_job.get("updated_at") or latest_job.get("ts"),
            "run_url": latest_job.get("run_url") or github_run_url(),
        }

    run_url = github_run_url()
    yt_url = None
    if latest_job:
        links = latest_job.get("links") or {}
        yt_url = links.get("youtube")
        if not yt_url and (latest_job.get("platforms") or {}).get("youtube"):
            yt_url = "https://youtu.be/" + str(latest_job["platforms"]["youtube"])
    if not yt_url and last_success:
        links = last_success.get("links") or {}
        yt_url = links.get("youtube")
        if not yt_url and (last_success.get("platforms") or {}).get("youtube"):
            yt_url = "https://youtu.be/" + str(last_success["platforms"]["youtube"])

    today_slots = build_today_slots(times, newest_first, skip_data, now=now)
    next_runs = next_run_times(times)
    next_slot = None
    for s in today_slots:
        if s["state"] == "upcoming":
            next_slot = s
            break
    if next_slot is None and next_runs:
        next_slot = {
            "time": None,
            "at": next_runs[0],
            "state": "upcoming",
            "countdown_sec": max(
                0,
                int(
                    (
                        datetime.fromisoformat(next_runs[0]) - now
                    ).total_seconds()
                ),
            ),
        }

    return {
        "autopilot": True,
        "require_approval": False,
        "privacy": (sched.get("privacy") or "public"),
        "timezone": sched.get("timezone") or "Europe/Istanbul",
        "schedule_times": times,
        "next_runs": next_runs,
        "next_slot": next_slot,
        "today_slots": today_slots,
        "skip_slots": skip_data,
        "platforms_connected": platform_presence(cfg),
        "budget": {
            "month": budget.get("month"),
            "spent_usd": budget.get("estimated_spend_usd"),
            "cap_usd": budget.get("cap_usd"),
            "images_generated": budget.get("images_generated"),
            "cost_per_image_usd": budget.get("cost_per_image_usd"),
            "provider": budget.get("provider"),
        },
        "latest_job": latest_job,
        "last_error": last_error,
        "last_success": last_success,
        "last_run_url": (
            ((latest_job or {}).get("run_url") if latest_job else None) or run_url
        ),
        "youtube_url": yt_url,
        "next_topic": peek_next_topic(cfg),
        "recent_jobs": newest_first,
        "actions_url": "https://github.com/ArdaYK31/shorts-oto/actions",
        "artifacts_url": "https://github.com/ArdaYK31/shorts-oto/actions",
        "repo_url": "https://github.com/ArdaYK31/shorts-oto",
        "panel_url": "https://ardayk31.github.io/shorts-oto/",
        "updated_at": now.isoformat(),
    }


def append_job(entry: dict[str, Any]) -> dict[str, Any]:
    """Append one JSON line to jobs.jsonl and refresh latest.json."""
    now = _istanbul_now()
    run_url = entry.get("run_url") or github_run_url()
    record = {
        **entry,
        "ts": entry.get("ts") or now.isoformat(),
        "updated_at": now.isoformat(),
    }
    if run_url:
        record["run_url"] = run_url

    jl = logs_dir() / "jobs.jsonl"
    with jl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    recent = _read_recent(40)
    # Ensure the just-written record is included even if read races
    if not recent or recent[-1].get("updated_at") != record.get("updated_at"):
        recent.append(record)

    cfg: dict[str, Any] = {}
    try:
        from config_loader import load_config

        cfg = load_config()
    except Exception:  # noqa: BLE001
        pass

    latest = _build_latest_payload(cfg, recent, latest_job=record)
    (logs_dir() / "latest.json").write_text(
        json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return latest


def write_snapshot(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh latest.json without appending a new job (startup / dry-run)."""
    return _write_latest_only(cfg)


def _write_latest_only(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or {}
    if not cfg:
        try:
            from config_loader import load_config

            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    recent = _read_recent(40)
    latest = _build_latest_payload(cfg, recent)
    (logs_dir() / "latest.json").write_text(
        json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return latest


def save_skip_slots(dates: dict[str, list[str]], *, note: str | None = None) -> Path:
    path = logs_dir() / "skip_slots.json"
    payload = {
        "dates": dates,
        "timezone": "Europe/Istanbul",
        "note": note
        or "Skip only listed Istanbul wall-clock slots; other times and future days run normally.",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def add_skip_slot(skip_date: str, skip_time: str) -> dict[str, Any]:
    data = load_skip_slots_file()
    dates = dict(data.get("dates") or {})
    slots = list(dates.get(skip_date) or [])
    if skip_time not in slots:
        slots.append(skip_time)
        slots.sort()
    dates[skip_date] = slots
    save_skip_slots(dates)
    return load_skip_slots_file()


def clear_skip_slots(
    skip_date: str | None = None,
    skip_time: str | None = None,
) -> dict[str, Any]:
    data = load_skip_slots_file()
    dates = dict(data.get("dates") or {})
    if not skip_date:
        dates = {}
    elif skip_time:
        slots = [s for s in (dates.get(skip_date) or []) if s != skip_time]
        if slots:
            dates[skip_date] = slots
        else:
            dates.pop(skip_date, None)
    else:
        dates.pop(skip_date, None)
    save_skip_slots(dates)
    return load_skip_slots_file()
