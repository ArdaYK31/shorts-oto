from __future__ import annotations

import json

import subprocess
from pathlib import Path
from typing import Any


def _ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    return float(subprocess.check_output(cmd, text=True).strip())



def _ffprobe_av_durations(path: Path) -> tuple[float | None, float | None]:
    """Return (video_stream_duration, audio_stream_duration) best-effort."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        data = json.loads(subprocess.check_output(cmd, text=True))
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None, None
    v = a = None
    for s in data.get("streams") or []:
        dur = s.get("duration")
        if dur is None:
            continue
        try:
            d = float(dur)
        except (TypeError, ValueError):
            continue
        if s.get("codec_type") == "video" and v is None:
            v = d
        elif s.get("codec_type") == "audio" and a is None:
            a = d
    return v, a


def check_output(video_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Quality gates: file exists + duration bounds + preferred 40–55s warn."""
    gates = cfg.get("quality_gates") or {}
    script_cfg = cfg.get("script") or {}
    min_d = float(gates.get("min_duration_sec", 35))
    max_d = float(gates.get("max_duration_sec", 59))
    pref_min = float(
        gates.get("preferred_duration_sec_min")
        or script_cfg.get("target_duration_sec_min")
        or 40
    )
    pref_max = float(
        gates.get("preferred_duration_sec_max")
        or script_cfg.get("target_duration_sec_max")
        or 55
    )
    require_video = bool(gates.get("require_video", True))

    result: dict[str, Any] = {
        "ok": True,
        "path": str(video_path),
        "errors": [],
        "warnings": [],
        "duration_sec": None,
    }

    if require_video and not video_path.exists():
        result["ok"] = False
        result["errors"].append(f"Missing video: {video_path}")
        return result

    if video_path.stat().st_size < 10_000:
        result["ok"] = False
        result["errors"].append("Video file too small (<10KB)")

    try:
        duration = _ffprobe_duration(video_path)
        result["duration_sec"] = duration
        if duration < min_d:
            result["ok"] = False
            result["errors"].append(f"Duration {duration:.1f}s < min {min_d}s")
        if duration > max_d:
            result["ok"] = False
            result["errors"].append(f"Duration {duration:.1f}s > max {max_d}s")
        if result["ok"] and (duration < pref_min or duration > pref_max):
            warn = (
                f"Duration {duration:.1f}s outside preferred viral window "
                f"{pref_min:.0f}–{pref_max:.0f}s (still within hard cap)"
            )
            result["warnings"].append(warn)
            print(f"[quality_gates] WARN {warn}")
        v_dur, a_dur = _ffprobe_av_durations(video_path)
        result["video_stream_sec"] = v_dur
        result["audio_stream_sec"] = a_dur
        if v_dur is not None and a_dur is not None:
            drift = abs(v_dur - a_dur)
            # Frozen tail: video longer than audio (or vice versa) after narration
            if drift > 0.35:
                result["ok"] = False
                result["errors"].append(
                    f"A/V duration mismatch video={v_dur:.2f}s audio={a_dur:.2f}s "
                    f"drift={drift:.2f}s (freeze/hang risk)"
                )
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["errors"].append(f"ffprobe failed: {exc}")

    return result


def assert_ok(video_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    result = check_output(video_path, cfg)
    if not result["ok"]:
        raise SystemExit("[quality_gates] FAILED: " + "; ".join(result["errors"]))
    print(
        f"[quality_gates] OK duration={result['duration_sec']:.1f}s path={video_path.name}"
    )
    return result
