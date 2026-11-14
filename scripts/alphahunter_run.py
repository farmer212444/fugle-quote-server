#!/usr/bin/env python3
"""AlphaHunter readiness and research CLI. Refuses to invent production returns."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphahunter import EvidenceError, load_bundle, rank_asof, matured_cohort_diagnostics


def readiness(bundle):
    try:
        manifest, rows = load_bundle(bundle)
    except (EvidenceError, OSError, ValueError) as exc:
        return {"status": "BLOCKED", "reason": str(exc),
                "production_ranking_allowed": False, "official_buy_certification": False}
    return {
        "status": "INPUT_CONTRACT_PASSED_NOT_EXTERNALLY_AUDITED",
        "rows": len(rows),
        "source_receipt_references": len(manifest["source_receipts"]),
        "production_ranking_allowed": False,
        "official_buy_certification": False,
        "note": "SHA and self-declared gates cannot substitute for independent source audits.",
    }


def research(bundle, asof, top_n=10):
    if date.fromisoformat(asof) > date.today():
        raise EvidenceError("ASOF_IN_FUTURE")
    _, rows = load_bundle(bundle)
    ranked = rank_asof(rows, asof, top_n=top_n)
    ranked["diagnostics"] = matured_cohort_diagnostics(rows, asof, top_n=top_n)
    ranked["production_ranking_allowed"] = False
    return ranked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("readiness", "research"))
    parser.add_argument("--bundle", type=Path, default=ROOT / "alphahunter/datasets/production")
    parser.add_argument("--asof", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.command == "readiness":
        result = readiness(args.bundle)
    else:
        if args.asof is None:
            result = {"status": "BLOCKED", "reason": "EXPLICIT_ASOF_REQUIRED",
                      "production_ranking_allowed": False}
        else:
            try:
                result = research(args.bundle, args.asof, args.top_n)
            except (EvidenceError, FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "BLOCKED", "reason": str(exc),
                          "production_ranking_allowed": False, "candidates": []}
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
