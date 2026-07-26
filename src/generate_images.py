from __future__ import annotations

"""ChronoShorts-style AI still generation (local Diffusers and/or free Pollinations)."""

import hashlib
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from PIL import Image

from config_loader import load_config

_STYLE_CACHE: str | None = None

SCENE_BEATS: list[str] = [
    "dramatic hero portrait, medium shot, intense expression",
    "wide establishing shot, epic environment, atmospheric depth",
    "character in action, storytelling moment, dynamic pose",
    "intimate interior scene, lantern or window light, chiaroscuro",
    "crowd or army context in background, main figure in focus",
    "symbolic object and figure, cinematic still, rich textures",
    "low-angle heroic framing, monumental architecture",
    "quiet contemplative moment before history changes",
    "aftermath or turning-point scene, emotional gravity",
    "close environmental detail with period props, cinematic grade",
    "journey or travel scene through period landscape",
    "final iconic tableau, powerful silhouette or stance",
]


def _load_style_prefix(cfg: dict[str, Any]) -> str:
    global _STYLE_CACHE
    if _STYLE_CACHE is not None:
        return _STYLE_CACHE
    root = cfg["_root"]
    path = root / cfg["media"].get("style_prompt_file", "prompts/image_style.txt")
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    # Use lines under STYLE PREFIX until blank/NEGATIVE
    lines: list[str] = []
    capture = False
    for line in raw.splitlines():
        if line.strip().upper().startswith("STYLE PREFIX"):
            capture = True
            continue
        if capture and line.strip().upper().startswith("NEGATIVE"):
            break
        if capture and line.strip():
            lines.append(line.strip())
    _STYLE_CACHE = " ".join(lines) if lines else (
        "cinematic historical illustration, semi-realistic painterly digital art, "
        "dramatic cinematic lighting, muted earthy color grading"
    )
    return _STYLE_CACHE


def _load_negative(cfg: dict[str, Any]) -> str:
    root = cfg["_root"]
    path = root / cfg["media"].get("style_prompt_file", "prompts/image_style.txt")
    if not path.exists():
        return "text, watermark, logo, anime, blurry, lowres"
    raw = path.read_text(encoding="utf-8")
    lines: list[str] = []
    capture = False
    for line in raw.splitlines():
        if line.strip().upper().startswith("NEGATIVE"):
            capture = True
            continue
        if capture and line.strip().upper().startswith("SCENE"):
            break
        if capture and line.strip():
            lines.append(line.strip())
    return ", ".join(lines) if lines else "text, watermark, logo, anime"


def _safe_stem(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name)[:80]


def build_scene_prompts(meta: dict[str, Any], count: int, cfg: dict[str, Any]) -> list[str]:
    style = _load_style_prefix(cfg)
    title = (meta.get("title") or meta.get("id") or "historical figure").strip()
    keywords = [str(k) for k in (meta.get("keywords") or [])][:5]
    kw = ", ".join(keywords)
    topic_bit = f"subject: {title}"
    if kw:
        topic_bit += f", themes: {kw}"
    prompts: list[str] = []
    for i in range(count):
        beat = SCENE_BEATS[i % len(SCENE_BEATS)]
        prompts.append(f"{style}. {topic_bit}. Scene: {beat}.")
    return prompts


