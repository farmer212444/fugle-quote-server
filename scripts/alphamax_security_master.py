#!/usr/bin/env python3
"""Capture current official issuer rosters as an auditable research artifact.

Never use any current-only company profile to backfill a historical stock
universe. No trading signal or purchase recommendation is generated.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from alphamax.security_master import capture_profiles


def run(root, output):
    root, output = Path(root), Path(output)
    try:
        latest = json.loads((root / "tw-market-data/prices/latest_manifest.json")
                            .read_text(encoding="utf-8"))
        quotes = json.loads((root / "tw-market-data/prices" / (latest["date"] + ".json"))
                            .read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        quotes = None
        quote_failure = str(exc)[:220]
    else:
        quote_failure = None
    try:
        report = capture_profiles(output, quote_rows=quotes)
        if quote_failure:
            report["quote_readiness"] = "BLOCKED_PRICE_SNAPSHOT_UNAVAILABLE"
            report["quote_failure"] = quote_failure
        return {k: v for k, v in report.items()}
    except (OSError, KeyError, TypeError, ValueError, UnicodeError) as exc:
        report = {
            "status": "BLOCKED_PROFILE_INTAKE_ERROR",
            "reason": str(exc)[:500], "profile_count": 0,
            "historical_PIT_universe_approved": False,
            "investment_certified": False,
        }
        output.mkdir(parents=True, exist_ok=True)
        (output / "capture-manifest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, default=ROOT / "alphamax-profile-capture")
    args = p.parse_args()
    result = run(args.repo_root, args.output_dir)
    compact = {k: v for k, v in result.items()
               if k in ("status", "profile_count", "sources", "attempts",
                        "quote_crosscheck", "quote_readiness", "blocking_reasons",
                        "historical_PIT_universe_approved", "investment_certified", "reason")}
    print(json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
