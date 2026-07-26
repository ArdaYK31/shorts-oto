from __future__ import annotations

from pathlib import Path

from config_loader import load_config

_ASCII_WORK = Path(r"C:\yt-shorts-work")

# Intermediate / leftover video names — never delete the final out/{stem}.mp4
_TEMP_NAME_HINTS = (
    ".tmp.mp4",
    "_partial.mp4",
    "_segment",
    "ffmpeg2pass",
    ".part.mp4",
)


def _is_temp_mp4(path: Path, keep: Path | None) -> bool:
    if path.suffix.lower() != ".mp4":
        return False
    if keep is not None and path.resolve() == keep.resolve():
        return False
    name = path.name.lower()
    if any(h in name for h in _TEMP_NAME_HINTS):
        return True
    # Bare encode leftovers in ASCII work dir
    if path.parent.resolve() == _ASCII_WORK.resolve():
        return True
    return False


def cleanup_temp_mp4s(stem: str | None = None, keep: Path | None = None) -> list[Path]:
    """
    Delete intermediate MP4s under out/, media/processed, and C:\\yt-shorts-work.
    Keeps only the final out/{stem}.mp4 when provided.
    """
    cfg = load_config()
    out_dir: Path = cfg["paths_resolved"]["out"]
    proc_dir: Path = cfg["paths_resolved"]["media_processed"]

    if keep is None and stem:
        keep = out_dir / f"{stem}.mp4"

    search_roots = [out_dir, proc_dir, _ASCII_WORK]
    removed: list[Path] = []

    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.mp4"):
            if not path.is_file():
                continue
            if not _is_temp_mp4(path, keep):
                continue
            try:
                path.unlink()
                removed.append(path)
                print(f"[cleanup] Removed {path}")
            except OSError as exc:
                print(f"[cleanup] Skip {path}: {exc}")

    # Also drop stem-specific leftovers that are clearly not the final deliverable
    if stem and keep:
        for root in (out_dir, proc_dir, _ASCII_WORK):
            if not root.exists():
                continue
            for path in root.glob(f"{stem}*.mp4"):
                if path.resolve() == keep.resolve():
                    continue
                if path.suffix.lower() != ".mp4":
                    continue
                # Only remove if looks intermediate (tmp/partial) OR lives in work dir
                if _is_temp_mp4(path, keep) or path.parent.resolve() == _ASCII_WORK.resolve():
                    try:
                        path.unlink()
                        if path not in removed:
                            removed.append(path)
                            print(f"[cleanup] Removed {path}")
                    except OSError as exc:
                        print(f"[cleanup] Skip {path}: {exc}")

    if removed:
        print(f"[cleanup] Deleted {len(removed)} temp MP4(s); kept {keep}")
    else:
        print("[cleanup] No temp MP4s to remove")
    return removed
