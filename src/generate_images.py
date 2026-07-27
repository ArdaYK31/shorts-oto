from __future__ import annotations

"""ChronoShorts-style AI stills: fal.ai Flux (paid, budgeted) + Pollinations/local fallback."""

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from PIL import Image

from budget import can_afford, record_images, remaining_usd
from config_loader import load_config

_STYLE_CACHE: str | None = None
_HOOK_CACHE: str | None = None

# Positive anti-trash constraints (Flux ignores negatives — keep in prompt body).
_ANTI_HAND_GAZE = (
    "hands secondary never focal, no palm gazing, no examining own hands, "
    "no awkward hand close-ups, eyes looking into the scene or at distant action"
)

# Narrative-linked composition templates keyed to viral structure beats.
# Each entry: (role_label, composition_directive)
SCENE_BEATS: list[tuple[str, str]] = [
    (
        "hook",
        "wide establishing hero tableau visualizing the shock claim, "
        "monumental scale or decisive contrast, environmental storytelling",
    ),
    (
        "evidence",
        "wide establishing period environment with maps documents architecture "
        "or dated landmarks proving the claim, atmospheric depth",
    ),
    (
        "evidence",
        "cause-and-effect beat: period props letters seals coins weapons or "
        "architecture that matches the named proof, medium-wide framing",
    ),
    (
        "relevance",
        "crowd silhouette army procession or public square showing stakes for "
        "ordinary people, main subject in context not isolated palm-gazing",
    ),
    (
        "evidence",
        "interior study archive throne room or war room with period documents "
        "and lantern Rembrandt light, objects carry the story",
    ),
    (
        "twist",
        "turning-point tableau: visual paradox or knife-turn of the story, "
        "dynamic medium-wide action or silhouette confrontation",
    ),
    (
        "twist",
        "low-angle monumental architecture or battlefield aftermath that "
        "escalates the irony, powerful environmental scale",
    ),
    (
        "relevance",
        "journey or travel through period landscape linking places named "
        "in the narration, continuity of era and costume",
    ),
    (
        "payoff",
        "aftermath or consequence scene with emotional gravity, wide or "
        "silhouette framing, story resolved visually",
    ),
    (
        "payoff",
        "close environmental detail of a decisive period object only "
        "(seal map broken chain crown document) — no hand close-ups",
    ),
    (
        "payoff",
        "final iconic silhouette or stance against epic skyline, loop-bait "
        "energy, strong composition tied to the claim",
    ),
    (
        "evidence",
        "crowd or army context behind a clear central figure in period dress, "
        "faces looking outward, documentary still",
    ),
]


def _load_style_prefix(cfg: dict[str, Any]) -> str:
    global _STYLE_CACHE
    if _STYLE_CACHE is not None:
        return _STYLE_CACHE
    root = cfg["_root"]
    path = root / cfg["media"].get("style_prompt_file", "prompts/image_style.txt")
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    lines: list[str] = []
    capture = False
    for line in raw.splitlines():
        upper = line.strip().upper()
        if upper.startswith("STYLE PREFIX"):
            capture = True
            continue
        if capture and (
            upper.startswith("NEGATIVE")
            or upper.startswith("HOOK")
            or upper.startswith("SCENE")
        ):
            break
        if capture and line.strip():
            lines.append(line.strip())
    _STYLE_CACHE = " ".join(lines) if lines else (
        "semi-realistic painterly digital illustration, cinematic historical documentary still, "
        "35mm Rembrandt Portra, shallow depth of field, no text in image, intact hands"
    )
    return _STYLE_CACHE


def _load_hook_prefix(cfg: dict[str, Any]) -> str:
    """Optional first-frame composition boost from image_style.txt HOOK section."""
    global _HOOK_CACHE
    if _HOOK_CACHE is not None:
        return _HOOK_CACHE
    root = cfg["_root"]
    path = root / cfg["media"].get("style_prompt_file", "prompts/image_style.txt")
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    lines: list[str] = []
    capture = False
    for line in raw.splitlines():
        upper = line.strip().upper()
        if upper.startswith("HOOK"):
            capture = True
            continue
        if capture and (upper.startswith("SCENE") or upper.startswith("NEGATIVE")):
            break
        if capture and line.strip():
            lines.append(line.strip())
    _HOOK_CACHE = " ".join(lines)
    return _HOOK_CACHE


