from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python src/run_pipeline.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from assemble import assemble
from captions import make_captions
from cleanup_temps import cleanup_temp_mp4s
from fetch_media import fetch_media
from generate_script import generate_script
from quality_gates import assert_ok
from config_loader import load_config
from sfx import ensure_sfx_library
from tts import synthesize


def main() -> None:
    parser = argparse.ArgumentParser(
        description="American history Shorts pipeline (English content, zero paid APIs)"
    )
    parser.add_argument("--topic-id", default=None, help="Topic id from topics/queue.json")
    args = parser.parse_args()

    cfg = load_config()
    script_path = generate_script(args.topic_id)
    stem = script_path.stem
    meta_path = script_path.parent / f"{stem}.meta.json"

    # Drop stale intermediates before a new encode
    cleanup_temp_mp4s(stem=stem, keep=cfg["paths_resolved"]["out"] / f"{stem}.mp4")

    # Cache cinematic SFX once (ElevenLabs Sound Gen or local); assemble mixes by beat
    ensure_sfx_library(cfg)

    audio_path = synthesize(script_path)
    fetch_media(meta_path)
    caption_path = make_captions(script_path, audio_path)
    out = assemble(stem=stem, audio_path=audio_path, caption_path=caption_path)
    cleanup_temp_mp4s(stem=stem, keep=out)
    assert_ok(out, cfg)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    seo_path = (cfg["paths_resolved"].get("seo") or (cfg["_root"] / "seo")) / f"{stem}.seo.json"
    print("\n=== DONE (English content locked) ===")
    print(f"Title : {meta.get('title')}")
    print(f"Lang  : en")
    print(f"Video : {out}")
    print(f"SEO   : {seo_path if seo_path.exists() else '(missing)'}")
    print("Next  : Local/manual -> optional Atelier Approve, OR cloud autopilot:")
    print("        python src/scheduled_run.py  (uploads immediately, no approval)")
    print("Note  : No paid APIs. Scheduled cloud path does NOT wait for approval.")


if __name__ == "__main__":
    main()
