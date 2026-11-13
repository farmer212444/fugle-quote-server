#!/usr/bin/env python3
"""Report pinned post-freeze exchange-quote-only PK diagnostics, never a winner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.pk_shadow_monitor import PKContractError, shadow_price_only


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, default=ROOT / "alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json")
    parser.add_argument("--entry", type=Path, required=True, help="Original pinned 2026-11-12 quote snapshot bytes")
    parser.add_argument("--manifest", type=Path, required=True, help="Latest official main-branch manifest")
    parser.add_argument("--latest", type=Path, required=True, help="Latest archive snapshot from same main commit as manifest")
    parser.add_argument("--output", type=Path, default=Path("alphamax-pk-shadow-price-only.json"))
    args = parser.parse_args()

    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = shadow_price_only(freeze, args.entry.read_bytes(), args.latest.read_bytes(), manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "entry_price_date": result["entry_price_date"],
        "latest_quote_date": result["last_price_date"],
        "alpha_coverage": result["lanes"]["alpha_lane"]["complete_quote_count"],
        "v8_coverage": result["lanes"]["v8_lane"]["complete_quote_count"],
        "alpha_raw_pct": result["lanes"]["alpha_lane"]["equal_initial_capital_unadjusted_price_change_pct"],
        "v8_raw_pct": result["lanes"]["v8_lane"]["equal_initial_capital_unadjusted_price_change_pct"],
        "0050_raw_pct": result["benchmark_0050"]["raw_price_only_change_pct"],
        "winner": result["official_winner"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, PKContractError) as exc:
        print("SHADOW_PRICE_MONITOR_BLOCKED: " + str(exc), file=sys.stderr)
        sys.exit(2)
