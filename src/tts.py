from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# espeak-ng breaks on non-ASCII Windows user paths (e.g. Turkish characters).
# Prefer a fixed ASCII data dir if present.
_ASCII_ESPEAK = Path(r"C:\espeak-ng-data")
if _ASCII_ESPEAK.exists() and (_ASCII_ESPEAK / "phontab").exists():
    os.environ["ESPEAK_DATA_PATH"] = str(_ASCII_ESPEAK)

import numpy as np
import soundfile as sf

from config_loader import load_config


def _elevenlabs_api_key() -> str | None:
    for name in ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return None


def _synthesize_kokoro(text: str, out_wav: Path, voice: str, speed: float, lang: str) -> None:
    from kokoro import KPipeline

    lang_code = "a"
    if lang.lower().startswith("en-gb") or lang.lower().startswith("b") or voice.startswith("bm_"):
        lang_code = "b"

    pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
    chunks: list[np.ndarray] = []
    sample_rate = 24000
    for _gs, _ps, audio in pipeline(text, voice=voice, speed=speed):
        if audio is None:
            continue
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr.reshape(-1)
        chunks.append(arr)
    if not chunks:
        raise RuntimeError("Kokoro produced no audio")
    audio_out = np.concatenate(chunks)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), audio_out, sample_rate)


def _synthesize_kokoro_onnx(
    text: str, out_wav: Path, voice: str, model: str, voices: str, speed: float = 1.0
) -> None:
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(model, voices)
    samples, sample_rate = kokoro.create(text, voice=voice, speed=float(speed), lang="en_us")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), samples, sample_rate)


def _synthesize_elevenlabs(
    text: str,
    out_wav: Path,
    *,
    voice_id: str,
    model_id: str,
    stability: float,
    similarity_boost: float,
    style: float,
    use_speaker_boost: bool,
    speed: float,
) -> None:
    """ElevenLabs TTS → mono PCM WAV (24 kHz). Needs ELEVENLABS_API_KEY / ELEVEN_API_KEY."""
    import requests

    api_key = _elevenlabs_api_key()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY / ELEVEN_API_KEY missing")
    if not voice_id or voice_id.startswith("REPLACE"):
        raise RuntimeError("tts.elevenlabs.voice_id is missing or still a placeholder")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/octet-stream",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": float(stability),
            "similarity_boost": float(similarity_boost),
            "style": float(style),
            "use_speaker_boost": bool(use_speaker_boost),
            "speed": float(speed),
        },
    }
    # pcm_24000 = raw s16le mono @ 24 kHz — matches Kokoro sample rate for post-FX
    resp = requests.post(
        url,
        params={"output_format": "pcm_24000"},
        headers=headers,
        json=payload,
        timeout=180,
    )
    if resp.status_code >= 400:
        detail = (resp.text or "")[:400]
        raise RuntimeError(f"ElevenLabs HTTP {resp.status_code}: {detail}")
    pcm = np.frombuffer(resp.content, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError("ElevenLabs returned empty audio")
    samples = pcm.astype(np.float32) / 32768.0
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), samples, 24000)


def _narration_post_filter() -> str:
    """ChronoShorts-tuned: trim dead air (~100ms pads), clear US doc EQ, loudnorm."""
    # Strip leading/trailing silence, then restore ~100ms pads for clean edits
    return (
        "silenceremove=start_periods=1:start_silence=0.04:start_threshold=-38dB:"
        "detection=peak,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0.04:start_threshold=-38dB:"
        "detection=peak,"
        "apad=pad_dur=0.10,"
        "areverse,"
        "apad=pad_dur=0.10,"
        "acompressor=threshold=-18dB:ratio=3.2:attack=6:release=100:makeup=2.5:knee=5,"
        "lowshelf=f=140:width_type=q:width=0.7:g=2.5,"
        "equalizer=f=3200:width_type=h:width=1600:g=3.2,"
        "highshelf=f=7500:width_type=q:width=0.7:g=-4,"
        "equalizer=f=90:width_type=h:width=60:g=-1.5,"
        "loudnorm=I=-16:TP=-1.5:LRA=9"
    )


