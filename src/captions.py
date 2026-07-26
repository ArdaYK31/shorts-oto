from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from config_loader import load_config
from fact_gate import resolve_claim

# Do not split on initials like "E." / "S." / "U.S."
_SENT_SPLIT = re.compile(r"(?<=(?<![A-Z])[.!?])\s+(?=[A-Z\"'])")


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


def _split_words(text: str) -> list[str]:
    return [w for w in re.findall(r"\S+", text) if w]


def _ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def _first_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return ""
    parts = _SENT_SPLIT.split(text, maxsplit=1)
    if parts:
        return parts[0].strip()
    words = _split_words(text)
    return " ".join(words[:12])


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    return parts or [text]


def _wrap_claim_lines(text: str, max_chars: int = 72) -> str:
    """ASS hard line breaks for frame-1 claim card."""
    words = _split_words(text)
    if not words:
        return ""
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = (" ".join(cur + [w])).strip()
        if cur and len(trial) > max_chars:
            lines.append(" ".join(cur))
            cur = [w]
            if len(lines) >= 3:
                break
        else:
            cur.append(w)
    if cur and len(lines) < 3:
        lines.append(" ".join(cur))
    return "\\N".join(lines)


def _load_claim_text(script_path: Path | None, narration: str, cfg: dict) -> str:
    """Claim card = the fact itself (never bare DID YOU KNOW?)."""
    topic: dict = {}
    if script_path and script_path.exists():
        meta_path = script_path.with_suffix(".meta.json")
        # scripts/foo.txt → scripts/foo.meta.json
        alt = script_path.parent / f"{script_path.stem}.meta.json"
        for candidate in (meta_path, alt):
            if candidate.exists():
                try:
                    topic = json.loads(candidate.read_text(encoding="utf-8"))
                    break
                except json.JSONDecodeError:
                    pass
    claim = resolve_claim(topic, narration)
    max_chars = int((cfg.get("captions") or {}).get("claim_max_chars", 72))
    # Soft trim for on-screen readability
    if len(claim) > max_chars * 3:
        claim = claim[: max_chars * 3 - 1].rsplit(" ", 1)[0] + "…"
    return claim


def _snap_karaoke_to_zero(
    timed_words: list[tuple[str, float, float]],
    *,
    enabled: bool = True,
    max_lead: float = 0.45,
) -> list[tuple[str, float, float]]:
    """Ensure karaoke starts at t=0 — no Whisper lead-in delay."""
    if not enabled or not timed_words:
        return timed_words
    first_start = float(timed_words[0][1])
    if first_start <= 0.02:
        return timed_words
    if first_start <= max_lead:
        shift = first_start
        snapped = [
            (w, max(0.0, float(s) - shift), max(0.02, float(e) - shift))
            for w, s, e in timed_words
        ]
        print(f"[captions] Karaoke snapped to t=0 (shifted −{shift:.2f}s)")
        return snapped
    # Larger lead: pin first word start to 0 without shifting the rest
    w0, _s0, e0 = timed_words[0]
    print(
        f"[captions] Karaoke first word pinned to t=0 "
        f"(Whisper lead was {first_start:.2f}s)"
    )
    return [(w0, 0.0, max(float(e0), 0.08))] + list(timed_words[1:])


