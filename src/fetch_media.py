from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from PIL import Image

from config_loader import load_config
from media_scorer import score_image

GRANT_LOC_URLS: list[str] = [
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/06900/06902v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/04400/04402v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/01000/01005v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/01100/01104v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/01500/01550v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/02200/02240v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/02300/02394v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/03400/03451v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/03700/03783v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/03900/03965v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/04000/04016v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/04200/04270v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/04300/04321v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/05300/05301v.jpg",
    "https://tile.loc.gov/storage-services/service/pnp/cwpb/06000/06045v.jpg",
]

GRANT_COMMONS_FILES: list[str] = [
    "Ulysses S Grant by Brady c1870-restored.jpg",
    "Ulysses S. Grant 1870-1880.jpg",
    "Battle of Antietam.jpg",
    "Grant and staff.jpg",
    "The Peacemakers 1868.jpg",
    "Abraham Lincoln O-77 matte collodion print.jpg",
    "Robert Edward Lee.jpg",
    "Dead on Antietam battlefield.jpg",
    "President Ulysses S. Grant seated portrait Brady.jpg",
    "Appomattox barn VA2.jpg",
    "Appomattox Court House, VA, Theater IMG 4179.JPG",
]


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name)[:80]


def _file_fingerprint(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def _session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept": "image/*,*/*;q=0.8"})
    return s


def commons_filepath_url(title: str, width: int = 2000) -> str:
    clean = title[5:] if title.startswith("File:") else title
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(clean)}?width={width}"


def download_file(url: str, dest: Path, session: requests.Session, retries: int = 2) -> Path:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with session.get(url, stream=True, timeout=120, allow_redirects=True) as r:
                if r.status_code == 429:
                    wait = 8 * (attempt + 1)
                    print(f"[media] 429 — sleep {wait}s")
                    time.sleep(wait)
                    last_err = RuntimeError("429")
                    continue
                r.raise_for_status()
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "text/html" in ctype and "image" not in ctype:
                    raise RuntimeError("HTML response")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            with Image.open(dest) as img:
                img.verify()
            return dest
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(str(last_err))


def fit_cover_jpg(
    src: Path,
    dest: Path,
    width: int,
    height: int,
    bias: float = 0.5,
) -> Path:
    from PIL import ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    bias = max(0.0, min(float(bias), 1.0))
    img = Image.open(src).convert("RGB")
    src_w, src_h = img.size
    if src_w < 32 or src_h < 32:
        raise OSError(f"Image too small: {src}")
    scale = max(width / src_w, height / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    max_left = max(new_w - width, 0)
    max_top = max(new_h - height, 0)
    left = int(max_left * bias)
    top = int(max_top * (0.35 + 0.3 * bias))
    img = img.crop((left, top, left + width, top + height))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=95, optimize=True)
    return dest


def _consider(
    path: Path,
    label: str,
    scored: list[tuple[float, Path, str]],
    seen_fp: set[str],
    *,
    score_enabled: bool,
    min_w: int,
    min_h: int,
    min_score: float,
    hard_min_w: int,
    hard_min_h: int,
) -> bool:
    try:
        with Image.open(path) as im:
            rw, rh = im.size
    except OSError:
        return False
    if rw < hard_min_w or rh < hard_min_h:
        print(f"[media] SKIP low-res {rw}x{rh} {label}")
        return False
    fp = _file_fingerprint(path)
    if fp in seen_fp:
        print(f"[media] SKIP duplicate {label}")
        return False
    s = score_image(path, min_w, min_h) if score_enabled else 50.0
    if score_enabled and s < min_score:
        print(f"[media] SKIP low score={s:.1f} {label}")
        return False
    seen_fp.add(fp)
    scored.append((s, path, label))
    print(f"[media] OK score={s:.1f} {rw}x{rh} {label}")
    return True


