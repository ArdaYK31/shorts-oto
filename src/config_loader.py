from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or (ROOT / "config.yaml")
    with cfg_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Resolve relative paths against project root
    paths = data.get("paths", {})
    resolved = {}
    for key, value in paths.items():
        p = Path(value)
        resolved[key] = p if p.is_absolute() else ROOT / p
    data["paths_resolved"] = resolved
    data["_root"] = ROOT
    return data
