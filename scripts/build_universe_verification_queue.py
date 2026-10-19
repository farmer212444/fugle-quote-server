#!/usr/bin/env python3
"""Generate an honest, restartable market-wide evidence review queue (no certification shortcuts)."""
import argparse
import json
from pathlib import Path

GATES = (
    "original_eight_quarter_statements", "cash_and_working_capital",
    "nonoperating_components", "fully_diluted_shares", "matched_peers_and_cycle",
    "management_promises", "auditor_scope", "tradability", "forecast_bridge",
    "insider_claims", "dividend_window", "point_in_time", "out_of_sample_validation"
)

def build(report):
    rows = report.get("all_model_row_summary", [])
    seen = set()
    queue = []
    for r in rows:
        code = str(r["code"])
        if code in seen:
            raise ValueError("duplicate issuer code: " + code)
        seen.add(code)
        upside = r.get("scenario_upside_pct")
        eligible = isinstance(upside, (int, float)) and not isinstance(upside, bool)
        if eligible and upside >= 30:
            lane = "HIGH_UPSIDE_EVIDENCE_REVIEW"
        elif eligible:
            lane = "OTHER_VALUED_EVIDENCE_REVIEW"
        else:
            lane = "UNVALUED_INPUT_REPAIR"
        queue.append({
            "code": code, "name": r.get("name"), "lane": lane,
            "research_upside_pct": upside if eligible else None,
            "certification": "NOT_CERTIFIED",
            "required_gates": list(GATES),
            "review_state": "PENDING_SOURCE_VERIFICATION"
        })
    priority = {"HIGH_UPSIDE_EVIDENCE_REVIEW": 0, "OTHER_VALUED_EVIDENCE_REVIEW": 1, "UNVALUED_INPUT_REPAIR": 2}
    queue.sort(key=lambda x: (priority[x["lane"]], -(x["research_upside_pct"] or 0), x["code"]))
    return {
        "model": report.get("model"), "asof_price_date": report.get("asof_price_date"),
        "source_estimate_vintage": report.get("estimate_vintage"),
        "universe_priced": report.get("data_scope", {}).get("priced_issuers"),
        "normalized_financial_issuers": report.get("data_scope", {}).get("normalized_issuers"),
        "model_issuer_rows": len(rows),
        "not_yet_in_model_count": max(0, report.get("data_scope", {}).get("normalized_issuers", 0) - len(rows)),
        "not_yet_in_model_note": "Count only; company identifiers must be reconciled against a dated official universe before declaring full coverage.",
        "official_full_universe_certified": False,
        "formal_Aplus_count_from_source": report.get("formal_Aplus_count"),
        "source_scope": report.get("ranking_scope"),
        "queues": queue,
        "counts": {lane: sum(x["lane"] == lane for x in queue) for lane in priority},
        "blocking_rules": [
            "Never mark PASS without issuer-specific source, publication time, financial period and document hash.",
            "CB and financing events require effective conversion terms and actual outstanding balances.",
            "Negative operating cash flow triggers working-capital and capex bridge, not automatic rejection.",
            "Do not promote a candidate solely from modeled upside or reconstructed historical data.",
            "Official full-universe certification requires an independently reconciled PIT issuer list."
        ]
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="tw-market-data/rankings/latest_research.json")
    p.add_argument("--output", default="tw-market-data/rankings/universe_verification_queue.json")
    a = p.parse_args()
    report = json.loads(Path(a.input).read_text(encoding="utf-8"))
    result = build(report)
    path = Path(a.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"], "model_rows": result["model_issuer_rows"], "certified": False}, ensure_ascii=False))

if __name__ == "__main__":
    main()
