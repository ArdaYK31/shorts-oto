"""Cinematic SFX stings for Shorts beats (hook / twist / payoff).

Prefer ElevenLabs Sound Generation API once, then cache under assets/sfx/
so we never re-bill the same whoosh/impact every episode. Falls back to
local FFmpeg-synthesized stings when the API key is missing or fails.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from config_loader import load_config

# Beat keys used by assemble + meta
BEAT_KEYS = ("hook", "twist", "payoff")

# Stable prompts — hash these for cache filenames (do not rotate casually)
DEFAULT_PROMPTS: dict[str, str] = {
    "hook": (
        "short cinematic whoosh transition, airy sweep, history documentary sting, "
        "0.8 seconds, no voice, no music melody"
    ),
    "twist": (
        "soft cinematic impact hit with subtle tension riser tail, dark curiosity, "
        "1.0 seconds, no voice, no melody"
    ),
    "payoff": (
        "punchy soft cinematic impact boom, documentary payoff sting, "
        "0.9 seconds, no voice, no melody"
    ),
}

DEFAULT_DURATIONS: dict[str, float] = {
    "hook": 0.85,
    "twist": 1.0,
    "payoff": 0.9,
}


def _api_key() -> str | None:
    for name in ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return None


def _sfx_cfg(cfg: dict) -> dict:
    audio = cfg.get("audio") or {}
    return dict(audio.get("sfx") or {})


def sfx_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    audio = cfg.get("audio") or {}
    if "sfx_enabled" in audio and not bool(audio.get("sfx_enabled")):
        return False
    return bool(_sfx_cfg(cfg).get("enabled", True))


def _sfx_dir(cfg: dict) -> Path:
    root = Path(cfg["_root"])
    rel = (_sfx_cfg(cfg).get("cache_dir") or "assets/sfx").strip()
    path = Path(rel)
    out = path if path.is_absolute() else root / path
    out.mkdir(parents=True, exist_ok=True)
    return out


def _cache_key(prompt: str, duration: float, model_id: str) -> str:
    raw = f"{model_id}|{duration:.2f}|{prompt.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _manifest_path(sfx_dir: Path) -> Path:
    return sfx_dir / "manifest.json"


def _load_manifest(sfx_dir: Path) -> dict[str, Any]:
    path = _manifest_path(sfx_dir)
    if not path.exists():
        return {"files": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"files": {}}


def _save_manifest(sfx_dir: Path, data: dict[str, Any]) -> None:
    _manifest_path(sfx_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _synthesize_local(out_mp3: Path, kind: str, duration: float) -> None:
    """Royalty-free synthetic stings via FFmpeg (no paid API)."""
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    d = max(0.45, min(float(duration), 2.5))
    fade_out_st = max(d - 0.32, 0.08)
    if kind == "hook":
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=44100:a=0.5",
            "-af", (
                "highpass=f=500,lowpass=f=6500,"
                f"afade=t=in:st=0:d=0.06,afade=t=out:st={fade_out_st:.2f}:d=0.3,volume=0.95"
            ),
            "-codec:a", "libmp3lame", "-q:a", "4", str(out_mp3),
        ]
    elif kind == "twist":
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=f=110:d={d}",
            "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=brown:a=0.3",
            "-filter_complex", (
                f"[0:a]volume=0.4[a];[1:a]volume=0.55[b];"
                f"[a][b]amix=inputs=2:duration=first,"
                f"afade=t=in:st=0:d=0.15,afade=t=out:st={fade_out_st:.2f}:d=0.35,volume=0.9"
            ),
            "-codec:a", "libmp3lame", "-q:a", "4", str(out_mp3),
        ]
    else:  # payoff
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=f=70:d={d}",
            "-f", "lavfi", "-i", f"anoisesrc=d={min(0.25, d)}:c=brown:a=0.6",
            "-filter_complex", (
                f"[0:a]afade=t=out:st={max(d - 0.5, 0.05):.2f}:d=0.5,volume=0.85[a];"
                f"[1:a]afade=t=out:st=0.12:d=0.12,volume=0.7,apad=whole_dur={d:.2f}[b];"
                f"[a][b]amix=inputs=2:duration=first,volume=1.0"
            ),
            "-t", f"{d:.2f}",
            "-codec:a", "libmp3lame", "-q:a", "4", str(out_mp3),
        ]
    subprocess.run(cmd, check=True, capture_output=True)


def _elevenlabs_generate(
    *,
    prompt: str,
    duration: float,
    model_id: str,
    prompt_influence: float,
    out_mp3: Path,
) -> None:
    import requests

    api_key = _api_key()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY missing")

    url = "https://api.elevenlabs.io/v1/sound-generation"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/octet-stream",
    }
    payload = {
        "text": prompt,
        "model_id": model_id,
        "duration_seconds": float(duration),
        "prompt_influence": float(prompt_influence),
    }
    resp = requests.post(
        url,
        params={"output_format": "mp3_44100_128"},
        headers=headers,
        json=payload,
        timeout=120,
    )
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        raise RuntimeError(f"ElevenLabs SFX HTTP {resp.status_code}: {detail}")
    if not resp.content:
        raise RuntimeError("ElevenLabs SFX returned empty body")
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    out_mp3.write_bytes(resp.content)


def ensure_sfx_library(cfg: dict | None = None) -> dict[str, Path]:
    """Ensure hook/twist/payoff MP3s exist (API once → cache, else local).

    Returns mapping beat → path. Safe to call every pipeline run.
    """
    cfg = cfg or load_config()
    if not sfx_enabled(cfg):
        return {}
    sfx = _sfx_cfg(cfg)

    sfx_dir = _sfx_dir(cfg)
    prompts = dict(DEFAULT_PROMPTS)
    prompts.update({k: str(v) for k, v in (sfx.get("prompts") or {}).items() if v})
    durations = dict(DEFAULT_DURATIONS)
    for k, v in (sfx.get("durations") or {}).items():
        try:
            durations[k] = float(v)
        except (TypeError, ValueError):
            pass

    model_id = str(sfx.get("model_id") or "eleven_text_to_sound_v2")
    influence = float(sfx.get("prompt_influence", 0.35))
    prefer_api = bool(sfx.get("prefer_elevenlabs", True))
    manifest = _load_manifest(sfx_dir)
    files: dict[str, Any] = dict(manifest.get("files") or {})
    resolved: dict[str, Path] = {}

    for beat in BEAT_KEYS:
        prompt = prompts.get(beat) or DEFAULT_PROMPTS[beat]
        dur = float(durations.get(beat) or DEFAULT_DURATIONS[beat])
        key = _cache_key(prompt, dur, model_id)
        stable_name = f"{beat}_{key}.mp3"
        alias = sfx_dir / f"{beat}.mp3"
        cached = sfx_dir / stable_name

        if cached.exists() and cached.stat().st_size > 500:
            if not alias.exists() or alias.stat().st_size < 500:
                try:
                    alias.write_bytes(cached.read_bytes())
                except OSError:
                    pass
            resolved[beat] = alias if alias.exists() else cached
            continue

        # Reuse committed/local alias — never re-bill the same sting
        if alias.exists() and alias.stat().st_size > 500:
            resolved[beat] = alias
            files.setdefault(
                beat,
                {
                    "alias": alias.name,
                    "source": "cached_alias",
                    "prompt": prompt,
                    "duration_seconds": dur,
                    "model_id": model_id,
                },
            )
            continue

        generated = False
        source = "local"
        if prefer_api and _api_key():
            try:
                print(f"[sfx] ElevenLabs generate beat={beat} dur={dur:.2f}s (one-time cache)")
                _elevenlabs_generate(
                    prompt=prompt,
                    duration=dur,
                    model_id=model_id,
                    prompt_influence=influence,
                    out_mp3=cached,
                )
                generated = True
                source = "elevenlabs"
            except Exception as exc:  # noqa: BLE001
                print(f"[sfx] ElevenLabs failed for {beat} ({exc}); local fallback")

        if not generated:
            print(f"[sfx] Local synthetic beat={beat}")
            _synthesize_local(cached, beat, dur)
            source = "local"

        if cached.exists():
            alias.write_bytes(cached.read_bytes())
            resolved[beat] = alias
            files[beat] = {
                "file": stable_name,
                "alias": alias.name,
                "prompt": prompt,
                "duration_seconds": dur,
                "model_id": model_id,
                "source": source,
                "cache_key": key,
            }
        elif alias.exists():
            resolved[beat] = alias

    manifest["files"] = files
    manifest["note"] = (
        "SFX cached once per prompt/model. Re-run only if prompts change. "
        "ElevenLabs Sound Generation is billed per generation — not per video."
    )
    _save_manifest(sfx_dir, manifest)
    return resolved


def resolve_sfx_times(
    duration: float,
    *,
    meta: dict[str, Any] | None = None,
    narration: str = "",
    cfg: dict | None = None,
) -> dict[str, float]:
    """Map hook/twist/payoff → start times (seconds).

    Prefer meta sfx_beats / claim_at / twist_at / payoff_at; else keyword /
    viral-structure fractions matched to Farzan-style Short pacing.
    """
    cfg = cfg or load_config()
    sfx = _sfx_cfg(cfg)
    duration = max(float(duration), 1.0)
    meta = meta or {}

    times: dict[str, float] = {}
    beats_meta = meta.get("sfx_beats") or meta.get("sfx") or {}
    if isinstance(beats_meta, dict):
        for k in BEAT_KEYS:
            if k in beats_meta:
                try:
                    times[k] = float(beats_meta[k])
                except (TypeError, ValueError):
                    pass
    for k, alt in (("hook", "claim_at"), ("twist", "twist_at"), ("payoff", "payoff_at")):
        if k not in times and alt in meta:
            try:
                times[k] = float(meta[alt])
            except (TypeError, ValueError):
                pass

    fracs = {
        "hook": float(sfx.get("hook_at_frac", 0.02)),
        "twist": float(sfx.get("twist_at_frac", 0.52)),
        "payoff": float(sfx.get("payoff_at_frac", 0.88)),
    }
    # Reference Short (kq7ByxGRBvs): whoosh/energy on open claim (~0–2.6s),
    # mid impact near sword/solve (~30s ≈ 52%), final punch on buried-alive (~57s ≈ 96%).
    text = narration or str(meta.get("narration") or meta.get("script") or "")
    if text and "twist" not in times:
        low = text.lower()
        # Prefer late contrast markers
        for pat in (
            r"\bin reality\b",
            r"\bbut\b",
            r"\bhowever\b",
            r"\binstead\b",
            r"\buntil\b",
        ):
            m = re.search(pat, low)
            if m:
                # Approximate time by character offset
                frac = m.start() / max(len(low), 1)
                if 0.25 <= frac <= 0.85:
                    times["twist"] = frac * duration
                    break
    if text and "payoff" not in times:
        # Last sentence ≈ payoff
        times["payoff"] = min(duration * 0.92, duration - 1.0)

    claim_end = meta.get("claim_end")
    if "hook" not in times:
        if claim_end is not None:
            try:
                times["hook"] = max(0.05, min(float(claim_end) * 0.15, 0.35))
            except (TypeError, ValueError):
                times["hook"] = duration * fracs["hook"]
        else:
            times["hook"] = duration * fracs["hook"]

    if "twist" not in times:
        times["twist"] = duration * fracs["twist"]
    if "payoff" not in times:
        times["payoff"] = duration * fracs["payoff"]

    # Clamp + keep ordering hook < twist < payoff
    times["hook"] = max(0.0, min(times["hook"], duration - 0.6))
    times["twist"] = max(times["hook"] + 1.5, min(times["twist"], duration - 1.2))
    times["payoff"] = max(times["twist"] + 1.5, min(times["payoff"], duration - 0.5))
    return times


def sfx_volume(cfg: dict | None = None) -> float:
    cfg = cfg or load_config()
    return max(0.05, min(float(_sfx_cfg(cfg).get("volume", 0.2)), 0.35))


if __name__ == "__main__":
    paths = ensure_sfx_library()
    for k, p in paths.items():
        print(f"{k}: {p} ({p.stat().st_size if p.exists() else 0} bytes)")
