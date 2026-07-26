"""Monthly AI image spend tracker (~$30 cap). Persists to logs/budget.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _month_key() -> str:
    try:
        now = datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:  # noqa: BLE001
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def budget_path() -> Path:
    p = ROOT / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p / "budget.json"


def load_budget() -> dict[str, Any]:
    path = budget_path()
    month = _month_key()
    default: dict[str, Any] = {
        "month": month,
        "images_generated": 0,
        "estimated_spend_usd": 0.0,
        "cap_usd": 30.0,
        "cost_per_image_usd": 0.006,
        "provider": "fal_flux_schnell",
    }
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    if data.get("month") != month:
        default["cap_usd"] = float(data.get("cap_usd") or 30.0)
        default["cost_per_image_usd"] = float(data.get("cost_per_image_usd") or 0.006)
        return default
    return {**default, **data, "month": month}


def save_budget(data: dict[str, Any]) -> None:
    path = budget_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def apply_config_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge media.ai_api budget fields into tracker state."""
    media = cfg.get("media") or {}
    api = media.get("ai_api") or {}
    budget_cfg = api.get("budget") or {}
    state = load_budget()
    if "monthly_cap_usd" in budget_cfg:
        state["cap_usd"] = float(budget_cfg["monthly_cap_usd"])
    if "cost_per_image_usd" in budget_cfg:
        state["cost_per_image_usd"] = float(budget_cfg["cost_per_image_usd"])
    if api.get("backend"):
        state["provider"] = str(api.get("backend"))
    return state


def remaining_usd(cfg: dict[str, Any] | None = None) -> float:
    state = apply_config_defaults(cfg or {})
    return max(0.0, float(state["cap_usd"]) - float(state["estimated_spend_usd"]))


def can_afford(count: int, cfg: dict[str, Any] | None = None) -> bool:
    state = apply_config_defaults(cfg or {})
    need = count * float(state["cost_per_image_usd"])
    return float(state["estimated_spend_usd"]) + need <= float(state["cap_usd"]) + 1e-9


def record_images(count: int, cfg: dict[str, Any] | None = None, actual_cost: float | None = None) -> dict[str, Any]:
    state = apply_config_defaults(cfg or {})
    cost = float(actual_cost) if actual_cost is not None else count * float(state["cost_per_image_usd"])
    state["images_generated"] = int(state.get("images_generated") or 0) + count
    state["estimated_spend_usd"] = round(float(state.get("estimated_spend_usd") or 0) + cost, 4)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_budget(state)
    print(
        f"[budget] +{count} images (~${cost:.4f}) | "
        f"month={state['month']} spent=${state['estimated_spend_usd']:.4f} "
        f"/ ${state['cap_usd']:.2f}"
    )
    return state
