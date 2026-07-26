"""Fact verification gate — require a real source before TTS. Never invent sources."""
from __future__ import annotations

from typing import Any


class FactGateError(Exception):
    """Soft-fail: topic lacks a verifiable source field."""

    def __init__(self, topic_id: str, message: str) -> None:
        self.topic_id = topic_id
        super().__init__(message)


def topic_source(topic: dict[str, Any]) -> str:
    raw = topic.get("source") or topic.get("sources") or ""
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw if str(x).strip()]
        return "; ".join(parts)
    return str(raw).strip()


def assert_source(topic: dict[str, Any], *, min_len: int = 8) -> str:
    """
    Require a non-empty source citation on the topic card.
    Soft-fail (FactGateError) if missing — caller should skip, not invent.
    """
    tid = str(topic.get("id") or "unknown")
    source = topic_source(topic)
    if len(source) < min_len:
        raise FactGateError(
            tid,
            f"[fact_gate] SKIP topic={tid}: missing/too-short 'source' field "
            f"(need a real citation before TTS; do not invent). "
            f"Add source to topics/queue.json and re-run.",
        )
    return source


def resolve_claim(topic: dict[str, Any], narration: str = "") -> str:
    """On-screen claim card text — the fact itself, never a bare 'DID YOU KNOW?'."""
    claim = str(topic.get("claim") or "").strip()
    if not claim:
        hook = str(topic.get("hook") or "").strip()
        claim = hook
    if not claim and narration:
        # First sentence of narration as claim fallback
        import re

        text = re.sub(r"\s+", " ", narration.strip())
        parts = re.split(r"(?<=(?<![A-Z])[.!?])\s+(?=[A-Z\"'])", text, maxsplit=1)
        claim = (parts[0] if parts else text)[:160]
    # Strip empty DYK label — keep the claim body
    stripped = claim
    for prefix in (
        "Did you know? ",
        "Did you know ",
        "DID YOU KNOW? ",
        "DID YOU KNOW ",
    ):
        if stripped.lower().startswith(prefix.lower()):
            stripped = stripped[len(prefix) :].lstrip("?—- ").strip()
            break
    if stripped.upper() in {"DID YOU KNOW", "DID YOU KNOW?", "DYK"}:
        stripped = str(topic.get("title") or topic.get("topic") or claim).strip()
    return (stripped or claim).strip()