def fetch_media(meta_path: Path | None = None) -> list[Path]:
    cfg = load_config()
    root = cfg["_root"]
    scripts_dir = cfg["paths_resolved"]["scripts"]
    raw_dir = cfg["paths_resolved"]["media_raw"]
    proc_dir = cfg["paths_resolved"]["media_processed"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    proc_dir.mkdir(parents=True, exist_ok=True)

    if meta_path is None:
        metas = sorted(scripts_dir.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not metas:
            raise SystemExit("No script meta found.")
        meta_path = metas[0]

    meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    stem = meta["id"]
    need = int(cfg["media"]["image_count"])
    provider = str(cfg["media"].get("provider", "ai_local")).lower().strip()

    # ChronoShorts look = AI painterly stills (local Diffusers or free Pollinations)
    if provider in {"ai_local", "ai_api"}:
        try:
            from generate_images import generate_ai_stills, process_ai_to_vertical

            print(f"[media] provider={provider} (ChronoShorts AI illustration path)")
            raws = generate_ai_stills(meta, need)
            processed = process_ai_to_vertical(raws, stem, need)
            if len(processed) >= 4:
                manifest = proc_dir / f"{stem}.images.json"
                manifest.write_text(
                    json.dumps([p.name for p in processed], indent=2), encoding="utf-8"
                )
                print(f"[media] Ready {len(processed)} AI scenes")
                return processed
            print(f"[media] AI path only got {len(processed)} — falling back to Wikimedia")
        except Exception as exc:  # noqa: BLE001
            print(f"[media] AI provider failed ({exc}); falling back to Wikimedia PD")

    ua = cfg["media"]["user_agent"]
    w, h = int(cfg["project"]["width"]), int(cfg["project"]["height"])
    score_enabled = bool(cfg["media"].get("score_enabled", True))
    min_w = int(cfg["media"].get("min_width", 800))
    min_h = int(cfg["media"].get("min_height", 600))
    min_score = float(cfg["media"].get("min_score", 22.0))
    hard_min_w = int(cfg["media"].get("hard_min_width", 600))
    hard_min_h = int(cfg["media"].get("hard_min_height", 450))

    print("[media] provider=wikimedia (PD / LOC archival)")
    session = _session(ua)
    scored: list[tuple[float, Path, str]] = []
    seen_fp: set[str] = set()
    consider_kwargs = dict(
        score_enabled=score_enabled,
        min_w=min_w,
        min_h=min_h,
        min_score=min_score,
        hard_min_w=hard_min_w,
        hard_min_h=hard_min_h,
    )

    # 1) Local offline PD pack (seeded from LOC) — immune to Commons 429
    local_dirs = [
        root / "media" / "fallbacks" / stem.split("-")[0],  # e.g. ulysses
        root / "media" / "fallbacks" / "grant" if "grant" in stem else None,
        root / "media" / "fallbacks" / stem,
    ]
    for d in local_dirs:
        if d is None or not d.is_dir():
            continue
        print(f"[media] Scanning local pack {d}")
        for p in sorted(d.glob("*")):
            if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
                continue
            if len(scored) >= need * 2:
                break
            _consider(p, f"local:{p.name}", scored, seen_fp, **consider_kwargs)

    # 2) Reuse prior raw downloads for this stem (high-res Commons hits from earlier runs)
    for p in sorted(raw_dir.glob(f"{stem}_*")):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
            continue
        if len(scored) >= need * 2:
            break
        _consider(p, f"cache:{p.name}", scored, seen_fp, **consider_kwargs)

    # 3) Network: topic PD URLs + LOC + Commons FilePath (best-effort under rate limits)
    urls: list[tuple[str, str]] = []
    seen_u: set[str] = set()

    def add_url(label: str, url: str) -> None:
        if url not in seen_u:
            seen_u.add(url)
            urls.append((label, url))

    for url in list(meta.get("pd_fallback_urls") or []):
        add_url(url.split("/")[-1][:50], url)
    if "grant" in stem:
        for url in GRANT_LOC_URLS:
            add_url(url.split("/")[-1][:50], url)

    titles = list(meta.get("wikimedia_titles") or [])
    if "grant" in stem:
        for t in GRANT_COMMONS_FILES:
            if t not in titles:
                titles.append(t)
    for t in titles:
        add_url(t, commons_filepath_url(t, width=2000))

    idx = 0
    for label, url in urls:
        if len(scored) >= need:
            break
        try:
            ext = Path(url.split("?")[0]).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}:
                ext = ".jpg"
            dest = raw_dir / f"{stem}_net_{idx:02d}{_safe_name(ext)}"
            idx += 1
            print(f"[media] Downloading {label}")
            download_file(url, dest, session)
            if not _consider(dest, label, scored, seen_fp, **consider_kwargs):
                dest.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[media] Failed {label[:60]}: {exc}")
        time.sleep(0.7)

    scored.sort(key=lambda t: t[0], reverse=True)
    chosen = scored[:need]

    for old in proc_dir.glob(f"{stem}_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass

    processed: list[Path] = []
    used: set[Path] = set()
    for _score, raw_path, title in scored:
        if len(processed) >= need:
            break
        if raw_path in used:
            continue
        out = proc_dir / f"{stem}_{len(processed):02d}.jpg"
        try:
            fit_cover_jpg(raw_path, out, w, h, bias=0.5)
        except OSError as exc:
            print(f"[media] SKIP unreadable {title}: {exc}")
            continue
        used.add(raw_path)
        processed.append(out)
        print(f"[media] Selected #{len(processed)-1}: {title}")

    unique_raw: list[Path] = []
    for _s, p, _t in scored:
        if p in unique_raw:
            continue
        try:
            with Image.open(p) as im:
                im.load()
            unique_raw.append(p)
        except OSError:
            continue
        if len(unique_raw) >= need:
            break

    if unique_raw and len(processed) < need:
        print(f"[media] Only {len(processed)} processed — cycling crops to reach {need}")
        guard = 0
        while len(processed) < need and guard < need * 3:
            guard += 1
            i = len(processed)
            src = unique_raw[i % len(unique_raw)]
            out = proc_dir / f"{stem}_{i:02d}.jpg"
            bias = 0.15 + 0.7 * ((i * 0.37) % 1.0)
            try:
                fit_cover_jpg(src, out, w, h, bias=bias)
            except OSError:
                continue
            processed.append(out)
            print(f"[media] Cycle-fill #{i} from {src.name}")

    if len(processed) < 4:
        raise SystemExit(f"Too few usable images: {len(processed)}")

    processed = processed[:need]
    manifest = proc_dir / f"{stem}.images.json"
    manifest.write_text(json.dumps([p.name for p in processed], indent=2), encoding="utf-8")
    print(f"[media] Ready {len(processed)} scenes ({len(unique_raw)} unique sources)")
    return processed


if __name__ == "__main__":
    fetch_media()
