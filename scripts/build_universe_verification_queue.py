#!/usr/bin/env python3
"""Generate an honest, restartable market-wide evidence review queue (no certification shortcuts)."""
import argparse
import hashlib
import json
from pathlib import Path

GATES = (
    "original_eight_quarter_statements", "cash_and_working_capital",
    "nonoperating_components", "fully_diluted_shares", "matched_peers_and_cycle",
    "management_promises", "auditor_scope", "tradability", "forecast_bridge",
    "insider_claims", "dividend_window", "point_in_time", "out_of_sample_validation"
)

def build(report, normalized_universe=None, universe_receipts=None):
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
            "code": code, "market": r.get("market"), "name": r.get("name"), "lane": lane,
            "research_upside_pct": upside if eligible else None,
            "certification": "NOT_CERTIFIED",
            "required_gates": list(GATES),
            "review_state": "PENDING_SOURCE_VERIFICATION"
        })
    priority = {"HIGH_UPSIDE_EVIDENCE_REVIEW": 0, "OTHER_VALUED_EVIDENCE_REVIEW": 1, "UNVALUED_INPUT_REPAIR": 2}
    queue.sort(key=lambda x: (priority[x["lane"]], -(x["research_upside_pct"] or 0), x["code"]))

    normalized_queue = []
    if normalized_universe is not None:
        expected = report.get("data_scope", {}).get("normalized_issuers")
        if expected is not None and len(normalized_universe) != expected:
            raise ValueError(f"NORMALIZED_UNIVERSE_COUNT_MISMATCH expected={expected} actual={len(normalized_universe)}")
        model_exact = {(str(r.get("market")), str(r["code"])) for r in rows if r.get("market")}
        model_code_only = {str(r["code"]) for r in rows if not r.get("market")}
        normalized_seen = set()
        for item in normalized_universe:
            code = str(item["code"])
            market = str(item["market"])
            key = (market, code)
            if key in normalized_seen:
                raise ValueError("duplicate normalized issuer identity: " + market + ":" + code)
            normalized_seen.add(key)
            if key in model_exact or code in model_code_only:
                continue
            normalized_queue.append({
                "market": market,
                "code": code,
                "name": item.get("name"),
                "lane": "NORMALIZED_NOT_YET_MODELED",
                "certification": "NOT_CERTIFIED",
                "identity_basis": "NORMALIZED_FINANCIAL_MIRROR_NOT_OFFICIAL_PIT_MASTER",
                "required_gates": list(GATES),
                "review_state": "PENDING_MODEL_INPUT_REPAIR_AND_SOURCE_VERIFICATION"
            })
        normalized_queue.sort(key=lambda x: (x["market"], x["code"]))
        not_modeled = len(normalized_queue)
    else:
        not_modeled = max(0, report.get("data_scope", {}).get("normalized_issuers", 0) - len(rows))

    return {
        "model": report.get("model"), "asof_price_date": report.get("asof_price_date"),
        "source_estimate_vintage": report.get("estimate_vintage"),
        "universe_priced": report.get("data_scope", {}).get("priced_issuers"),
        "normalized_financial_issuers": report.get("data_scope", {}).get("normalized_issuers"),
        "model_issuer_rows": len(rows),
        "not_yet_in_model_count": not_modeled,
        "not_yet_in_model_note": (
            "Identifiers are derived from hashed normalized financial mirrors and remain NOT_CERTIFIED. "
            "They must be reconciled against a dated official PIT issuer master before full coverage can be declared."
            if normalized_universe is not None else
            "Count only; company identifiers must be reconciled against a dated official universe before declaring full coverage."
        ),
        "normalized_universe_identity_receipts": universe_receipts or [],
        "normalized_not_yet_modeled": normalized_queue,
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

def load_normalized_universe(data_root):
    root = Path(data_root)
    identities = {}
    receipts = []
    for path in sorted((root / "fundamentals").glob("*/*_income.json")):
        raw = path.read_bytes()
        obj = json.loads(raw)
        market = str(obj["market"])
        period = str(obj["period"])
        receipts.append({
            "path": path.as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "meaning": "NORMALIZED_MIRROR_IDENTITY_ONLY_NOT_INDEPENDENT_OFFICIAL_PIT_PROOF"
        })
        for row in obj.get("rows", []):
            code = str(row["code"])
            key = (market, code)
            previous = identities.get(key)
            if previous is None or period >= previous["latest_period_seen"]:
                identities[key] = {
                    "market": market,
                    "code": code,
                    "name": row.get("name") or row.get("company_name") or row.get("公司名稱"),
                    "latest_period_seen": period
                }
    return sorted(identities.values(), key=lambda x: (x["market"], x["code"])), receipts

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="tw-market-data/rankings/latest_research.json")
    p.add_argument("--output", default="tw-market-data/rankings/universe_verification_queue.json")
    p.add_argument("--data-root", default="tw-market-data")
    a = p.parse_args()
    report = json.loads(Path(a.input).read_text(encoding="utf-8"))
    identities, receipts = load_normalized_universe(a.data_root)
    result = build(report, identities, receipts)
    path = Path(a.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "counts": result["counts"],
        "model_rows": result["model_issuer_rows"],
        "normalized_not_yet_modeled": result["not_yet_in_model_count"],
        "certified": False
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
