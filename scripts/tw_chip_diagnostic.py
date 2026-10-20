#!/usr/bin/env python3
"""As-of-safe institutional/TDCC joins. Never promotes a stock to A+."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# Supports both 'python scripts/tw_chip_diagnostic.py' and unittest imports.
REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT)
from scripts.tw_institutional_retreat import assess_retreat, load_issued_shares

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def validate_archive(receipt):
    raw_path = Path(receipt["raw_archive"])
    normalized_path = Path(receipt["normalized_path"])
    packed = raw_path.read_bytes()
    if digest(packed) != receipt["raw_gzip_sha256"]:
        raise ValueError("RAW_ARCHIVE_HASH_MISMATCH: " + str(raw_path))
    if digest(gzip.decompress(packed)) != receipt["raw_sha256"]:
        raise ValueError("RAW_PAYLOAD_HASH_MISMATCH: " + str(raw_path))
    normalized = normalized_path.read_bytes()
    if digest(normalized) != receipt["normalized_sha256"]:
        raise ValueError("NORMALIZED_HASH_MISMATCH: " + str(normalized_path))
    rows = json.loads(normalized)
    if len(rows) != receipt["rows"]:
        raise ValueError("NORMALIZED_ROW_COUNT_MISMATCH")
    return rows

def dated_sets(root, family, asof, limit=65):
    root = Path(root) / family
    records = []
    errors = []
    if not root.exists():
        return records, errors
    candidate_days = sorted(root.glob("????-??-??/receipt.json"), reverse=True)
    for receipt_path in candidate_days:
        day = receipt_path.parent.name
        try:
            iso = dt.date.fromisoformat(day).isoformat()
            if iso > asof:
                continue  # strict PIT: never use future source dates
            manifest = read_json(receipt_path)
            if manifest["date"] != day:
                raise ValueError("RECEIPT_DATE_MISMATCH")
            if family == "institutional":
                if set(manifest["markets"]) != {"TWSE", "TPEX"}:
                    raise ValueError("NOT_A_COMPLETE_TWO_MARKET_SNAPSHOT")
                items = []
                for market in ("TWSE", "TPEX"):
                    rec = manifest["markets"][market]
                    if rec["data_date"] != day or rec["market"] != market:
                        raise ValueError("SOURCE_IDENTITY_DATE_MISMATCH")
                    items.extend(validate_archive(rec))
                if len({(x["market"], x["code"]) for x in items}) != len(items):
                    raise ValueError("DUPLICATE_MARKET_CODE")
                records.append((day, {(r["market"], r["code"]): r for r in items}))
            elif family == "ownership":
                rec = manifest["receipt"]
                if rec["data_date"] != day or rec["market"] != "TDCC":
                    raise ValueError("TDCC_SOURCE_IDENTITY_MISMATCH")
                items = validate_archive(rec)
                if len({x["code"] for x in items}) != len(items):
                    raise ValueError("DUPLICATE_TDCC_CODE")
                records.append((day, {r["code"]: r for r in items}))
            else:
                raise ValueError("UNKNOWN_SOURCE_FAMILY")
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            errors.append({"path": receipt_path.as_posix(), "reason": str(exc)})
        if len(records) >= limit:
            break
    return records, errors

def flows(series, issuer_key, n):
    """Exactly n certified dated sessions; never fill missing stock rows with zero."""
    if len(series) < n:
        return None
    observations = [snapshot.get(issuer_key) for _, snapshot in series[:n]]
    if any(row is None for row in observations):
        return None
    return {
        "foreign_ex_dealer_net_shares": sum(r["foreign_ex_dealer_net_shares"] for r in observations),
        "trust_net_shares": sum(r["trust_net_shares"] for r in observations),
        "dealer_net_shares": sum(r["dealer_net_shares"] for r in observations),
        "official_total_net_shares": sum(r["official_total_net_shares"] for r in observations),
        "first_session": series[n-1][0],
        "last_session": series[0][0],
        "sessions": n,
    }

def join_market_codes(queue, reference_price_path=None):
    universe = queue.get("queues", []) + queue.get("normalized_not_yet_modeled", [])
    code_to_market = {}
    if reference_price_path is not None and Path(reference_price_path).exists():
        for row in read_json(reference_price_path):
            code_to_market.setdefault(str(row["code"]), set()).add(row["market"])
    result = []
    for stock in universe:
        code = str(stock["code"])
        market = stock.get("market")
        if not market:
            matches = code_to_market.get(code, set())
            market = next(iter(matches)) if len(matches) == 1 else None
        result.append(dict(code=code, market=market, name=stock.get("name"),
                           issuer_research_lane=stock.get("lane"),
                           issuer_certification="NOT_CERTIFIED"))
    keys = [(r["market"], r["code"]) for r in result if r["market"]]
    if len(keys) != len(set(keys)):
        raise ValueError("DUPLICATE_MARKET_CODE_IN_UNIVERSE")
    return result

def summarize(queue, asof, inst, ownership, base_rows, errors, share_master=None):
    if len(queue.get("queues", [])) + len(queue.get("normalized_not_yet_modeled", [])) != queue.get("tracked_issuer_universe", queue.get("normalized_financial_issuers")):
        raise ValueError("UNIVERSE_COUNT_NOT_RECONCILED")
    current_inst = inst[0][1] if inst and inst[0][0] == asof else {}
    current_own = ownership[0][1] if ownership and (dt.date.fromisoformat(asof) - dt.date.fromisoformat(ownership[0][0])).days <= 10 else {}
    previous_own = ownership[1][1] if len(ownership) >= 2 else {}
    share_master = share_master or {}
    annotate = []
    for item in base_rows:
        market, code = item["market"], item["code"]
        intraday = current_inst.get((market, code)) if market else None
        tdcc = current_own.get(code)
        two_weeks = previous_own.get(code)
        row = dict(item)
        row["institutional_asof"] = intraday["date"] if intraday else None
        row["institutional_day_net_shares"] = {k: intraday[k] for k in
            ("foreign_ex_dealer_net_shares", "trust_net_shares", "dealer_net_shares", "official_total_net_shares")} if intraday else None
        row["institutional_5d"] = flows(inst, (market, code), 5) if intraday else None
        row["institutional_20d"] = flows(inst, (market, code), 20) if intraday else None
        row["institutional_60d"] = flows(inst, (market, code), 60) if intraday else None
        row["institutional_retreat_20d"] = assess_retreat(row["institutional_20d"], share_master.get((market, code)))
        row["tdcc_level_12_15_pct"] = tdcc["level_12_15_pct"] if tdcc else None
        row["tdcc_weekly_change_pp"] = (round(tdcc["level_12_15_pct"] - two_weeks["level_12_15_pct"], 4)
                                        if tdcc and two_weeks else None)
        row["chip_evidence_status"] = ("PENDING_SOURCE_OR_HISTORY" if
            not (row["institutional_60d"] and row["tdcc_weekly_change_pp"] is not None)
            else "OBSERVED_CHIP_HISTORY_NOT_A_CERTIFICATION")
        annotate.append(row)
    stats = Counter(r["chip_evidence_status"] for r in annotate)
    return {
        "asof_price_date": asof,
        "model": queue.get("model"),
        "financial_issuer_count": queue.get("normalized_financial_issuers"),
        "tracked_issuer_count": len(annotate),
        "issuer_rows_are_tracked_not_certified": True,
        "dated_institutional_snapshots_through_asof": len(inst),
        "dated_tdcc_snapshots_through_asof": len(ownership),
        "matched_current_institutional": sum(bool(r["institutional_day_net_shares"]) for r in annotate),
        "matched_current_tdcc": sum(r["tdcc_level_12_15_pct"] is not None for r in annotate),
        "five_day_complete": sum(r["institutional_5d"] is not None for r in annotate),
        "twenty_day_complete": sum(r["institutional_20d"] is not None for r in annotate),
        "sixty_day_complete": sum(r["institutional_60d"] is not None for r in annotate),
        "ownership_change_complete": sum(r["tdcc_weekly_change_pp"] is not None for r in annotate),
        "status_counts": dict(stats),
        "source_audit_failures": errors,
        "institutional_retreat_counts": dict(Counter(r["institutional_retreat_20d"]["status"] for r in annotate)),
        "institutional_retreat_20d_is_review_only": True,
        "PIT_issuer_master_certified": False,
        "PIT_publication_audit_complete": False,
        "formal_Aplus_count_derived_from_chip": 0,
        "official_marketwide_chip_certified": False,
        "ranking_safe": False,
        "interpretation": "Institutional retreat watch requires 20 dated observations and eligible dated issued-share denominator; >=0.30% net trust selling triggers research review only. Incomplete official session calendar or fundamental corroboration cannot be called a certified warning, insider information, automatic Exit or A+ change. TDCC grades 12-15 are not identified insiders.",
        "stocks": annotate,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="tw-market-data/rankings/universe_verification_queue.json")
    parser.add_argument("--research", default="tw-market-data/rankings/latest_research.json")
    parser.add_argument("--chip-dir", default="tw-market-data/chip")
    parser.add_argument("--output", default="tw-market-data/rankings/chip_coverage.json")
    args = parser.parse_args()
    queue = read_json(args.queue)
    research = read_json(args.research)
    asof = research["asof_price_date"]
    p = Path("tw-market-data/prices") / (asof + ".json")
    issuer_list = join_market_codes(queue, p)
    institutional, errors1 = dated_sets(args.chip_dir, "institutional", asof)
    tdcc, errors2 = dated_sets(args.chip_dir, "ownership", asof)
    share_master = {}
    try:
        share_master = load_issued_shares("tw-market-data", asof)
    except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
        errors2.append({"path": "tw-market-data/evidence/v880/manifest.json",
                        "reason": "SHARE_MASTER_UNAVAILABLE: " + str(exc)})
    report = summarize(queue, asof, institutional, tdcc, issuer_list, errors1 + errors2, share_master)
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("asof_price_date", "financial_issuer_count",
                                            "matched_current_institutional", "matched_current_tdcc",
                                            "five_day_complete", "twenty_day_complete",
                                            "sixty_day_complete", "official_marketwide_chip_certified")},
                     ensure_ascii=False))

if __name__ == "__main__":
    main()
