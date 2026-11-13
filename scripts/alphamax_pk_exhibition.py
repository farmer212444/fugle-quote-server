#!/usr/bin/env python3
"""Inspect frozen exhibition PK with official snapshots; never report a trading winner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.pk_exhibition import observed_quotes, evidence_scorecard, PKContractError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, default=ROOT / "alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "tw-market-data/prices/latest_manifest.json")
    parser.add_argument("--snapshot", type=Path, help="Official archived JSON quote array, preferably from the exact main-branch commit as manifest")
    parser.add_argument("--execution-evidence", type=Path, help="OPTIONAL unverified 21/63/126/252-session investor total-return evidence; NOT auto-approved")
    parser.add_argument("--output", type=Path, default=Path("alphamax-pk-observation.json"))
    args = parser.parse_args()

    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    src = args.snapshot or ROOT / manifest["path"]
    if not src.is_file():
        out = {
            "status": "BLOCKED_PRICE_SNAPSHOT_NOT_IN_CHECKOUT",
            "requested_snapshot": str(src),
            "manifest_date": manifest.get("date"),
            "official_winner": None,
            "note": "Do not silently reuse the reference price snapshot or invent prices.",
        }
    else:
        rows = json.loads(src.read_text(encoding="utf-8"))
        diagnostic = observed_quotes(freeze, rows, manifest["date"], manifest)
        out = {"status": "DIAGNOSTIC_ONLY_NOT_INVESTABLE",
               "observation": diagnostic, "unverified_evidence_scorecard": None,
               "official_winner": None}
        if args.execution_evidence is not None:
            source = json.loads(args.execution_evidence.read_text(encoding="utf-8"))
            out["unverified_evidence_scorecard"] = evidence_scorecard(freeze, source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": out["status"],
        "official_winner": None,
        "observation_date": out.get("observation", {}).get("observation_price_date"),
        "alpha_quote_coverage": out.get("observation", {}).get("lanes", {}).get("alpha_lane", {}).get("quote_coverage"),
        "v8_quote_coverage": out.get("observation", {}).get("lanes", {}).get("v8_lane", {}).get("quote_coverage"),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (PKContractError, ValueError, KeyError, OSError) as exc:
        print("PK_EVIDENCE_BLOCKED: " + str(exc), file=sys.stderr)
        sys.exit(2)
