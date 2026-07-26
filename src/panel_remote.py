"""Lightweight remote panel actions: skip_slot / clear_skip (+ snapshot refresh).

Used by GitHub Actions workflow_dispatch so the status panel can manage
schedule skips without running the full Docker pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_status import (  # noqa: E402
    add_skip_slot,
    clear_skip_slots,
    write_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Atelier panel remote actions")
    parser.add_argument(
        "--action",
        required=True,
        choices=["skip_slot", "clear_skip", "snapshot"],
    )
    parser.add_argument("--skip-date", default="", help="YYYY-MM-DD (Istanbul)")
    parser.add_argument("--skip-time", default="", help="HH:MM e.g. 08:00")
    args = parser.parse_args()

    if args.action == "skip_slot":
        if not args.skip_date or not args.skip_time:
            print("skip_slot requires --skip-date and --skip-time", file=sys.stderr)
            return 2
        data = add_skip_slot(args.skip_date.strip(), args.skip_time.strip())
        print(f"[panel] skip_slot ok {args.skip_date} {args.skip_time}")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.action == "clear_skip":
        data = clear_skip_slots(
            args.skip_date.strip() or None,
            args.skip_time.strip() or None,
        )
        print(
            f"[panel] clear_skip ok date={args.skip_date or '*'} "
            f"time={args.skip_time or '*'}"
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("[panel] snapshot refresh")

    snap = write_snapshot()
    print(f"[panel] latest.json updated_at={snap.get('updated_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
