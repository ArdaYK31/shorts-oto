from __future__ import annotations

import json

import os

import re

import shutil

import subprocess

import tempfile

from pathlib import Path

from config_loader import load_config
from sfx import ensure_sfx_library, resolve_sfx_times, sfx_enabled, sfx_volume

# ASCII-only work dir for FFmpeg/libass (Windows non-ASCII home paths break filters).
# Must NOT hardcode C:\… inside Linux Docker — that made Cloud assemble fail instantly.
_ASCII_WORK = (
    Path(r"C:\yt-shorts-work")
    if os.name == "nt"
    else Path(os.environ.get("SHORTS_ASCII_WORK", "/tmp/yt-shorts-work"))
)

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

def _grade_filter(cfg: dict, label_in: str, label_out: str) -> str:

    ass = cfg.get("assemble") or {}

    contrast = float(ass.get("contrast", 1.08))

    saturation = float(ass.get("saturation", 0.92))

    brightness = float(ass.get("brightness", 0.02))

    parts = [

        f"{label_in}eq=contrast={contrast}:saturation={saturation}:brightness={brightness}"

    ]

    # Slight warm midtones (no paid LUT) — reds up, blues down a touch
    warm = ass.get("warm_midtones", True)
    if warm:
        parts.append("colorbalance=rs=0.04:gs=0.01:bs=-0.03:rm=0.03:bm=-0.02")

    if ass.get("vignette", True):
        # Softer than PI/5 — less crushed edges on 9:16
        vig = str(ass.get("vignette_angle", "PI/6"))
        parts.append(f"vignette={vig}")

    if ass.get("grain", False):

        strength = min(max(int(ass.get("grain_strength", 4)), 1), 8)

        parts.append(f"noise=alls={strength}:allf=t")

    return ",".join(parts) + f"[{label_out}]"

def _ease_progress(n: int) -> str:
    """Cubic ease-in-out progress 0→1 over frames (FFmpeg zoompan expr)."""
    # p = on/n; ease = 3p^2 - 2p^3
    return f"(3*pow(on/{n},2)-2*pow(on/{n},3))"


def _ken_burns_filter(

    i: int,

    frames: int,

    w: int,

    h: int,

    fps: int,

    zoom_end: float,

    mode: str,

) -> str:

    """Smooth Ken Burns only. NO shake/tremble/wiggle. Ease-in-out zoom/pan."""

    n = max(frames - 1, 1)

    z_delta = max(zoom_end - 1.0, 0.04)

    ease = _ease_progress(n)

    if mode == "zoom_in":

        z_expr = f"1+{z_delta:.6f}*{ease}"

        x_expr = "iw/2-(iw/zoom/2)"

        y_expr = "ih/2-(ih/zoom/2)"

    elif mode == "zoom_out":

        z_expr = f"{zoom_end:.6f}-{z_delta:.6f}*{ease}"

        x_expr = "iw/2-(iw/zoom/2)"

        y_expr = "ih/2-(ih/zoom/2)"

    elif mode == "pan_right":

        z_expr = f"1+{z_delta * 0.55:.6f}"

        x_expr = f"(iw-iw/zoom)*({ease})"

        y_expr = "ih/2-(ih/zoom/2)"

    elif mode == "pan_left":

        z_expr = f"1+{z_delta * 0.55:.6f}"

        x_expr = f"(iw-iw/zoom)*(1-({ease}))"

        y_expr = "ih/2-(ih/zoom/2)"

    elif mode == "pan_up":

        # Prefer vertical pans for 9:16 — reveal more of the frame
        z_expr = f"1+{z_delta * 0.55:.6f}"

        x_expr = "iw/2-(iw/zoom/2)"

        y_expr = f"(ih-ih/zoom)*(1-({ease}))"

    elif mode == "pan_down":

        z_expr = f"1+{z_delta * 0.55:.6f}"

        x_expr = "iw/2-(iw/zoom/2)"

        y_expr = f"(ih-ih/zoom)*({ease})"

    else:

        z_expr = f"1+{z_delta * 0.55:.6f}"

        x_expr = f"(iw-iw/zoom)*(1-({ease}))"

        y_expr = "ih/2-(ih/zoom/2)"

    # 2400 pre-scale: cleaner than native, faster/safer than 3600 on long chains

    return (

        f"[{i}:v]scale=2400:-2:flags=lanczos,"

        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"

        f"d={frames}:s={w}x{h}:fps={fps},"

        f"setsar=1,format=yuv420p[v{i}]"

    )