def _subdivide_long_beat(beat: dict, max_dur: float, target: float = 3.0) -> list[dict]:
    """Split a beat longer than max_dur into ~target-second chunks."""
    import math

    t0, t1 = float(beat["start"]), float(beat["end"])
    dur = t1 - t0
    text = str(beat.get("text", "")).strip()
    if dur <= max_dur:
        return [beat]

    parts = _split_sentences(text)
    if len(parts) >= 2:
        total_chars = max(sum(len(p) for p in parts), 1)
        cursor = t0
        chunks: list[dict] = []
        for i, part in enumerate(parts):
            share = len(part) / total_chars
            end = t1 if i == len(parts) - 1 else cursor + share * dur
            chunks.append({"start": cursor, "end": end, "text": part})
            cursor = end
        out: list[dict] = []
        for c in chunks:
            out.extend(_subdivide_long_beat(c, max_dur, target))
        return out

    n = max(2, int(math.ceil(dur / target)))
    while dur / n > max_dur:
        n += 1
    words = _split_words(text) or [text or "..."]
    out: list[dict] = []
    cursor = t0
    word_i = 0
    for i in range(n):
        end = t1 if i == n - 1 else t0 + (i + 1) * (dur / n)
        remaining_slices = n - i
        remaining_words = len(words) - word_i
        take = max(1, remaining_words // remaining_slices) if remaining_words else 0
        if i == n - 1:
            slice_words = words[word_i:]
        else:
            slice_words = words[word_i : word_i + take]
            word_i += take
        out.append(
            {
                "start": cursor,
                "end": end,
                "text": " ".join(slice_words) if slice_words else text,
            }
        )
        cursor = end
    return out


def _merge_beats(
    raw: list[dict],
    *,
    min_dur: float = 1.5,
    max_dur: float = 4.0,
) -> list[dict]:
    """Merge short Whisper segments; never keep a beat longer than max_dur."""
    if not raw:
        return []
    merged: list[dict] = []
    buf = dict(raw[0])
    for seg in raw[1:]:
        dur = float(buf["end"]) - float(buf["start"])
        next_dur = float(seg["end"]) - float(seg["start"])
        if dur < min_dur or (next_dur < 1.0 and dur + next_dur <= max_dur):
            buf["end"] = seg["end"]
            buf["text"] = (
                str(buf.get("text", "")).strip() + " " + str(seg.get("text", "")).strip()
            ).strip()
        else:
            merged.append(buf)
            buf = dict(seg)
    merged.append(buf)
    final: list[dict] = []
    for beat in merged:
        final.extend(_subdivide_long_beat(beat, max_dur=max_dur, target=3.0))
    return final


def _write_beats_json(
    out_path: Path,
    beats: list[dict],
    *,
    hook_text: str,
    hook_end: float,
    duration: float,
    claim_text: str = "",
    claim_end: float = 0.0,
) -> Path:
    payload = {
        "duration": duration,
        "hook_text": hook_text,
        "hook_end": hook_end,
        "claim_text": claim_text,
        "claim_end": claim_end,
        "beats": [
            {
                "start": round(float(b["start"]), 4),
                "end": round(float(b["end"]), 4),
                "text": str(b.get("text", "")).strip(),
            }
            for b in beats
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def _beats_from_script(script_path: Path, duration: float) -> list[dict]:
    text = script_path.read_text(encoding="utf-8").strip()
    sentences = _split_sentences(text) or [text or "..."]
    weights = [max(len(_split_words(s)), 1) for s in sentences]
    total_w = sum(weights)
    beats: list[dict] = []
    cursor = 0.0
    for i, (sent, w) in enumerate(zip(sentences, weights)):
        share = w / total_w
        end = duration if i == len(sentences) - 1 else cursor + share * duration
        beats.append({"start": cursor, "end": end, "text": sent})
        cursor = end
    return _merge_beats(beats, max_dur=4.0)


def _write_header(cfg: dict, karaoke: bool = True) -> str:
    cap = cfg.get("captions") or {}
    font_size = int(cap["font_size"])
    font_name = str(cap.get("font_name", "Arial"))
    hook_size = int(cap.get("hook_font_size", max(font_size + 22, 90)))
    margin_v = int(cap["margin_v"])
    hook_margin_v = int(cap.get("hook_margin_v", 720))
    alignment = int(cap.get("alignment", 2))
    primary = cap["primary_color"]
    highlight = cap.get("highlight_color", "&H0000FFFF")
    hook_color = cap.get("hook_color", "&H0000D7FF")
    outline_c = cap["outline_color"]
    outline = int(cap["outline"])
    shadow = int(cap.get("shadow", 2))
    bold = -1 if cap["bold"] else 0
    secondary = highlight if karaoke else "&H000000FF"

    claim_size = int(cap.get("claim_font_size", 72))
    claim_margin = int(cap.get("claim_margin_v", 280))
    claim_align = int(cap.get("claim_alignment", 8))
    claim_color = cap.get("claim_color", "&H00FFFFFF")
    claim_outline = int(cap.get("claim_outline", outline + 1))

    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {cfg['project']['width']}
PlayResY: {cfg['project']['height']}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},{secondary},{outline_c},&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},{alignment},40,40,{margin_v},1
Style: Hook,{font_name},{hook_size},{hook_color},{secondary},{outline_c},&H80000000,-1,0,0,0,100,100,0,0,1,{outline + 1},{shadow},{alignment},40,40,{hook_margin_v},1
Style: Claim,{font_name},{claim_size},{claim_color},{secondary},{outline_c},&H80000000,-1,0,0,0,100,100,0,0,1,{claim_outline},{shadow},{claim_align},48,48,{claim_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _claim_event(cfg: dict, claim_text: str, duration: float) -> tuple[str | None, float]:
    cap = cfg.get("captions") or {}
    if not bool(cap.get("claim_card", True)):
        return None, 0.0
    if not claim_text.strip():
        return None, 0.0
    claim_sec = float(cap.get("claim_seconds", 2.6))
    claim_end = min(max(claim_sec, 1.5), duration * 0.35, 4.0)
    max_chars = int(cap.get("claim_max_chars", 72))
    body = _wrap_claim_lines(claim_text.upper(), max_chars=max_chars)
    if not body:
        return None, 0.0
    line = (
        f"Dialogue: 2,0:00:00.00,{_ass_timestamp(claim_end)},Claim,,0,0,0,,"
        f"{_ass_escape(body)}"
    )
    return line, claim_end


def write_ass_rough(script_path: Path, audio_path: Path, out_path: Path, cfg: dict) -> Path:
    text = script_path.read_text(encoding="utf-8").strip()
    words = _split_words(text)
    duration = _ffprobe_duration(audio_path)
    if not words:
        raise SystemExit("Empty script for captions")

    beats = _beats_from_script(script_path, duration)
    hook_seconds = float(cfg["captions"].get("hook_seconds", 0.0))
    hook_text = _first_sentence(text) if hook_seconds > 0 else ""
    hook_end = 0.0
    if hook_seconds > 0 and hook_text:
        hook_end = min(hook_seconds, duration * 0.25)
        if beats:
            hook_end = min(max(hook_end, float(beats[0]["end"]) * 0.55), float(beats[0]["end"]))

    claim_text = _load_claim_text(script_path, text, cfg)
    claim_line, claim_end = _claim_event(cfg, claim_text, duration)

    beats_path = out_path.parent / f"{out_path.stem}.beats.json"
    _write_beats_json(
        beats_path,
        beats,
        hook_text=hook_text,
        hook_end=hook_end,
        duration=duration,
        claim_text=claim_text,
        claim_end=claim_end,
    )

    chunk_size = int(cfg["captions"].get("words_per_line", 4))
    chunks = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]
    lead = 0.0  # karaoke from first word — no delay
    usable = max(duration - lead, 0.1)
    per = usable / max(len(chunks), 1)

    events: list[str] = []
    if claim_line:
        events.append(claim_line)
        print(f"[captions] Claim card until {claim_end:.2f}s: {claim_text[:50]!r}")
    if hook_text and hook_end > 0:
        events.append(
            f"Dialogue: 1,0:00:00.00,{_ass_timestamp(hook_end)},Hook,,0,0,0,,"
            f"{_ass_escape(hook_text.upper())}"
        )

    t = lead
    for chunk in chunks:
        start, end = t, min(t + per, duration)
        events.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,"
            f"{_ass_escape(chunk.upper())}"
        )
        t = end

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_write_header(cfg, karaoke=False) + "\n".join(events) + "\n", encoding="utf-8")
    return out_path


