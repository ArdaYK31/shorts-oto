from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from config_loader import load_config
from fact_gate import FactGateError, assert_source, resolve_claim
from seo_pack import write_seo_pack


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s[:60] or "topic"


def load_queue(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    queue_path = cfg["paths_resolved"]["topics"] / "queue.json"
    with queue_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_scenarios(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios_dir = cfg["paths_resolved"].get("scenarios") or (cfg["_root"] / "scenarios")
    # Prefer broadened History Hooks pack; fall back to legacy american_history.json
    for name in ("history_hooks.json", "american_history.json"):
        path = scenarios_dir / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return list(data.get("scenarios") or [])
    return []


def pick_scenario(cfg: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any] | None:
    scenarios = load_scenarios(cfg)
    if not scenarios:
        return None
    if topic.get("scenario_id"):
        for s in scenarios:
            if s["id"] == topic["scenario_id"]:
                return s
    tid = (topic.get("id") or "").lower()
    topic_blob = f"{tid} {(topic.get('topic') or '')} {(topic.get('title') or '')}".lower()
    want = None
    if any(k in topic_blob for k in ("did-you-know", "did you know", "myth", "older than")):
        want = "did-you-know"
    elif any(k in topic_blob for k in ("traitor", "arnold", "brutus", "caesar")):
        want = "traitor-twist"
    elif any(k in topic_blob for k in ("cold-war", "petrov", "missile", "berlin")):
        want = "cold-war-fact"
    elif any(k in topic_blob for k in ("ww2", "wwii", "mincemeat", "navajo", "onoda")):
        want = "ww2-hook"
    elif any(k in topic_blob for k in ("empire", "rome", "british-tea", "colosseum")):
        want = "empire-twist"
    elif any(k in topic_blob for k in ("death", "rasputin", "genghis")):
        want = "ironic-death"
    elif any(k in topic_blob for k in ("crown", "washington", "refused")):
        want = "refused-power"
    elif any(k in topic_blob for k in ("nobody", "grant", "failed", "lincoln", "napoleon")):
        want = "failed-before-fame"
    elif any(k in topic_blob for k in ("overlook", "smalls", "ludington", "tubman")):
        want = "overlooked-hero"
    else:
        want = scenarios[0]["id"]
    for s in scenarios:
        if s["id"] == want:
            return s
    return scenarios[0]


def pick_topic(cfg: dict[str, Any], topic_id: str | None = None) -> dict[str, Any]:
    queue = load_queue(cfg)
    used_dir = cfg["paths_resolved"]["topics"] / "used"
    used_dir.mkdir(parents=True, exist_ok=True)
    used_ids = {p.stem for p in used_dir.glob("*.json")}

    if topic_id:
        for item in queue:
            if item["id"] == topic_id:
                return item
        raise SystemExit(f"Topic id not found: {topic_id}")

    for item in queue:
        if item["id"] not in used_ids:
            return item
    if not queue:
        raise SystemExit("topics/queue.json is empty")
    return queue[0]


def generate_with_ollama(cfg: dict[str, Any], topic: dict[str, Any], scenario: dict[str, Any] | None) -> str:
    prompt_file = cfg["_root"] / cfg["script"]["prompt_file"]
    system = prompt_file.read_text(encoding="utf-8")
    scenario_hint = ""
    if scenario:
        scenario_hint = (
            f"\nScenario template: {scenario.get('name')} ({scenario.get('id')})\n"
            f"Angle: {scenario.get('angle')}\n"
            f"Hook style: {scenario.get('hook_style')}\n"
            f"Structure: {scenario.get('structure')}\n"
        )
    claim = resolve_claim(topic)
    source = assert_source(topic)
    user = (
        f"Topic: {topic['topic']}\n"
        f"Suggested title vibe: {topic['title']}\n"
        f"MANDATORY CLAIM (must land in sentence 1): {claim}\n"
        f"Verified source (do not invent beyond this): {source}\n"
        f"Hook hint: {topic.get('hook') or claim}\n"
        f"{scenario_hint}"
        "Write the narration now in English only.\n"
        "Structure: Claim → Evidence → Relevance → Twist → Payoff.\n"
        "75–130 words. No filler."
    )
    url = cfg["script"]["ollama_url"].rstrip("/") + "/api/chat"
    payload = {
        "model": cfg["script"]["ollama_model"],
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = requests.post(url, json=payload, timeout=180)
    r.raise_for_status()
    content = r.json()["message"]["content"].strip()
    return content


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w])


def _clamp_script_words(narration: str, min_words: int, max_words: int) -> str:
    """Keep spoken length inside Shorts budget (defense before TTS)."""
    words = narration.split()
    n = len(words)
    if n > max_words:
        cut = " ".join(words[:max_words]).rstrip(".,;:")
        if not cut.endswith("."):
            cut += "."
        print(f"[script] Clamped narration {n} → {max_words} words for Shorts duration")
        return cut
    if n < min_words:
        print(
            f"[script] WARN word count {n} < target min {min_words} "
            f"(proceeding; prefer fuller Claim→Payoff next topic)"
        )
    return narration.strip()


def generate_script(topic_id: str | None = None) -> Path:
    cfg = load_config()
    # Enforce English content language
    if cfg.get("project", {}).get("language", "en") != "en":
        print("[script] Warning: project.language forced to en for video content")
    topic = pick_topic(cfg, topic_id)
    scenario = pick_scenario(cfg, topic)

    # P0 fact gate — before any TTS / media spend
    try:
        source = assert_source(topic)
    except FactGateError as exc:
        print(str(exc))
        raise SystemExit(2) from exc

    claim = resolve_claim(topic)
    provider = cfg["script"]["provider"]

    if provider == "ollama":
        try:
            narration = generate_with_ollama(cfg, topic, scenario)
        except Exception as exc:  # noqa: BLE001
            print(f"[script] Ollama failed ({exc}); falling back to template.")
            narration = topic["fallback_script"]
    else:
        narration = topic["fallback_script"]

    script_cfg = cfg.get("script") or {}
    min_words = int(script_cfg.get("target_words_min", 75))
    max_words = int(script_cfg.get("target_words_max", 130))
    narration = _clamp_script_words(str(narration).strip(), min_words, max_words)
    # Re-resolve claim against final narration if topic.claim empty
    claim = resolve_claim(topic, narration)

    scripts_dir = cfg["paths_resolved"]["scripts"]
    scripts_dir.mkdir(parents=True, exist_ok=True)
    stem = topic["id"]
    txt_path = scripts_dir / f"{stem}.txt"
    meta_path = scripts_dir / f"{stem}.meta.json"
    txt_path.write_text(narration.strip() + "\n", encoding="utf-8")
    meta = {
        "id": topic["id"],
        "title": topic["title"],
        "topic": topic["topic"],
        "language": "en",
        "claim": claim,
        "hook": topic.get("hook") or claim,
        "source": source,
        "keywords": topic.get("keywords", []),
        "search_queries": topic.get("search_queries", []),
        "wikimedia_titles": topic.get("wikimedia_titles", []),
        "pd_fallback_urls": topic.get("pd_fallback_urls", []),
        "scenario_id": scenario["id"] if scenario else topic.get("scenario_id"),
        "provider": provider,
        "script_file": str(txt_path.name),
        "word_count": _word_count(narration),
        "us_audience_score": topic.get("us_audience_score"),
        "series_hint": (cfg.get("project") or {}).get("series") or "History Hooks",
        "viral_structure": ["claim", "evidence", "relevance", "twist", "payoff"],
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    write_seo_pack(topic, narration, scenario_id=meta.get("scenario_id"), meta=meta)
    print(
        f"[script] Wrote {txt_path} (English) words={meta['word_count']} "
        f"claim={claim[:60]!r} source_ok=1"
    )
    return txt_path


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--topic-id", default=None)
    args = p.parse_args()
    generate_script(args.topic_id)
