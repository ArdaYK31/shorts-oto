from __future__ import annotations

from pathlib import Path

from PIL import Image


def score_image(path: Path, min_width: int = 800, min_height: int = 600) -> float:
    """Heuristic PD still scorer: resolution + aspect + avoid tiny/collage-ish extremes."""
    try:
        with Image.open(path) as img:
            w, h = img.size
    except OSError:
        return -1.0

    # Hard-fail tiny sources (blurry upscales look awful on Shorts)
    if w < 500 or h < 400:
        return -1.0

    if w < min_width or h < min_height:
        # Usable but heavily penalized
        size_score = (w * h) / (min_width * min_height) * 20.0
    else:
        size_score = min((w * h) / 1_000_000.0 * 40.0, 60.0)

    aspect = w / max(h, 1)
    # Prefer landscape or near-square historical photos over ultra-wide banners
    if 0.6 <= aspect <= 2.2:
        aspect_score = 25.0
    elif 0.4 <= aspect <= 3.0:
        aspect_score = 12.0
    else:
        aspect_score = 0.0

    # Slight preference for larger files (often less compressed)
    try:
        bytes_score = min(path.stat().st_size / (500_000), 15.0)
    except OSError:
        bytes_score = 0.0

    return float(size_score + aspect_score + bytes_score)


def pick_best(paths: list[Path], need: int, min_width: int = 800, min_height: int = 600) -> list[Path]:
    ranked = sorted(
        ((score_image(p, min_width, min_height), p) for p in paths),
        key=lambda t: t[0],
        reverse=True,
    )
    return [p for score, p in ranked if score >= 0][:need]