def _pick_ken_burns_modes(n: int) -> list[str]:
    """9:16-friendly modes; never repeat the same mode on consecutive scenes."""
    # Prefer vertical pans for vertical video; keep some zoom variety
    pool = ["pan_up", "pan_down", "zoom_in", "pan_up", "zoom_out", "pan_down", "pan_left", "pan_right"]
    out: list[str] = []
    for i in range(n):
        choice = pool[i % len(pool)]
        if out and choice == out[-1]:
            # Skip to next distinct mode
            for alt in pool:
                if alt != out[-1]:
                    choice = alt
                    break
        out.append(choice)
    return out

def _expand_scene_durs(durs: list[float], max_sec: float = 4.0, target: float = 3.0) -> list[float]:

    """Subdivide any scene longer than max_sec into ~target slices (never > max_sec)."""

    import math

    out: list[float] = []

    for d in durs:

        d = float(d)

        if d <= max_sec:

            # Avoid max(d, 0.9): that inflated timeline past narration length.

            out.append(max(d, 0.05))

            continue

        n = max(2, int(math.ceil(d / target)))

        while d / n > max_sec:

            n += 1

        piece = d / n

        out.extend([piece] * n)

    return out

def _load_beats(cap_dir: Path, stem: str, duration: float) -> list[float] | None:

    path = cap_dir / f"{stem}.beats.json"

    if not path.exists():

        return None

    try:

        data = json.loads(path.read_text(encoding="utf-8"))

    except json.JSONDecodeError:

        return None

    beats = data.get("beats") or []

    if not beats:

        return None

    durs = [max(float(b.get("end", 0)) - float(b.get("start", 0)), 0.05) for b in beats]

    total = sum(durs)

    if total <= 0:

        return None

    durs = [d * (duration / total) for d in durs]

    # Prefer more cuts: split any still longer than 4s across multiple images

    durs = _expand_scene_durs(durs, max_sec=4.0, target=3.0)

    total2 = sum(durs)

    if abs(total2 - duration) > 0.05 and total2 > 0:

        durs = [d * (duration / total2) for d in durs]

        # Re-clamp after rescale in case float drift pushes a slice over 4s

        durs = _expand_scene_durs(durs, max_sec=4.0, target=3.0)

        total3 = sum(durs)

        if abs(total3 - duration) > 0.05 and total3 > 0:

            durs = [d * (duration / total3) for d in durs]

    return durs

def _scene_durations(

    images: list[Path],

    duration: float,

    beat_durs: list[float] | None,

    target_sec: float,

) -> tuple[list[Path], list[float]]:

    if beat_durs:

        # Hard cap: no static scene longer than 4s (viral 2–4s cuts)

        durs = _expand_scene_durs(list(beat_durs), max_sec=4.0, target=3.0)

        total = sum(durs)

        if abs(total - duration) > 0.05 and total > 0:

            durs = [d * (duration / total) for d in durs]

            durs = _expand_scene_durs(durs, max_sec=4.0, target=3.0)

            total2 = sum(durs)

            if abs(total2 - duration) > 0.05 and total2 > 0:

                durs = [d * (duration / total2) for d in durs]

        n = len(durs)

        mapped = [images[i % len(images)] for i in range(n)]

        print(f"[assemble] Beat-sync: {n} scenes (max scene <=4s, Ken Burns)")

        return mapped, durs

    # Prefer ~2–4s cuts; never exceed scene_max

    target_sec = max(2.0, min(target_sec, 4.0))

    ideal_count = max(int(round(duration / target_sec)), 1)

    # Ensure equal slices never exceed 4s

    min_count = max(int(__import__("math").ceil(duration / 4.0)), 1)

    ideal_count = max(ideal_count, min_count)

    imgs = list(images)

    while len(imgs) < ideal_count:

        imgs.extend(images)

    imgs = imgs[:ideal_count]

    seg = duration / len(imgs)

    print(f"[assemble] Equal slice fallback: {len(imgs)} scenes x {seg:.2f}s")

    return imgs, [seg] * len(imgs)