def write_ass_whisper(
    audio_path: Path, out_path: Path, cfg: dict, script_path: Path | None = None
) -> Path:
    from faster_whisper import WhisperModel

    cap = cfg.get("captions") or {}
    model_name = cap.get("whisper_model", "base.en")
    device = cap.get("whisper_device", "cpu")
    compute = cap.get("whisper_compute_type", "int8")
    words_per_line = int(cap.get("words_per_line", 4))
    duration = _ffprobe_duration(audio_path)

    print(f"[captions] faster-whisper model={model_name} device={device}")
    model = WhisperModel(model_name, device=device, compute_type=compute)
    segments, _info = model.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        vad_filter=True,
    )

    timed_words: list[tuple[str, float, float]] = []
    raw_beats: list[dict] = []
    for seg in segments:
        seg_text = (seg.text or "").strip()
        if seg_text:
            raw_beats.append(
                {"start": float(seg.start), "end": float(seg.end), "text": seg_text}
            )
        if not seg.words:
            continue
        for w in seg.words:
            token = (w.word or "").strip()
            if not token:
                continue
            timed_words.append((token, float(w.start), float(w.end)))

    if not timed_words:
        raise RuntimeError("Whisper returned no word timestamps")

    timed_words = _snap_karaoke_to_zero(
        timed_words,
        enabled=bool(cap.get("karaoke_snap_to_zero", True)),
        max_lead=float(cap.get("karaoke_max_lead_sec", 0.45)),
    )

    scene_max = float((cfg.get("media") or {}).get("scene_max_sec", 4.0))
    if raw_beats:
        beats = _merge_beats(raw_beats, max_dur=scene_max)
    elif script_path and script_path.exists():
        beats = _beats_from_script(script_path, duration)
    else:
        beats = []
        for i in range(0, len(timed_words), words_per_line):
            group = timed_words[i : i + words_per_line]
            beats.append(
                {
                    "start": group[0][1],
                    "end": group[-1][2],
                    "text": " ".join(t[0] for t in group),
                }
            )

    narration = ""
    if script_path and script_path.exists():
        narration = script_path.read_text(encoding="utf-8")
        hook_text = _first_sentence(narration)
    else:
        hook_text = str(beats[0]["text"]) if beats else timed_words[0][0]

    hook_seconds = float(cap.get("hook_seconds", 0.0))
    if hook_seconds <= 0:
        hook_text = ""
        hook_end = 0.0
    else:
        first_end = (
            float(beats[0]["end"]) if beats else timed_words[min(5, len(timed_words) - 1)][2]
        )
        hook_end = min(max(hook_seconds, 1.2), first_end, duration * 0.3)

    claim_text = _load_claim_text(script_path, narration, cfg)
    claim_line, claim_end = _claim_event(cfg, claim_text, duration)

    beats_path = out_path.parent / f"{out_path.stem}.beats.json"
    _write_beats_json(
        beats_path,
        beats,
        hook_text=hook_text,
        hook_end=hook_end,
        duration=duration,
        claim_text=claim_text,
        claim_end=claim_end,
    )
    print(
        f"[captions] Beat map: {len(beats)} beats -> {beats_path.name} "
        f"(claim until {claim_end:.2f}s, karaoke from t=0)"
    )

    events: list[str] = []
    if claim_line:
        events.append(claim_line)
        print(f"[captions] Claim card: {claim_text[:60]!r}")
    if hook_text and hook_end > 0:
        events.append(
            f"Dialogue: 1,0:00:00.00,{_ass_timestamp(hook_end)},Hook,,0,0,0,,"
            f"{_ass_escape(hook_text.upper())}"
        )

    for i in range(0, len(timed_words), words_per_line):
        group = timed_words[i : i + words_per_line]
        start = group[0][1]
        end = group[-1][2]
        # Karaoke always from first word — do not delay behind claim card
        if hook_end > 0:
            if end <= hook_end:
                continue
            if start < hook_end:
                group = [(w, max(s, hook_end), e) for (w, s, e) in group if e > hook_end]
                if not group:
                    continue
                start = group[0][1]

        parts: list[str] = []
        for idx, (word, w_start, w_end) in enumerate(group):
            if idx == 0:
                dur_cs = max(int(round((w_end - start) * 100)), 1)
            else:
                prev_end = group[idx - 1][2]
                dur_cs = max(int(round((w_end - prev_end) * 100)), 1)
            parts.append(f"{{\\k{dur_cs}}}{_ass_escape(word.upper())}")

        events.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,"
            f"{' '.join(parts)}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        _write_header(cfg, karaoke=True) + "\n".join(events) + "\n", encoding="utf-8"
    )
    return out_path


