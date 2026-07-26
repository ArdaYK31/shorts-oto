from __future__ import annotations

import json

import re

import subprocess

from pathlib import Path

from config_loader import load_config

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

def _subdivide_long_beat(beat: dict, max_dur: float, target: float = 3.5) -> list[dict]:

    """Split a beat longer than max_dur into ~target-second chunks (never > max_dur)."""

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

    # Force time/word split — prefer more scene changes over lingering stills

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

    max_dur: float = 5.0,

) -> list[dict]:

    """Merge short Whisper segments; never keep a beat longer than max_dur (5s)."""

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

        final.extend(_subdivide_long_beat(beat, max_dur=max_dur, target=3.5))

    return final

def _write_beats_json(

    out_path: Path,

    beats: list[dict],

    *,

    hook_text: str,

    hook_end: float,

    duration: float,

) -> Path:

    payload = {

        "duration": duration,

        "hook_text": hook_text,

        "hook_end": hook_end,

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

    return _merge_beats(beats)

def _write_header(cfg: dict, karaoke: bool = True) -> str:

    font_size = int(cfg["captions"]["font_size"])

    hook_size = int(cfg["captions"].get("hook_font_size", max(font_size + 22, 90)))

    margin_v = int(cfg["captions"]["margin_v"])

    hook_margin_v = int(cfg["captions"].get("hook_margin_v", 720))

    primary = cfg["captions"]["primary_color"]

    highlight = cfg["captions"].get("highlight_color", "&H0000FFFF")

    hook_color = cfg["captions"].get("hook_color", "&H0000D7FF")

    outline_c = cfg["captions"]["outline_color"]

    outline = int(cfg["captions"]["outline"])

    bold = -1 if cfg["captions"]["bold"] else 0

    secondary = highlight if karaoke else "&H000000FF"

    return f"""[Script Info]

ScriptType: v4.00+

PlayResX: {cfg['project']['width']}

PlayResY: {cfg['project']['height']}

WrapStyle: 0

[V4+ Styles]

Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding

Style: Default,Arial,{font_size},{primary},{secondary},{outline_c},&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},2,2,80,120,{margin_v},1

Style: Hook,Arial,{hook_size},{hook_color},{secondary},{outline_c},&H80000000,-1,0,0,0,100,100,0,0,1,{outline + 1},3,2,60,90,{hook_margin_v},1

[Events]

Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text

"""

def write_ass_rough(script_path: Path, audio_path: Path, out_path: Path, cfg: dict) -> Path:

    text = script_path.read_text(encoding="utf-8").strip()

    words = _split_words(text)

    duration = _ffprobe_duration(audio_path)

    if not words:

        raise SystemExit("Empty script for captions")

    beats = _beats_from_script(script_path, duration)

    hook_text = _first_sentence(text)

    hook_end = min(float(cfg["captions"].get("hook_seconds", 2.0)), duration * 0.25)

    if beats:

        hook_end = min(max(hook_end, float(beats[0]["end"]) * 0.55), float(beats[0]["end"]))

    beats_path = out_path.parent / f"{out_path.stem}.beats.json"

    _write_beats_json(beats_path, beats, hook_text=hook_text, hook_end=hook_end, duration=duration)

    chunk_size = int(cfg["captions"].get("words_per_line", 4))

    chunks = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]

    n = len(chunks)

    lead = hook_end if hook_text else 0.15

    usable = max(duration - lead, 0.5)

    per = usable / n

    events: list[str] = []

    if hook_text:

        events.append(

            f"Dialogue: 1,0:00:00.00,{_ass_timestamp(hook_end)},Hook,,0,0,0,,{_ass_escape(hook_text)}"

        )

    for i, chunk in enumerate(chunks):

        start = lead + i * per

        end = lead + (i + 1) * per

        events.append(

            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,{_ass_escape(chunk)}"

        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(_write_header(cfg, karaoke=False) + "\n".join(events) + "\n", encoding="utf-8")

    return out_path

def write_ass_whisper(audio_path: Path, out_path: Path, cfg: dict, script_path: Path | None = None) -> Path:

    from faster_whisper import WhisperModel

    model_name = cfg["captions"].get("whisper_model", "base.en")

    device = cfg["captions"].get("whisper_device", "cpu")

    compute = cfg["captions"].get("whisper_compute_type", "int8")

    words_per_line = int(cfg["captions"].get("words_per_line", 4))

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

            raw_beats.append({"start": float(seg.start), "end": float(seg.end), "text": seg_text})

        if not seg.words:

            continue

        for w in seg.words:

            token = (w.word or "").strip()

            if not token:

                continue

            timed_words.append((token, float(w.start), float(w.end)))

    if not timed_words:

        raise RuntimeError("Whisper returned no word timestamps")

    if raw_beats:

        beats = _merge_beats(raw_beats)

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

    if script_path and script_path.exists():

        hook_text = _first_sentence(script_path.read_text(encoding="utf-8"))

    else:

        hook_text = str(beats[0]["text"]) if beats else timed_words[0][0]

    hook_seconds = float(cfg["captions"].get("hook_seconds", 2.0))

    first_end = float(beats[0]["end"]) if beats else timed_words[min(5, len(timed_words) - 1)][2]

    hook_end = min(max(hook_seconds, 1.2), first_end, duration * 0.3)

    beats_path = out_path.parent / f"{out_path.stem}.beats.json"

    _write_beats_json(beats_path, beats, hook_text=hook_text, hook_end=hook_end, duration=duration)

    # ASCII-only log (Windows cp1254 consoles choke on arrows)

    print(f"[captions] Beat map: {len(beats)} beats -> {beats_path.name} (hook until {hook_end:.2f}s)")

    events: list[str] = []

    if hook_text:

        events.append(

            f"Dialogue: 1,0:00:00.00,{_ass_timestamp(hook_end)},Hook,,0,0,0,,{_ass_escape(hook_text)}"

        )

    for i in range(0, len(timed_words), words_per_line):

        group = timed_words[i : i + words_per_line]

        start = group[0][1]

        end = group[-1][2]

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

            parts.append(f"{{\\k{dur_cs}}}{_ass_escape(word)}")

        events.append(

            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,{' '.join(parts)}"

        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(_write_header(cfg, karaoke=True) + "\n".join(events) + "\n", encoding="utf-8")

    return out_path

def make_captions(script_path: Path | None = None, audio_path: Path | None = None) -> Path | None:

    cfg = load_config()

    if not cfg["captions"]["enabled"]:

        print("[captions] Disabled")

        return None

    scripts_dir = cfg["paths_resolved"]["scripts"]

    audio_dir = cfg["paths_resolved"]["audio"]

    cap_dir = cfg["paths_resolved"]["captions"]

    cap_dir.mkdir(parents=True, exist_ok=True)

    if script_path is None:

        scripts = sorted(scripts_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)

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
