"""Cloud/local daily Shorts job: pick topic → pipeline → SEO → multi-platform upload.

Platforms (config.platforms + secrets):
  YouTube Shorts, Instagram Reels, TikTok

Designed for GitHub Actions / Docker (PC can be OFF). Never opens a browser.
Exit non-zero if pipeline fails OR if an *enabled+credentialed* platform fails.
Missing Meta/TikTok secrets → skip those platforms (YouTube still works).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent


def _ensure_espeak_data_path() -> None:
    if os.environ.get("ESPEAK_DATA_PATH"):
        existing = Path(os.environ["ESPEAK_DATA_PATH"])
        if existing.exists():
            return
    candidates = [
        Path(r"C:\espeak-ng-data"),
        Path("/usr/lib/x86_64-linux-gnu/espeak-ng-data"),
        Path("/usr/lib/aarch64-linux-gnu/espeak-ng-data"),
        Path("/usr/share/espeak-ng-data"),
        Path("/usr/lib/espeak-ng-data"),
    ]
    for c in candidates:
        if (c / "phontab").exists():
            os.environ["ESPEAK_DATA_PATH"] = str(c)
            print(f"[schedule] ESPEAK_DATA_PATH={c}")
            return
    print("[schedule] WARNING: espeak-ng data not found; Kokoro may fail")


_ensure_espeak_data_path()

from assemble import assemble  # noqa: E402
from captions import make_captions  # noqa: E402
from cleanup_temps import cleanup_temp_mp4s  # noqa: E402
from config_loader import load_config  # noqa: E402
from fetch_media import fetch_media  # noqa: E402
from generate_script import generate_script, load_queue, pick_topic  # noqa: E402
from fact_gate import FactGateError, assert_source, topic_source  # noqa: E402
from job_status import append_job, write_snapshot  # noqa: E402
from quality_gates import check_output  # noqa: E402
from seo_adapt import load_seo, platform_preview  # noqa: E402
from topic_state import (  # noqa: E402
    HARD_BANNED_TOPIC_IDS,
    blocked_ids,
    clear_used,
    mark_claimed,
    mark_uploaded,
)
from tts import synthesize  # noqa: E402
from sfx import ensure_sfx_library  # noqa: E402
from upload_instagram import credentials_present as ig_creds  # noqa: E402
from upload_instagram import upload_reel  # noqa: E402
from upload_tiktok import credentials_present as tt_creds  # noqa: E402
from upload_tiktok import upload_video as upload_tiktok  # noqa: E402
from youtube_upload import load_seo_metadata, upload_short  # noqa: E402


def _istanbul_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:  # noqa: BLE001
        # Windows without tzdata: fixed GMT+3
        from datetime import timedelta

        return datetime.now(timezone(timedelta(hours=3)))


def _log_path(_cfg: dict) -> Path:
    logs = ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "schedule.log"


def append_log(cfg: dict, message: str) -> None:
    path = _log_path(cfg)
    ts = _istanbul_now().strftime("%Y-%m-%d %H:%M:%S %z")
    line = f"[{ts}] {message}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line.rstrip())


def _skip_slots_path() -> Path:
    return ROOT / "logs" / "skip_slots.json"


def _force_next_topic_path() -> Path:
    return ROOT / "logs" / "force_next_topic.json"


def load_skip_slots() -> dict[str, list[str]]:
    """Return {YYYY-MM-DD: ["HH:MM", ...]} from logs/skip_slots.json."""
    path = _skip_slots_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[schedule] WARN skip_slots.json unreadable: {exc}")
        return {}
    dates = data.get("dates") or {}
    out: dict[str, list[str]] = {}
    for day, slots in dates.items():
        if isinstance(slots, list):
            out[str(day)] = [str(s).strip() for s in slots if str(s).strip()]
    return out


def load_force_next_topic(now: datetime | None = None) -> str | None:
    """Return staged topic_id from logs/force_next_topic.json when the slot matches.

    If upload_at is set (ISO datetime, Europe/Istanbul), only honor on that
    Istanbul calendar day within ±1 hour of the target hour — so a daytime
    preview_only run cannot burn the midnight force early.
    """
    path = _force_next_topic_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[schedule] WARN force_next_topic.json unreadable: {exc}")
        return None
    if not isinstance(data, dict):
        return None
    tid = data.get("topic_id") or data.get("id")
    if not tid or not str(tid).strip():
        return None
    tid = str(tid).strip()
    upload_at_raw = data.get("upload_at")
    if not upload_at_raw:
        return tid
    now = now or _istanbul_now()
    try:
        target = datetime.fromisoformat(str(upload_at_raw).strip())
    except ValueError as exc:
        print(f"[schedule] WARN force_next_topic upload_at invalid: {exc}")
        return tid
    if target.tzinfo is None:
        try:
            target = target.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
        except Exception:  # noqa: BLE001
            from datetime import timedelta

            target = target.replace(tzinfo=timezone(timedelta(hours=3)))
    target_local = target.astimezone(now.tzinfo)
    if target_local.strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
        print(
            f"[schedule] force_next_topic={tid} deferred "
            f"(upload_at={target_local.isoformat()} now={now.isoformat()})"
        )
        return None
    if _hour_distance(now.hour, target_local.hour) > 1:
        print(
            f"[schedule] force_next_topic={tid} deferred "
            f"(hour {now.hour} vs target {target_local.hour})"
        )
        return None
    return tid


def clear_force_next_topic(*, reason: str = "consumed") -> None:
    path = _force_next_topic_path()
    if not path.exists():
        return
    try:
        path.unlink()
        print(f"[schedule] cleared force_next_topic.json ({reason})")
    except OSError as exc:
        print(f"[schedule] WARN could not clear force_next_topic.json: {exc}")


def _hour_distance(a: int, b: int) -> int:
    return min((a - b) % 24, (b - a) % 24)


def should_skip_slot(cfg: dict, now: datetime | None = None) -> str | None:
    """If today's Istanbul slot is listed in skip_slots.json, return that HH:MM.

    Matches cron hour ±1 (e.g. 08:00 → 07–09) so slightly late Actions still
    skip, without treating early morning (06:xx) as the 08:00 slot.
    """
    del cfg  # reserved for future config-driven paths
    now = now or _istanbul_now()
    day = now.strftime("%Y-%m-%d")
    skipped = load_skip_slots().get(day) or []
    hour = now.hour
    for slot in skipped:
        try:
            slot_hour = int(str(slot).split(":")[0])
        except (TypeError, ValueError):
            continue
        if _hour_distance(hour, slot_hour) <= 1:
            return slot
    return None


def platform_flags(cfg: dict) -> dict[str, bool]:
    p = cfg.get("platforms") or {}
    return {
        "youtube": bool(p.get("youtube", True)),
        "instagram": bool(p.get("instagram", True)),
        "tiktok": bool(p.get("tiktok", True)),
    }


def pick_next_topic_id(cfg: dict, topic_id: str | None = None) -> str:
    """Each cron slot must get a DIFFERENT topic — never re-upload the same video."""
    if topic_id:
        if topic_id in HARD_BANNED_TOPIC_IDS:
            print(
                f"[schedule] REFUSING banned topic_id={topic_id} "
                f"(HARD_BANNED_TOPIC_IDS) — picking next eligible instead"
            )
            # Fall through to normal unique pick (ignore force/CLI for banned ids)
        else:
            return topic_id

    queue = load_queue(cfg)
    if not queue:
        raise SystemExit("topics/queue.json is empty — add topics first")

    require_source = bool((cfg.get("script") or {}).get("require_source", True)) or bool(
        (cfg.get("quality_gates") or {}).get("require_source", True)
    )
    blocked = blocked_ids(cfg)
    skipped_no_source = 0
    for item in queue:
        if item["id"] in blocked:
            continue
        if require_source and not topic_source(item):
            skipped_no_source += 1
            print(
                f"[fact_gate] SKIP (no source) topic={item['id']} — "
                f"add source to queue.json before TTS"
            )
            continue
        # us_audience_score is a schema hint for topic authors / future ranking
        score = item.get("us_audience_score")
        score_bit = f" us_score={score}" if score is not None else ""
        print(
            f"[schedule] UNIQUE topic selected: {item['id']}{score_bit} "
            f"(blocked={len(blocked)} prior used/uploaded"
            f"{f', skipped_no_source={skipped_no_source}' if skipped_no_source else ''})"
        )
        return item["id"]

    if skipped_no_source and skipped_no_source >= len(
        [i for i in queue if i["id"] not in blocked]
    ):
        raise SystemExit(
            "[fact_gate] No unused topics with a 'source' field. "
            "Add real citations to topics/queue.json (do not invent)."
        )

    print(
        "[schedule] All topics used/uploaded — cycling used/ "
        "(uploaded.jsonl kept so we still prefer fresh if queue grows)"
    )
    clear_used(cfg)
    blocked = blocked_ids(cfg)
    for item in queue:
        if item["id"] in blocked:
            continue
        if require_source and not topic_source(item):
            continue
        return item["id"]
    # Full cycle exhausted — allow re-run from start of queue
    print("[schedule] Full cycle complete — restarting from first topic")
    return queue[0]["id"]


def run_pipeline(
    topic_id: str,
    cfg: dict,
    *,
    enforce_quality_gates: bool = True,
) -> tuple[Path, Path]:
    script_path = generate_script(topic_id)
    stem = script_path.stem
    meta_path = script_path.parent / f"{stem}.meta.json"

    cleanup_temp_mp4s(stem=stem, keep=cfg["paths_resolved"]["out"] / f"{stem}.mp4")

    ensure_sfx_library(cfg)

    audio_path = synthesize(script_path)
    fetch_media(meta_path)
    caption_path = make_captions(script_path, audio_path)
    out = assemble(stem=stem, audio_path=audio_path, caption_path=caption_path)
    cleanup_temp_mp4s(stem=stem, keep=out)

    gate = check_output(out, cfg)
    if not gate["ok"]:
        msg = "[quality_gates] FAILED: " + "; ".join(gate["errors"])
        # Preview-only (--skip-upload): keep artifact success as exit 0.
        # Cron uploads still hard-fail so a >60s Short never goes public.
        if enforce_quality_gates:
            raise SystemExit(msg)
        print(f"[quality_gates] WARN (skip-upload preview, artifact kept): {msg}")
        append_log(cfg, f"WARN quality_gates skip-upload topic={topic_id} {msg}")
    else:
        print(
            f"[quality_gates] OK duration={gate['duration_sec']:.1f}s path={out.name}"
        )

    seo_dir = cfg["paths_resolved"].get("seo") or (ROOT / "seo")
    seo_path = seo_dir / f"{stem}.seo.json"
    if not seo_path.exists():
        raise SystemExit(f"SEO pack missing after pipeline: {seo_path}")
    return out, seo_path


def resolve_privacy(cfg: dict) -> str:
    sched = cfg.get("schedule") or {}
    upload = cfg.get("upload") or {}
    return sched.get("privacy") or upload.get("privacy") or "public"


def yt_credentials_ok(cfg: dict) -> bool:
    upload = cfg.get("upload") or {}
    cred_dir = ROOT / (upload.get("credentials_dir") or "credentials")
    return (cred_dir / "youtube_token.json").exists() and (
        cred_dir / "client_secret.json"
    ).exists()


def upload_all_platforms(
    cfg: dict,
    video_path: Path,
    seo_path: Path,
) -> dict[str, str | None]:
    """Upload to enabled platforms. Skips if disabled or credentials missing."""
    flags = platform_flags(cfg)
    seo = load_seo(seo_path)
    results: dict[str, str | None] = {
        "youtube": None,
        "instagram": None,
        "tiktok": None,
    }
    errors: list[str] = []

    if flags["youtube"]:
        if not yt_credentials_ok(cfg):
            print("[youtube] skipped: missing credentials/client_secret.json or youtube_token.json")
            append_log(cfg, "SKIP youtube: missing credentials")
        else:
            try:
                title, description, tags = load_seo_metadata(seo_path)
                privacy = resolve_privacy(cfg)
                vid = upload_short(
                    video_path,
                    title=title,
                    description=description,
                    tags=tags,
                    privacy=privacy,
                    cfg=cfg,
                )
                results["youtube"] = vid
                append_log(cfg, f"OK youtube id={vid} url=https://youtu.be/{vid}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"youtube:{exc}")
                append_log(cfg, f"FAIL youtube error={exc!r}")
    else:
        print("[youtube] disabled in config.platforms")

    if flags["instagram"]:
        if not ig_creds():
            print("[instagram] skipped: missing META_ACCESS_TOKEN or IG_USER_ID")
            append_log(cfg, "SKIP instagram: missing credentials")
        else:
            try:
                mid = upload_reel(video_path, seo=seo)
                results["instagram"] = mid
                append_log(cfg, f"OK instagram media_id={mid}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"instagram:{exc}")
                append_log(cfg, f"FAIL instagram error={exc!r}")
    else:
        print("[instagram] disabled in config.platforms")

    if flags["tiktok"]:
        if not tt_creds():
            print("[tiktok] skipped: missing TIKTOK_ACCESS_TOKEN")
            append_log(cfg, "SKIP tiktok: missing credentials")
        else:
            try:
                pid = upload_tiktok(video_path, seo=seo)
                results["tiktok"] = pid
                append_log(cfg, f"OK tiktok publish_id={pid}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"tiktok:{exc}")
                append_log(cfg, f"FAIL tiktok error={exc!r}")
    else:
        print("[tiktok] disabled in config.platforms")

    if errors:
        raise RuntimeError("Platform upload failures: " + "; ".join(errors))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scheduled ChronoShorts job (cloud: YT + IG + TikTok)"
    )
    parser.add_argument("--topic-id", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pick topic + print platform plan (no render, no upload)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Full pipeline only; no platform uploads",
    )
    args = parser.parse_args()

    cfg = load_config()
    sched = cfg.get("schedule") or {}
    # FULL AUTOPILOT defaults — never wait for Approve / review queue
    auto_upload = bool(sched.get("auto_upload", True))
    require_approval = bool(sched.get("require_approval", False))
    if require_approval:
        print(
            "[schedule] WARNING: schedule.require_approval=true in config — "
            "forcing false for cloud autopilot path (no human gate)."
        )
        require_approval = False
        sched = {**sched, "require_approval": False}
        cfg["schedule"] = sched
    flags = platform_flags(cfg)

    topic_id = None
    title = None
    forced_tid = None
    try:
        write_snapshot(cfg)
        skip_slot = should_skip_slot(cfg)
        if skip_slot:
            msg = f"SKIP slot {skip_slot} today"
            append_log(cfg, msg)
            append_job(
                {
                    "topic_id": None,
                    "title": None,
                    "status": "skipped_slot",
                    "slot": skip_slot,
                    "platforms": {},
                    "note": msg,
                }
            )
            print(f"[schedule] {msg}")
            return 0
        forced_tid = None if args.topic_id else load_force_next_topic()
        if forced_tid and forced_tid in HARD_BANNED_TOPIC_IDS:
            clear_force_next_topic(reason=f"banned topic={forced_tid}")
            print(
                f"[schedule] cleared force_next_topic — banned id={forced_tid}"
            )
            forced_tid = None
        topic_id = pick_next_topic_id(cfg, args.topic_id or forced_tid)
        if forced_tid and topic_id == forced_tid:
            append_log(
                cfg,
                f"FORCE topic={topic_id} from logs/force_next_topic.json "
                f"(staged prototype / midnight slot)",
            )
            print(f"[schedule] FORCE topic_id={topic_id} (force_next_topic.json)")
        topic = pick_topic(cfg, topic_id)
        title = topic.get("title") or topic_id
        # Fact gate BEFORE claim — soft-fail without burning a used/ slot
        try:
            assert_source(topic)
        except FactGateError as exc:
            msg = str(exc)
            print(msg)
            append_log(cfg, msg)
            append_job(
                {
                    "topic_id": topic_id,
                    "title": title,
                    "status": "skipped_no_source",
                    "platforms": {},
                    "note": msg,
                }
            )
            return 0
        # Claim immediately so the next cron cannot pick the same topic
        # even if this run fails mid-pipeline (used/ is committed by Actions).
        # Preview-only (--skip-upload): do NOT claim — leave topic free for the
        # staged midnight upload (force_next_topic.json / natural queue pick).
        if args.skip_upload:
            append_log(
                cfg,
                f"PREVIEW no-claim topic={topic_id} title={title!r} "
                f"(--skip-upload; topic stays eligible for scheduled upload)",
            )
            print(f"[schedule] PREVIEW no-claim topic={topic_id}")
        else:
            claimed_path = mark_claimed(cfg, topic)
            append_log(
                cfg,
                f"CLAIMED unique topic={topic_id} title={title!r} path={claimed_path} "
                f"(each cron slot must upload a DIFFERENT Short)",
            )
        append_log(
            cfg,
            f"START topic={topic_id} title={title!r} "
            f"autopilot auto_upload={auto_upload} require_approval={require_approval}",
        )
        append_job(
            {
                "topic_id": topic_id,
                "title": title,
                "status": "queued",
                "platforms": {},
            }
        )

        if args.dry_run:
            append_log(
                cfg,
                f"DRY-RUN topic={topic_id} platforms={json.dumps(flags)} "
                f"yt_creds={yt_credentials_ok(cfg)} ig_creds={ig_creds()} "
                f"tt_creds={tt_creds()} privacy={resolve_privacy(cfg)} "
                f"require_approval=false",
            )
            append_job(
                {
                    "topic_id": topic_id,
                    "title": title,
                    "status": "dry_run",
                    "platforms": {},
                }
            )
            print(f"[dry-run] Topic: {topic_id}")
            print(f"[dry-run] Title: {topic.get('title')}")
            print(f"[dry-run] Platforms: {flags}")
            print(f"[dry-run] Autopilot: upload immediately (no approval)")
            print(f"[dry-run] YT creds: {yt_credentials_ok(cfg)}")
            print(f"[dry-run] IG creds: {ig_creds()}")
            print(f"[dry-run] TT creds: {tt_creds()}")
            return 0

        append_job(
            {
                "topic_id": topic_id,
                "title": title,
                "status": "rendering",
                "platforms": {},
            }
        )
        video_path, seo_path = run_pipeline(
            topic_id,
            cfg,
            enforce_quality_gates=not args.skip_upload,
        )
        # Never honor SEO approval.status=pending — cloud path always uploads
        try:
            seo_data = json.loads(seo_path.read_text(encoding="utf-8"))
            appr = seo_data.get("approval") or {}
            appr["status"] = "auto_approved"
            appr["require_approval"] = False
            appr["auto_upload"] = True
            appr["upload_mode"] = "autopilot"
            appr["note"] = (
                "FULL AUTOPILOT: uploaded by scheduled_run without human approval."
            )
            seo_data["approval"] = appr
            seo_path.write_text(
                json.dumps(seo_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[schedule] SEO approval stamp skipped: {exc}")

        preview = platform_preview(load_seo(seo_path))
        print(f"[schedule] Video: {video_path}")
        print(f"[schedule] YT title: {preview['youtube']['title']}")
        print("[schedule] AUTOPILOT: uploading now (no Approve button / no queue wait)")

        if args.skip_upload:
            append_log(
                cfg,
                f"OK pipeline-only topic={topic_id} video={video_path.name} "
                f"(--skip-upload flag)",
            )
            append_job(
                {
                    "topic_id": topic_id,
                    "title": title,
                    "status": "rendered",
                    "video": video_path.name,
                    "platforms": {},
                    "note": "skip_upload",
                }
            )
            return 0
        if not auto_upload:
            append_log(
                cfg,
                "WARN auto_upload=false ignored on scheduled_run — forcing upload",
            )

        results = upload_all_platforms(cfg, video_path, seo_path)
        mark_uploaded(
            cfg,
            topic_id,
            youtube_id=results.get("youtube"),
            title=title,
        )
        if forced_tid and topic_id == forced_tid:
            clear_force_next_topic(reason=f"uploaded topic={topic_id}")
        links = {
            "youtube": (
                f"https://youtu.be/{results['youtube']}" if results.get("youtube") else None
            ),
            "instagram": results.get("instagram"),
            "tiktok": results.get("tiktok"),
        }
        append_log(
            cfg,
            f"DONE unique topic={topic_id} autopilot=true "
            f"results={json.dumps(results)} marked_uploaded=true",
        )
        append_job(
            {
                "topic_id": topic_id,
                "title": title,
                "status": "uploaded",
                "video": video_path.name,
                "platforms": results,
                "links": links,
            }
        )
        return 0

    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 1
        if code == 0:
            return 0
        msg = str(exc) if exc.args else f"SystemExit({code})"
        append_log(cfg, f"FAIL topic={topic_id or '?'} error={msg}")
        append_job(
            {
                "topic_id": topic_id,
                "title": title,
                "status": "failed",
                "error": msg,
                "platforms": {},
            }
        )
        return code if code else 1
    except Exception as exc:  # noqa: BLE001
        append_log(cfg, f"FAIL topic={topic_id or '?'} error={exc!r}")
        append_job(
            {
                "topic_id": topic_id,
                "title": title,
                "status": "failed",
                "error": repr(exc),
                "platforms": {},
            }
        )
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
