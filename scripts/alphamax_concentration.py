#!/usr/bin/env python3
"""Independent AlphaMax concentration research CLI (never an order generator)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.concentration import ConcentrationPolicy, allocate_concentration


def evaluate(path):
    source = Path(path)
    if not source.is_file():
        return {
            "status": "BLOCKED",
            "reason": "AUDITED_CONCENTRATION_FORECAST_FILE_MISSING",
            "weights": [], "cash_weight": 1.0, "buy_signal": False
        }
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("FORECAST_ENVELOPE_MUST_BE_OBJECT")
        policy = ConcentrationPolicy(**payload.get("policy", {}))
        return allocate_concentration(
            payload.get("candidates"), payload.get("scenarios"),
            payload.get("evidence"),
            cash_net_return_12m=payload.get("cash_net_return_12m", 0.0),
            policy=policy,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "BLOCKED", "reason": "INVALID_CONCENTRATION_INPUT:" + str(exc),
                "weights": [], "cash_weight": 1.0, "buy_signal": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path,
        default=ROOT / "alphamax/datasets/production/concentration.json",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = json.dumps(evaluate(args.input), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