def _load_negative(cfg: dict[str, Any]) -> str:
    """Legacy NEGATIVE block (Flux Schnell often ignores it — constraints live in STYLE PREFIX)."""
    root = cfg["_root"]
    path = root / cfg["media"].get("style_prompt_file", "prompts/image_style.txt")
    if not path.exists():
        return "text, watermark, logo, anime, blurry, lowres, deformed hands"
    raw = path.read_text(encoding="utf-8")
    lines: list[str] = []
    capture = False
    for line in raw.splitlines():
        upper = line.strip().upper()
        if upper.startswith("NEGATIVE"):
            capture = True
            continue
        if capture and (upper.startswith("SCENE") or upper.startswith("HOOK")):
            break
        if capture and line.strip():
            lines.append(line.strip())
    return ", ".join(lines) if lines else (
        "text, watermark, logo, anime, blurry, lowres, deformed hands"
    )


def _safe_stem(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name)[:80]


def _topic_seed(stem: str) -> int:
    """Deterministic per-topic seed (free; no API cost). Scene i uses topic_seed + i."""
    return int(hashlib.md5(stem.encode()).hexdigest()[:8], 16) % 10_000_000


def _split_narration_beats(text: str, want: int) -> list[str]:
    """Split narration into ~want beat snippets for image prompt grounding."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [cleaned[:180]]
    if len(parts) >= want:
        return [p[:180] for p in parts[:want]]
    # Stretch fewer sentences across want slots
    out: list[str] = []
    for i in range(want):
        out.append(parts[min(i, len(parts) - 1)][:180])
    return out


def _load_narration_for_meta(meta: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Prefer on-disk script so image beats track spoken narration."""
    scripts = cfg.get("paths_resolved", {}).get("scripts")
    stem = str(meta.get("id") or "").strip()
    if scripts and stem:
        path = Path(scripts) / f"{stem}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return str(meta.get("narration") or meta.get("script") or "").strip()


def build_scene_prompts(meta: dict[str, Any], count: int, cfg: dict[str, Any]) -> list[str]:
    style = _load_style_prefix(cfg)
    hook_prefix = _load_hook_prefix(cfg)
    title = (meta.get("title") or meta.get("id") or "historical figure").strip()
    claim = (meta.get("claim") or meta.get("hook") or title).strip()
    topic = (meta.get("topic") or title).strip()
    keywords = [str(k) for k in (meta.get("keywords") or [])][:5]
    kw = ", ".join(keywords)
    continuity = (
        f"same era and subject continuity across episode, subject: {title}, "
        f"topic: {topic}"
    )
    if kw:
        continuity += f", themes: {kw}"

    narration = _load_narration_for_meta(meta, cfg)
    narr_beats = _split_narration_beats(narration, count)
    prompts: list[str] = []
    for i in range(count):
        role, composition = SCENE_BEATS[i % len(SCENE_BEATS)]
        beat_text = narr_beats[i] if i < len(narr_beats) else claim
        if i == 0:
            beat_text = claim or beat_text
        narrative = f"script beat ({role}): {beat_text}"
        parts = [style, continuity, narrative, f"Scene: {composition}", _ANTI_HAND_GAZE]
        if i == 0 and hook_prefix:
            parts.insert(1, hook_prefix)
            parts.append(f"visualizes claim: {claim}")
        prompts.append(". ".join(p.rstrip(".") for p in parts if p) + ".")
    return prompts