def _post_process_narration(raw_wav: Path, out_mp3: Path) -> None:
    """FFmpeg post on raw narration WAV → fuller narration MP3."""
    processed_wav = raw_wav.with_name(raw_wav.stem + ".post.wav")
    filt = _narration_post_filter()
    cmd_wav = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_wav),
        "-af",
        filt,
        "-ar",
        "48000",
        "-ac",
        "1",
        str(processed_wav),
    ]
    subprocess.run(cmd_wav, check=True, capture_output=True)
    cmd_mp3 = [
        "ffmpeg",
        "-y",
        "-i",
        str(processed_wav),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    subprocess.run(cmd_mp3, check=True, capture_output=True)
    try:
        processed_wav.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"[tts] Post-FX: dead-air trim + ChronoShorts EQ + loudnorm")


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


def _atempo_chain(speedup: float) -> str:
    """Build atempo filter chain (each stage must be within 0.5–2.0)."""
    parts: list[str] = []
    remaining = max(speedup, 1.0)
    while remaining > 2.0 + 1e-9:
        parts.append("atempo=2.0")
        remaining /= 2.0
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def enforce_max_duration(mp3_path: Path, max_sec: float) -> float:
    """Speed up narration in-place so duration <= max_sec (Shorts hard cap)."""
    duration = _ffprobe_duration(mp3_path)
    if duration <= max_sec + 0.05:
        return duration
    speedup = duration / max_sec
    filt = _atempo_chain(speedup)
    tmp = mp3_path.with_suffix(".fit.mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(mp3_path),
        "-af",
        filt,
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(tmp),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    tmp.replace(mp3_path)
    fitted = _ffprobe_duration(mp3_path)
    print(
        f"[tts] Duration fit: {duration:.1f}s → {fitted:.1f}s "
        f"(atempo chain for Shorts max {max_sec:.0f}s)"
    )
    return fitted


def _run_kokoro(text: str, wav_path: Path, voice: str, speed: float, tts_cfg: dict) -> None:
    print(
        f"[tts] Kokoro LOCKED voice={voice} speed={speed} lang=en-us "
        f"ESPEAK_DATA_PATH={os.environ.get('ESPEAK_DATA_PATH')}"
    )
    try:
        _synthesize_kokoro(
            text,
            wav_path,
            voice=voice,
            speed=speed,
            lang=str(tts_cfg.get("lang", "en-us")),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[tts] Kokoro failed ({exc}); trying kokoro_onnx…")
        model = tts_cfg.get("kokoro_onnx_model") or r"C:\kokoro-models\kokoro-v1.0.onnx"
        voices = tts_cfg.get("kokoro_onnx_voices") or r"C:\kokoro-models\voices-v1.0.bin"
        _synthesize_kokoro_onnx(
            text,
            wav_path,
            voice=voice,
            model=model,
            voices=voices,
            speed=speed,
        )


def _run_kokoro_onnx(text: str, wav_path: Path, voice: str, speed: float, tts_cfg: dict) -> None:
    print(f"[tts] Using kokoro-onnx LOCKED voice={voice} speed={speed}")
    model = tts_cfg.get("kokoro_onnx_model") or r"C:\kokoro-models\kokoro-v1.0.onnx"
    voices = tts_cfg.get("kokoro_onnx_voices") or r"C:\kokoro-models\voices-v1.0.bin"
    _synthesize_kokoro_onnx(
        text,
        wav_path,
        voice=voice,
        model=model,
        voices=voices,
        speed=speed,
    )


def _run_fallback(text: str, wav_path: Path, voice: str, speed: float, tts_cfg: dict) -> None:
    fallback = str(tts_cfg.get("fallback") or "kokoro").strip().lower()
    print(f"[tts] Falling back to {fallback}")
    if fallback == "kokoro_onnx":
        _run_kokoro_onnx(text, wav_path, voice, speed, tts_cfg)
    else:
        _run_kokoro(text, wav_path, voice, speed, tts_cfg)


def synthesize(script_path: Path | None = None) -> Path:
    cfg = load_config()
    scripts_dir = cfg["paths_resolved"]["scripts"]
    audio_dir = cfg["paths_resolved"]["audio"]
    audio_dir.mkdir(parents=True, exist_ok=True)

    if script_path is None:
        candidates = sorted(scripts_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise SystemExit("No script .txt found. Run generate_script first.")
        script_path = candidates[0]

    text = script_path.read_text(encoding="utf-8").strip()
    text = re.sub(r"\s+", " ", text)
    wav_path = audio_dir / f"{script_path.stem}.wav"
    out_path = audio_dir / f"{script_path.stem}.mp3"
    provider = str(cfg["tts"]["provider"]).strip().lower()
    tts_cfg = cfg.get("tts") or {}
    # Brand voice lock — ChronoShorts US narrator (am_adam) for Kokoro paths only
    brand_voice = "am_adam"
    voice = str(tts_cfg.get("voice") or brand_voice)
    if bool(tts_cfg.get("voice_locked", True)):
        if voice != brand_voice:
            print(
                f"[tts] voice_locked=true — forcing {brand_voice} "
                f"(config had {voice!r})"
            )
            voice = brand_voice
        onnx_v = str(tts_cfg.get("kokoro_onnx_voice") or voice)
        if onnx_v != brand_voice:
            print(f"[tts] voice_locked=true — onnx voice forced to {brand_voice}")
    if not voice.startswith("am_"):
        print(f"[tts] WARN non-US voice {voice!r}; ChronoShorts expects am_*")
    speed = float(tts_cfg.get("speed", 1.05))

    if provider == "elevenlabs":
        el = tts_cfg.get("elevenlabs") or {}
        api_key = _elevenlabs_api_key()
        model_id = str(el.get("model_id") or "eleven_multilingual_v2")
        voice_id = str(el.get("voice_id") or "").strip()
        el_speed = float(el.get("speed", speed))
        if not api_key:
            print(
                "[tts] ELEVENLABS_API_KEY missing — "
                "falling back to Kokoro (set GitHub secret, never paste key in chat)"
            )
            _run_fallback(text, wav_path, voice, speed, tts_cfg)
        else:
            print(
                f"[tts] ElevenLabs model={model_id} voice_id={voice_id[:8]}… "
                f"stability={el.get('stability', 0.45)} speed={el_speed}"
            )
            try:
                _synthesize_elevenlabs(
                    text,
                    wav_path,
                    voice_id=voice_id,
                    model_id=model_id,
                    stability=float(el.get("stability", 0.45)),
                    similarity_boost=float(el.get("similarity_boost", 0.75)),
                    style=float(el.get("style", 0.15)),
                    use_speaker_boost=bool(el.get("use_speaker_boost", True)),
                    speed=el_speed,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[tts] ElevenLabs failed ({exc}); falling back…")
                _run_fallback(text, wav_path, voice, speed, tts_cfg)
    elif provider == "kokoro":
        _run_kokoro(text, wav_path, voice, speed, tts_cfg)
    elif provider == "kokoro_onnx":
        _run_kokoro_onnx(text, wav_path, voice, speed, tts_cfg)
    else:
        raise SystemExit(
            f"Unknown/unsupported tts.provider: {provider}. "
            "Use elevenlabs, kokoro, or kokoro_onnx."
        )

    _post_process_narration(wav_path, out_path)
    project = cfg.get("project") or {}
    gates = cfg.get("quality_gates") or {}
    max_sec = float(
        project.get("max_duration_sec")
        or gates.get("max_duration_sec")
        or 58
    )
    # Leave a small cushion so assemble/xfade + gate (60s) never fail schedule uploads.
    hard_max = min(max_sec, float(gates.get("max_duration_sec", 60)) - 1.0)
    hard_max = max(hard_max, 20.0)
    enforce_max_duration(out_path, hard_max)
    print(f"[tts] Wrote {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--script", type=Path, default=None)
    args = p.parse_args()
    synthesize(args.script)