def _session(ua: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept": "image/*,*/*;q=0.8"})
    return s


def generate_via_pollinations(
    prompts: list[str],
    dest_dir: Path,
    stem: str,
    session: requests.Session,
    width: int = 768,
    height: int = 1344,
) -> list[Path]:
    """Zero-cost HTTP image gen (no API key)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for i, prompt in enumerate(prompts):
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt[:900])}"
            f"?width={width}&height={height}&nologo=true&enhance=true"
            f"&seed={int(hashlib.md5(f'{stem}-{i}'.encode()).hexdigest()[:8], 16) % 10_000_000}"
        )
        dest = dest_dir / f"{stem}_ai_{i:02d}.jpg"
        print(f"[ai] Pollinations {i+1}/{len(prompts)}")
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with session.get(url, stream=True, timeout=180) as r:
                    r.raise_for_status()
                    with dest.open("wb") as f:
                        for chunk in r.iter_content(1024 * 256):
                            if chunk:
                                f.write(chunk)
                with Image.open(dest) as im:
                    im.verify()
                out.append(dest)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(2.0 * (attempt + 1))
        if last_err is not None:
            print(f"[ai] Pollinations failed scene {i}: {last_err}")
        time.sleep(0.4)
    return out


def generate_via_diffusers(
    prompts: list[str],
    dest_dir: Path,
    stem: str,
    negative: str,
    model_id: str,
    steps: int,
    guidance: float,
) -> list[Path]:
    """Local SD-Turbo / Diffusers path (GPU preferred)."""
    import torch
    from diffusers import AutoPipelineForText2Image

    dest_dir.mkdir(parents=True, exist_ok=True)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[ai] Diffusers model={model_id} device={device}")
    pipe = AutoPipelineForText2Image.from_pretrained(model_id, torch_dtype=dtype)
    pipe = pipe.to(device)
    if hasattr(pipe, "enable_attention_slicing"):
        pipe.enable_attention_slicing()
    if hasattr(pipe, "enable_vae_slicing"):
        pipe.enable_vae_slicing()

    out: list[Path] = []
    gen = torch.Generator(device=device)
    for i, prompt in enumerate(prompts):
        seed = int(hashlib.md5(f"{stem}-{i}".encode()).hexdigest()[:8], 16) % (2**31 - 1)
        gen.manual_seed(seed)
        print(f"[ai] Local render {i+1}/{len(prompts)}")
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "generator": gen,
            "height": 768,
            "width": 448,
        }
        try:
            image = pipe(**kwargs).images[0]
        except Exception:
            # Some turbo pipelines dislike custom H/W — retry square then crop later
            kwargs.pop("height", None)
            kwargs.pop("width", None)
            image = pipe(**kwargs).images[0]
        dest = dest_dir / f"{stem}_ai_{i:02d}.png"
        image.save(dest)
        out.append(dest)
    return out


def generate_ai_stills(meta: dict[str, Any], need: int) -> list[Path]:
    """
    Returns raw AI image paths (not yet cover-fitted).
    Raises RuntimeError if nothing usable was produced.
    """
    cfg = load_config()
    media = cfg.get("media") or {}
    root = cfg["_root"]
    raw_dir = cfg["paths_resolved"]["media_raw"]
    stem = _safe_stem(str(meta.get("id") or "scene"))
    prompts = build_scene_prompts(meta, need, cfg)
    negative = _load_negative(cfg)
    ua = media.get("user_agent", "yt-history-shorts/0.3")
    provider = str(media.get("provider", "ai_local")).lower()
    session = _session(ua)

    paths: list[Path] = []

    if provider == "ai_api":
        backend = str((media.get("ai_api") or {}).get("backend", "pollinations")).lower()
        if backend in {"pollinations", "free"}:
            paths = generate_via_pollinations(prompts, raw_dir, stem, session)
        else:
            raise RuntimeError(
                f"ai_api.backend={backend} not configured (use pollinations for $0, "
                "or add a paid backend later)."
            )
        if len(paths) < 4:
            raise RuntimeError(f"ai_api produced too few images: {len(paths)}")
        return paths[:need]

    # ai_local (default): try Diffusers, optional free HTTP fallback
    local_cfg = media.get("ai_local") or {}
    model_id = str(local_cfg.get("model", "stabilityai/sd-turbo"))
    steps = int(local_cfg.get("steps", 4))
    guidance = float(local_cfg.get("guidance", 0.0))
    allow_fallback = bool(local_cfg.get("allow_free_api_fallback", True))

    try:
        paths = generate_via_diffusers(
            prompts, raw_dir, stem, negative, model_id, steps, guidance
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ai] Local Diffusers unavailable ({exc})")
        if allow_fallback:
            print("[ai] Falling back to free Pollinations API (still $0, AI style)")
            paths = generate_via_pollinations(prompts, raw_dir, stem, session)
        else:
            raise RuntimeError(f"ai_local failed and free fallback disabled: {exc}") from exc

    if len(paths) < 4:
        raise RuntimeError(f"AI generation produced too few images: {len(paths)}")
    return paths[:need]


def process_ai_to_vertical(raw_paths: list[Path], stem: str, need: int) -> list[Path]:
    # Lazy import avoids circular dependency with fetch_media
    from fetch_media import fit_cover_jpg

    cfg = load_config()
    proc_dir = cfg["paths_resolved"]["media_processed"]
    w, h = int(cfg["project"]["width"]), int(cfg["project"]["height"])
    proc_dir.mkdir(parents=True, exist_ok=True)
    for old in proc_dir.glob(f"{stem}_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    processed: list[Path] = []
    for i, raw in enumerate(raw_paths):
        if len(processed) >= need:
            break
        out = proc_dir / f"{stem}_{len(processed):02d}.jpg"
        bias = 0.35 + 0.3 * ((i * 0.37) % 1.0)
        try:
            fit_cover_jpg(raw, out, w, h, bias=bias)
            processed.append(out)
        except OSError as exc:
            print(f"[ai] SKIP unreadable {raw.name}: {exc}")
    if len(processed) < need and processed:
        # Cycle-fill like Wikimedia path
        guard = 0
        while len(processed) < need and guard < need * 3:
            guard += 1
            i = len(processed)
            src = raw_paths[i % len(raw_paths)]
            out = proc_dir / f"{stem}_{i:02d}.jpg"
            bias = 0.15 + 0.7 * ((i * 0.37) % 1.0)
            try:
                fit_cover_jpg(src, out, w, h, bias=bias)
                processed.append(out)
            except OSError:
                continue
    return processed[:need]


if __name__ == "__main__":
    import json
    import sys

    cfg = load_config()
    scripts = cfg["paths_resolved"]["scripts"]
    metas = sorted(scripts.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not metas:
        raise SystemExit("No meta.json")
    meta = json.loads(metas[0].read_text(encoding="utf-8"))
    need = int(cfg["media"]["image_count"])
    raws = generate_ai_stills(meta, need)
    done = process_ai_to_vertical(raws, meta["id"], need)
    print(f"[ai] Wrote {len(done)} processed stills")
    sys.exit(0 if done else 1)
