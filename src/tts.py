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


def _narration_post_filter() -> str:
    """ChronoShorts-tuned: clear US doc narrator — mild body, strong presence, de-ess, loudnorm."""
    return (
        "acompressor=threshold=-18dB:ratio=3.2:attack=6:release=100:makeup=2.5:knee=5,"
        "lowshelf=f=140:width_type=q:width=0.7:g=2.5,"
        "equalizer=f=3200:width_type=h:width=1600:g=3.2,"
        "highshelf=f=7500:width_type=q:width=0.7:g=-4,"
        "equalizer=f=90:width_type=h:width=60:g=-1.5,"
        "loudnorm=I=-16:TP=-1.5:LRA=9"
    )


def _post_process_narration(raw_wav: Path, out_mp3: Path) -> None:
    """FFmpeg post on raw Kokoro WAV → fuller narration MP3."""
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
    print(f"[tts] Post-FX: ChronoShorts EQ (compress + mild lowshelf + presence 3.2k + de-ess + loudnorm)")


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
    provider = cfg["tts"]["provider"]
    voice = cfg["tts"].get("voice", "am_adam")
    speed = float(cfg["tts"].get("speed", 1.05))

    if provider == "kokoro":
        print(f"[tts] Kokoro voice={voice} speed={speed} ESPEAK_DATA_PATH={os.environ.get('ESPEAK_DATA_PATH')}")
        try:
            _synthesize_kokoro(
                text,
                wav_path,
                voice=voice,
                speed=speed,
                lang=str(cfg["tts"].get("lang", "en-us")),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[tts] Kokoro failed ({exc}); trying kokoro_onnx…")
            model = cfg["tts"].get("kokoro_onnx_model") or r"C:\kokoro-models\kokoro-v1.0.onnx"
            voices = cfg["tts"].get("kokoro_onnx_voices") or r"C:\kokoro-models\voices-v1.0.bin"
            _synthesize_kokoro_onnx(
                text,
                wav_path,
                voice=cfg["tts"].get("kokoro_onnx_voice") or voice,
                model=model,
                voices=voices,
                speed=speed,
            )
    elif provider == "kokoro_onnx":
        print(f"[tts] Using kokoro-onnx voice={voice} speed={speed}")
        model = cfg["tts"].get("kokoro_onnx_model") or r"C:\kokoro-models\kokoro-v1.0.onnx"
        voices = cfg["tts"].get("kokoro_onnx_voices") or r"C:\kokoro-models\voices-v1.0.bin"
        _synthesize_kokoro_onnx(
            text,
            wav_path,
            voice=cfg["tts"].get("kokoro_onnx_voice") or voice,
            model=model,
            voices=voices,
            speed=speed,
        )
    else:
        raise SystemExit(
            f"Unknown/unsupported tts.provider: {provider}. Use kokoro or kokoro_onnx."
        )

    _post_process_narration(wav_path, out_path)
    print(f"[tts] Wrote {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--script", type=Path, default=None)
    args = p.parse_args()
    synthesize(args.script)