def _fonts_dir(cfg: dict) -> Path | None:
    """Bundled free fonts (Montserrat) for libass — works on Actions Linux + Windows."""
    root = Path(cfg.get("_root") or Path(__file__).resolve().parent.parent)
    fonts = root / "assets" / "fonts"
    if fonts.is_dir() and any(fonts.glob("*.ttf")):
        return fonts
    return None


def _stage_ass(caption_path: Path, stem: str, fonts_dir: Path | None = None) -> Path:

    """Copy ASS (+ fonts) to ASCII-only path so libass/ffmpeg do not choke on Turkish chars."""

    _ASCII_WORK.mkdir(parents=True, exist_ok=True)

    dest = _ASCII_WORK / f"{stem}.ass"

    shutil.copy2(caption_path, dest)

    if fonts_dir and fonts_dir.is_dir():
        staged_fonts = _ASCII_WORK / "fonts"
        staged_fonts.mkdir(parents=True, exist_ok=True)
        for ttf in fonts_dir.glob("*.ttf"):
            target = staged_fonts / ttf.name
            if not target.exists() or target.stat().st_mtime < ttf.stat().st_mtime:
                shutil.copy2(ttf, target)

    return dest

def assemble(

    stem: str | None = None,

    audio_path: Path | None = None,

    caption_path: Path | None = None,

) -> Path:

    cfg = load_config()

    scripts_dir = cfg["paths_resolved"]["scripts"]

    audio_dir = cfg["paths_resolved"]["audio"]

    proc_dir = cfg["paths_resolved"]["media_processed"]

    cap_dir = cfg["paths_resolved"]["captions"]

    out_dir = cfg["paths_resolved"]["out"]

    bgm_dir = cfg["paths_resolved"]["bgm"]

    out_dir.mkdir(parents=True, exist_ok=True)

    ass_cfg = cfg.get("assemble") or {}

    media_cfg = cfg.get("media") or {}

    mix_cfg = cfg.get("audio_mix") or {}

    if stem is None:

        metas = sorted(scripts_dir.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        name = metas[0].name

        stem = name[: -len(".meta.json")] if name.endswith(".meta.json") else metas[0].stem

    if audio_path is None:

        audio_path = audio_dir / f"{stem}.mp3"

    if not audio_path.exists():

        raise SystemExit(f"Missing audio: {audio_path}")

    duration = _ffprobe_duration(audio_path)

    max_dur = float(cfg["project"]["max_duration_sec"])

    gates = cfg.get("quality_gates") or {}

    gate_max = float(gates.get("max_duration_sec", 60))

    # Hard cap narration before scenes so quality_gates cannot fail schedule uploads.

    hard_max = min(max_dur, gate_max - 1.0)

    hard_max = max(hard_max, 20.0)

    if duration > hard_max + 0.05:

        trimmed = audio_path.with_suffix(".trim.mp3")

        fade = min(1.2, hard_max * 0.08)

        fade_start = max(hard_max - fade, 0.0)

        cmd_trim = [

            "ffmpeg",

            "-y",

            "-i",

            str(audio_path),

            "-t",

            f"{hard_max:.3f}",

            "-af",

            f"afade=t=out:st={fade_start:.3f}:d={fade:.3f}",

            "-codec:a",

            "libmp3lame",

            "-q:a",

            "2",

            str(trimmed),

        ]

        subprocess.run(cmd_trim, check=True, capture_output=True)

        trimmed.replace(audio_path)

        duration = _ffprobe_duration(audio_path)

        print(

            f"[assemble] Hard-trimmed audio to {duration:.1f}s "

            f"(Shorts cap {hard_max:.0f}s; was over limit)"

        )

    manifest = proc_dir / f"{stem}.images.json"

    if not manifest.exists():

        raise SystemExit(f"Missing images manifest: {manifest}")

    image_names = json.loads(manifest.read_text(encoding="utf-8"))

    images = [p for p in (proc_dir / n for n in image_names) if p.exists()]

    if not images:

        raise SystemExit("No processed images")

    if caption_path is None:

        candidate = cap_dir / f"{stem}.ass"

        caption_path = candidate if candidate.exists() else None

    w = int(cfg["project"]["width"])

    h = int(cfg["project"]["height"])

    fps = int(cfg["project"]["fps"])

    zoom = float(media_cfg.get("ken_burns_zoom", 1.08))

    target_sec = float(media_cfg.get("seconds_per_image", 4.0))

    beat_durs = _load_beats(cap_dir, stem, duration)

    images, scene_durs = _scene_durations(images, duration, beat_durs, target_sec)

    print(

        f"[assemble] {len(images)} scenes (audio {duration:.1f}s) "

        f"avg={sum(scene_durs)/len(scene_durs):.2f}s "

        f"range={min(scene_durs):.2f}-{max(scene_durs):.2f}s"

    )

    crossfade = float(ass_cfg.get("crossfade_sec", 0.35))

    crossfade = max(0.0, min(crossfade, 0.55))

    if len(images) <= 1:

        crossfade = 0.0

    if crossfade > 0:

        min_scene = min(scene_durs)

        if min_scene < crossfade * 2.2:

            crossfade = max(0.12, min_scene / 2.5)

            print(f"[assemble] Crossfade reduced to {crossfade:.2f}s for short beats")

    modes = _pick_ken_burns_modes(len(images))

    inputs: list[str] = []

    filter_parts: list[str] = []

    for i, img in enumerate(images):

        visible = scene_durs[i]

        seg_input = visible + crossfade if (crossfade > 0 and i < len(images) - 1) else visible

        inputs.extend(["-loop", "1", "-t", f"{seg_input:.4f}", "-i", str(img)])

        # round(): int() truncation made clips short → xfade offset past end → freeze
        frames = max(int(round(seg_input * fps)), 1)

        filter_parts.append(_ken_burns_filter(i, frames, w, h, fps, zoom, modes[i]))

    if crossfade > 0 and len(images) > 1:

        prev = "v0"

        acc = 0.0

        for i in range(1, len(images)):

            acc += scene_durs[i - 1]

            out_label = f"xf{i}" if i < len(images) - 1 else "vcat"

            filter_parts.append(

                f"[{prev}][v{i}]xfade=transition=fade:duration={crossfade:.3f}:"

                f"offset={acc:.4f}[{out_label}]"

            )

            prev = out_label

    else:

        concat_in = "".join(f"[v{i}]" for i in range(len(images)))

        filter_parts.append(f"{concat_in}concat=n={len(images)}:v=1:a=0[vcat]")

    filter_parts.append(_grade_filter(cfg, "[vcat]", "vgraded"))

    narr_idx = len(images)

    inputs.extend(["-i", str(audio_path)])

    bgm_file = (mix_cfg.get("bgm_file") or "").strip()

    bgm_path = bgm_dir / bgm_file if bgm_file else None

    has_bgm = bool(bgm_path and bgm_path.exists())

    nv = float(mix_cfg.get("narration_volume", 1.0))

    bv = max(0.05, min(float(mix_cfg.get("bgm_volume", 0.15)), 0.35))

    duck = bool(mix_cfg.get("bgm_duck", True))

    li = float(ass_cfg.get("loudnorm_i", -14))

    ltp = float(ass_cfg.get("loudnorm_tp", -1.5))

    llra = float(ass_cfg.get("loudnorm_lra", 11))

    # --- SFX stings (hook / twist / payoff), cached under assets/sfx/ ---
    meta_obj: dict = {}
    meta_early = scripts_dir / f"{stem}.meta.json"
    if meta_early.exists():
        try:
            meta_obj = json.loads(meta_early.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta_obj = {}
    narration_txt = ""
    script_txt = scripts_dir / f"{stem}.txt"
    if script_txt.exists():
        narration_txt = script_txt.read_text(encoding="utf-8")

    sfx_paths: dict = {}
    sfx_times: dict = {}
    sv = 0.2
    if sfx_enabled(cfg):
        try:
            sfx_paths = ensure_sfx_library(cfg)
            sfx_times = resolve_sfx_times(
                duration, meta=meta_obj, narration=narration_txt, cfg=cfg
            )
            sv = sfx_volume(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[assemble] SFX skipped ({exc})")
            sfx_paths = {}

    sfx_inputs: list[tuple[str, float, Path]] = []
    for beat in ("hook", "twist", "payoff"):
        path = sfx_paths.get(beat)
        if path and Path(path).exists() and beat in sfx_times:
            sfx_inputs.append((beat, float(sfx_times[beat]), Path(path)))

    next_idx = narr_idx + 1
    bgm_idx = None
    if has_bgm:
        bgm_idx = next_idx
        inputs.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        next_idx += 1

    sfx_indices: list[tuple[str, float, int]] = []
    for beat, t_sec, path in sfx_inputs:
        sfx_indices.append((beat, t_sec, next_idx))
        inputs.extend(["-i", str(path)])
        next_idx += 1

    # Build base narr (+ optional ducked BGM) → [abase], then overlay SFX → [aout]
    if has_bgm and bgm_idx is not None:
        if duck:
            filter_parts.append(
                f"[{narr_idx}:a]volume={nv},asplit=2[narr_sc][narr_mix];"
                f"[{bgm_idx}:a]volume={bv},afade=t=in:st=0:d=1.2,afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.4[bg];"
                f"[bg][narr_sc]sidechaincompress="
                f"threshold=0.035:ratio=6:attack=60:release=500:makeup=1.15:knee=8[bgd];"
                f"[narr_mix][bgd]amix=inputs=2:duration=first:dropout_transition=2[abase]"
            )
            print(f"[assemble] BGM={bgm_path.name} vol={bv} + sidechain duck")
        else:
            filter_parts.append(
                f"[{narr_idx}:a]volume={nv}[narr];"
                f"[{bgm_idx}:a]volume={bv},afade=t=in:st=0:d=1[bg];"
                f"[narr][bg]amix=inputs=2:duration=first:dropout_transition=2[abase]"
            )
            print(f"[assemble] BGM={bgm_path.name} vol={bv} (no duck)")
    else:
        filter_parts.append(f"[{narr_idx}:a]volume={nv}[abase]")
        if bgm_file:
            print(f"[assemble] BGM missing ({bgm_file}) - narration only")

    if sfx_indices:
        sfx_labels = []
        for i, (beat, t_sec, idx) in enumerate(sfx_indices):
            ms = max(0, int(round(t_sec * 1000)))
            lab = f"sfx{i}"
            # adelay + apad so amix duration follows narration bed
            filter_parts.append(
                f"[{idx}:a]volume={sv},aformat=sample_fmts=fltp:channel_layouts=mono,"
                f"adelay={ms}|{ms},apad[{lab}]"
            )
            sfx_labels.append(f"[{lab}]")
            print(f"[assemble] SFX {beat} @{t_sec:.2f}s vol={sv}")
        n_mix = 1 + len(sfx_labels)
        mix_in = "[abase]" + "".join(sfx_labels)
        filter_parts.append(
            f"{mix_in}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0[amixed];"
            f"[amixed]loudnorm=I={li}:TP={ltp}:LRA={llra}[aout]"
        )
    else:
        filter_parts.append(f"[abase]loudnorm=I={li}:TP={ltp}:LRA={llra}[aout]")

    audio_map = "[aout]"

    staged_ass: Path | None = None

    if caption_path and caption_path.exists():

        fonts_dir = _fonts_dir(cfg)

        staged_ass = _stage_ass(caption_path, stem, fonts_dir)

        ass_esc = str(staged_ass).replace("\\", "/").replace(":", "\\:")

        if fonts_dir:
            fonts_esc = str(_ASCII_WORK / "fonts").replace("\\", "/").replace(":", "\\:")
            filter_parts.append(f"[vgraded]ass='{ass_esc}':fontsdir='{fonts_esc}'[vout]")
            print(f"[assemble] Captions + fontsdir={fonts_esc}")
        else:
            filter_parts.append(f"[vgraded]ass='{ass_esc}'[vout]")
            print(f"[assemble] Captions staged at {staged_ass}")

        video_map = "[vout]"

    else:

        video_map = "[vgraded]"

    # Lock A/V to narration length. Without this, xfade/zoompan float drift or
    # unreliable -shortest leaves a frozen last frame after audio ends.
    dur_s = f"{min(duration, hard_max):.4f}"
    filter_parts.append(
        f"{video_map}trim=duration={dur_s},setpts=PTS-STARTPTS,fps={fps}[vfinal]"
    )
    filter_parts.append(
        f"{audio_map}atrim=duration={dur_s},asetpts=PTS-STARTPTS[afinal]"
    )
    video_map = "[vfinal]"
    audio_map = "[afinal]"
    print(f"[assemble] Hard-trimmed A/V to {dur_s}s (no post-narration freeze)")

    filter_complex = ";".join(filter_parts)

    out_path = out_dir / f"{stem}.mp4"

    # Encode to ASCII work dir then move - avoids mid-write issues on complex paths

    _ASCII_WORK.mkdir(parents=True, exist_ok=True)

    tmp_path = _ASCII_WORK / f"{stem}.tmp.mp4"

    meta_path = scripts_dir / f"{stem}.meta.json"

    title = stem

    if meta_path.exists():

        title = json.loads(meta_path.read_text(encoding="utf-8")).get("title", stem)

    crf = str(ass_cfg.get("crf", 17))

    preset = str(ass_cfg.get("preset", "medium"))

    cmd = [

        "ffmpeg",

        "-y",

        *inputs,

        "-filter_complex",

        filter_complex,

        "-map",

        video_map,

        "-map",

        audio_map,

        "-c:v",

        "libx264",

        "-preset",

        preset,

        "-crf",

        crf,

        "-pix_fmt",

        "yuv420p",

        "-c:a",

        "aac",

        "-b:a",

        "192k",

        "-ar",

        "48000",

        # Output length = narration (not hard_max). -shortest alone is unreliable
        # with filter_complex and can leave a frozen tail.
        "-t",

        f"{min(duration, hard_max):.3f}",

        "-movflags",

        "+faststart",

        "-metadata",

        f"title={title}",

        "-metadata",

        "language=eng",

        str(tmp_path),

    ]

    print(f"[assemble] Smooth Ken Burns + grade + loudnorm CRF={crf} (no shake)...")

    log_path = out_dir / f"{stem}.ffmpeg.log"

    with log_path.open("w", encoding="utf-8", errors="replace") as logf:

        proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)

    if proc.returncode != 0:

        raise SystemExit(f"ffmpeg failed (code {proc.returncode}); see {log_path}")

    if out_path.exists():

        out_path.unlink()

    shutil.move(str(tmp_path), str(out_path))

    print(f"[assemble] Wrote {out_path}")

    from cleanup_temps import cleanup_temp_mp4s

    cleanup_temp_mp4s(stem=stem, keep=out_path)

    used = cfg["paths_resolved"]["topics"] / "used" / f"{stem}.json"

    used.parent.mkdir(parents=True, exist_ok=True)

    if meta_path.exists():

        used.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")

    else:

        used.write_text(json.dumps({"id": stem}), encoding="utf-8")

    seo_path = (cfg["paths_resolved"].get("seo") or (cfg["_root"] / "seo")) / f"{stem}.seo.json"

    seo_hint = ""

    if seo_path.exists():

        seo = json.loads(seo_path.read_text(encoding="utf-8"))

        seo_hint = (

            f"Title: {seo.get('title', title)}\n"

            f"Tags: {', '.join(seo.get('tags', [])[:8])}\n"

            f"Approval: {seo.get('approval', {}).get('status', 'pending_human_review')}\n"

            f"SEO JSON: {seo_path.name}\n"

        )

    readme = out_dir / f"{stem}.UPLOAD.txt"
    sched = cfg.get("schedule") or {}
    auto_upload = bool(sched.get("auto_upload", True))
    require_approval = bool(sched.get("require_approval", False))
    if auto_upload and not require_approval:
        header = "CLOUD AUTOPILOT — NO HUMAN APPROVAL"
        note = (
            "scheduled_run.py uploads immediately (YT public + IG/TT if secrets). "
            "Atelier Approve queue is optional for manual local experiments only."
        )
    else:
        header = "MANUAL UPLOAD - HUMAN APPROVAL REQUIRED"
        note = "Review MP4 + SEO pack before uploading (local/manual path)."
    privacy = (sched.get("privacy") or (cfg.get("upload") or {}).get("privacy") or "public")
    readme.write_text(
        "\n".join(
            [
                header,
                "========================================",
                "Language: English only (video content)",
                f"File: {out_path.name}",
                f"Title: {title}",
                seo_hint,
                "Description: see seo/*.seo.json (English SEO pack)",
                f"Visibility: {privacy}",
                note,
                "ElevenLabs only if ELEVENLABS_API_KEY is set; else Kokoro. Free quality upgrades stay on.",
            ]
        ),
        encoding="utf-8",
    )

    print(f"[assemble] Upload notes: {readme}")

    return out_path

if __name__ == "__main__":

    import argparse

    p = argparse.ArgumentParser()

    p.add_argument("--stem", default=None)

    args = p.parse_args()

    assemble(stem=args.stem)
