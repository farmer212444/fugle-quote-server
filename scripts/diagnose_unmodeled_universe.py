#!/usr/bin/env python3
"""Read-only diagnostic: classify unmodeled issuers without manufacturing financials."""
import argparse
import collections
import json
from pathlib import Path

def summarize(queue):
    missing = queue.get("normalized_not_yet_modeled", [])
    model = queue.get("queues", [])
    if len(missing) != queue.get("not_yet_in_model_count"):
        raise ValueError("Unmodeled count mismatch; fail closed")
    identities = [(str(x.get("market")), str(x.get("code"))) for x in missing]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate market/code in unmodeled queue")
    by_market = dict(sorted(collections.Counter(x[0] for x in identities).items()))
    missing_names = [x for x in missing if not x.get("name")]
    return {
        "model": queue.get("model"),
        "source_estimate_vintage": queue.get("source_estimate_vintage"),
        "financial_universe": queue.get("normalized_financial_issuers"),
        "modeled": len(model),
        "model_rows_meaning": queue.get("model_rows_meaning", "LEGACY_MODEL_ENTRY_ROWS"),
        "comparable_valuation_rows": sum(x.get("lane") in ("HIGH_UPSIDE_EVIDENCE_REVIEW", "OTHER_VALUED_EVIDENCE_REVIEW") for x in model),
        "unvalued_input_repair_rows": sum(x.get("lane")=="UNVALUED_INPUT_REPAIR" for x in model),
        "unmodeled_definition": "NO_TRACKING_RECORD; ZERO_DOES_NOT_MEAN_ALL_VALUATIONS_OR_EVIDENCE_COMPLETE",
        "unmodeled": len(missing),
        "unmodeled_by_market": by_market,
        "unmodeled_missing_name": len(missing_names),
        "unmodeled_identity_source": "NORMALIZED_FINANCIAL_MIRROR_ONLY",
        "official_PIT_master_reconciled": False,
        "issuer_evidence_certified": 0,
        "action": "Match each market/code to dated official issuer master, then classify missing model inputs; no synthetic data or PASS statuses.",
        "status": "DIAGNOSTIC_ONLY_NOT_A_CERTIFICATION"
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="tw-market-data/rankings/universe_verification_queue.json")
    parser.add_argument("--output", default="tw-market-data/rankings/universe_gap_diagnostic.json")
    args = parser.parse_args()
    queue = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = summarize(queue)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