def make_captions(
    script_path: Path | None = None, audio_path: Path | None = None
) -> Path | None:
    cfg = load_config()
    if not cfg["captions"]["enabled"]:
        print("[captions] Disabled")
        return None

    scripts_dir = cfg["paths_resolved"]["scripts"]
    audio_dir = cfg["paths_resolved"]["audio"]
    cap_dir = cfg["paths_resolved"]["captions"]
    cap_dir.mkdir(parents=True, exist_ok=True)

    if script_path is None:
        scripts = sorted(
            scripts_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        script_path = scripts[0]

    if audio_path is None:
        audio_path = audio_dir / f"{script_path.stem}.mp3"
        if not audio_path.exists():
            wav = audio_dir / f"{script_path.stem}.wav"
            if wav.exists():
                audio_path = wav
            else:
                raise SystemExit(f"Audio not found: {audio_path}")

    out = cap_dir / f"{script_path.stem}.ass"
    provider = cfg["captions"].get("provider", "whisper")
    if provider == "whisper":
        try:
            write_ass_whisper(audio_path, out, cfg, script_path=script_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[captions] Whisper failed ({exc}); falling back to rough timing")
            write_ass_rough(script_path, audio_path, out, cfg)
    else:
        write_ass_rough(script_path, audio_path, out, cfg)

    print(f"[captions] Wrote {out}")
    return out


if __name__ == "__main__":
    make_captions()
