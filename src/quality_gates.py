from __future__ import annotations

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


def check_output(video_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Quality gates: file exists + duration bounds + preferred 30–45s warn."""
    gates = cfg.get("quality_gates") or {}
    script_cfg = cfg.get("script") or {}
    min_d = float(gates.get("min_duration_sec", 20))
    max_d = float(gates.get("max_duration_sec", 60))
    pref_min = float(
        gates.get("preferred_duration_sec_min")
        or script_cfg.get("target_duration_sec_min")
        or 30
    )
    pref_max = float(
        gates.get("preferred_duration_sec_max")
        or script_cfg.get("target_duration_sec_max")
        or 45
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