def _session(ua: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept": "image/*,*/*;q=0.8"})
    return s


def _fal_api_key() -> str | None:
    for name in ("FAL_KEY", "IMAGE_API_KEY", "FAL_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return None


def generate_via_fal(
    prompts: list[str],
    dest_dir: Path,
    stem: str,
    session: requests.Session,
    *,
    endpoint: str = "fal-ai/flux/schnell",
    width: int = 768,
    height: int = 1344,
    steps: int = 4,
    negative: str = "",
) -> list[Path]:
    """Paid fal.ai Flux Schnell (~$0.003/MP). Needs FAL_KEY / IMAGE_API_KEY."""
    key = _fal_api_key()
    if not key:
        raise RuntimeError("FAL_KEY / IMAGE_API_KEY missing")

    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://fal.run/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    out: list[Path] = []
    base_seed = _topic_seed(stem)
    for i, prompt in enumerate(prompts):
        seed = (base_seed + i * 997) % 10_000_000
        body: dict[str, Any] = {
            "prompt": prompt[:2000],
            "image_size": {"width": int(width), "height": int(height)},
            "num_inference_steps": int(steps),
            "enable_safety_checker": True,
            "num_images": 1,
            "seed": seed,
        }
        if negative:
            body["negative_prompt"] = negative[:800]
        dest = dest_dir / f"{stem}_ai_{i:02d}.jpg"
        print(f"[ai] fal Flux {i+1}/{len(prompts)} ({endpoint})")
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                r = session.post(url, headers=headers, json=body, timeout=180)
                if r.status_code >= 400:
                    raise RuntimeError(f"fal HTTP {r.status_code}: {r.text[:400]}")
                data = r.json()
                images = data.get("images") or []
                if not images:
                    raise RuntimeError(f"fal empty images: {str(data)[:300]}")
                img_url = images[0].get("url") if isinstance(images[0], dict) else None
                if not img_url:
                    raise RuntimeError("fal response missing image url")
                with session.get(img_url, stream=True, timeout=120) as img_r:
                    img_r.raise_for_status()
                    with dest.open("wb") as f:
                        for chunk in img_r.iter_content(1024 * 256):
                            if chunk:
                                f.write(chunk)
                with Image.open(dest) as im:
                    im.verify()
                # Re-encode as JPEG if PNG
                with Image.open(dest) as im:
                    rgb = im.convert("RGB")
                    rgb.save(dest, format="JPEG", quality=92)
                out.append(dest)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        if last_err is not None:
            print(f"[ai] fal failed scene {i}: {last_err}")
        time.sleep(0.15)
    return out


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
    base_seed = _topic_seed(stem)
    for i, prompt in enumerate(prompts):
        seed = (base_seed + i * 997) % 10_000_000
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt[:900])}"
            f"?width={width}&height={height}&nologo=true&enhance=true"
            f"&seed={seed}"
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
    base_seed = _topic_seed(stem)
    for i, prompt in enumerate(prompts):
        seed = (base_seed + i * 997) % (2**31 - 1)
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
    raw_dir = cfg["paths_resolved"]["media_raw"]
    stem = _safe_stem(str(meta.get("id") or "scene"))
    prompts = build_scene_prompts(meta, need, cfg)
    negative = _load_negative(cfg)
    ua = media.get("user_agent", "yt-history-shorts/0.3")
    provider = str(media.get("provider", "ai_api")).lower()
    session = _session(ua)
    api = media.get("ai_api") or {}
    width = int(api.get("width") or 768)
    height = int(api.get("height") or 1344)

    paths: list[Path] = []
    used_paid = False

    if provider == "ai_api":
        backend = str(api.get("backend") or "fal_flux_schnell").lower()
        fal_key = _fal_api_key()
        budget_ok = can_afford(need, cfg)
        want_fal = backend in {
            "fal",
            "fal_flux",
            "fal_flux_schnell",
            "flux",
            "flux_schnell",
        }

        if want_fal and fal_key and budget_ok:
            try:
                paths = generate_via_fal(
                    prompts,
                    raw_dir,
                    stem,
                    session,
                    endpoint=str(api.get("fal_endpoint") or "fal-ai/flux/schnell"),
                    width=width,
                    height=height,
                    steps=int(api.get("num_inference_steps") or 4),
                    negative=negative,
                )
                used_paid = True
            except Exception as exc:  # noqa: BLE001
                print(f"[ai] fal failed ({exc}); falling back to Pollinations")
                paths = []

        if not paths:
            if want_fal and not fal_key:
                print("[ai] FAL_KEY missing — using free Pollinations fallback")
            elif want_fal and not budget_ok:
                print(
                    f"[ai] Monthly image budget exhausted "
                    f"(remaining ${remaining_usd(cfg):.2f}) — Pollinations fallback"
                )
            if not paths:
                paths = generate_via_pollinations(
                    prompts, raw_dir, stem, session, width=width, height=height
                )

        if used_paid and paths:
            record_images(len(paths), cfg)

        if len(paths) < 4:
            raise RuntimeError(f"ai_api produced too few images: {len(paths)}")
        return paths[:need]

    # ai_local: Diffusers, optional free HTTP fallback
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
            paths = generate_via_pollinations(
                prompts, raw_dir, stem, session, width=width, height=height
            )
        else:
            raise RuntimeError(f"ai_local failed and free fallback disabled: {exc}") from exc

    if len(paths) < 4:
        raise RuntimeError(f"AI generation produced too few images: {len(paths)}")
    return paths[:need]


def process_ai_to_vertical(raw_paths: list[Path], stem: str, need: int) -> list[Path]:
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
