#!/usr/bin/env python3
"""Import an AUTHORIZED buyback vendor JSON export to quarantine, never to a trading model.

Board resolution dates are not verified public-disclosure timestamps. Completion
numbers are ex-post and are never eligible as announcement-date predictors.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

HEADERS = (
    "candidate_id", "market", "stock_id", "company_name",
    "board_resolution_date", "purpose", "planned_shares",
    "planned_start_date", "planned_end_date", "completed_at_capture",
    "executed_shares_at_capture", "execution_rate_pct_at_capture",
    "actual_disclosure_timestamp", "original_publication_verified",
    "history_complete_verified", "usable_as_announce_signal",
    "usable_as_completion_signal", "source_feed", "source_export_sha256"
)


def nonnegative(value, label, optional=False):
    if value in (None, ""):
        if optional:
            return None
        raise ValueError("MISSING_" + label)
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError("INVALID_" + label) from None
    if not math.isfinite(result) or result < 0:
        raise ValueError("INVALID_" + label)
    return result


def normalize(source, source_sha):
    records = source if isinstance(source, list) else source.get("items") if isinstance(source, dict) else None
    if not isinstance(records, list):
        raise ValueError("BUYBACK_VENDOR_EXPECTED_LIST_OR_ITEMS")
    seen, results, rejected, skipped = set(), [], [], Counter()
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            rejected.append({"source_index":idx,"reason":"NOT_OBJECT"})
            continue
        if record.get("record_type") != "BUYBACK":
            skipped["other_record_type"] += 1
            continue
        market = str(record.get("market","")).upper().strip()
        if market not in ("TWSE","TPEX"):
            skipped["other_market"] += 1
            continue
        try:
            board = date.fromisoformat(str(record["board_resolution_date"]))
        except (KeyError, TypeError, ValueError):
            rejected.append({"source_index":idx,"reason":"INVALID_BOARD_DATE"})
            continue
        if not date(2020,1,1) <= board <= date(2025,12,31):
            skipped["outside_2020_2025"] += 1
            continue
        code = str(record.get("company_code","")).strip()
        purpose = str(record.get("purpose","")).strip()
        if not code or not purpose:
            rejected.append({"source_index":idx,"reason":"MISSING_CODE_OR_PURPOSE"})
            continue
        key = ":".join((market,code,board.isoformat(),purpose))
        if key in seen:
            rejected.append({"source_index":idx,"candidate_id":key,"reason":"DUPLICATED_EVENT"})
            continue
        try:
            planned = nonnegative(record.get("planned_shares"),"PLANNED_SHARES")
            if planned <= 0 or planned != int(planned):
                raise ValueError("NONPOSITIVE_OR_FRACTIONAL_SHARES")
            start = date.fromisoformat(str(record.get("planned_start_date")))
            end = date.fromisoformat(str(record.get("planned_end_date")))
            if not board <= start <= end:
                raise ValueError("INVALID_PLANNED_WINDOW")
            completed = record.get("completed")
            if type(completed) is not bool:
                raise ValueError("INVALID_COMPLETED_BOOLEAN")
            executed = nonnegative(record.get("executed_shares"),"EXECUTED_SHARES",optional=True)
            pct = nonnegative(record.get("execution_rate_pct"),"EXECUTION_RATE",optional=True)
            if completed:
                if executed is None or pct is None:
                    raise ValueError("COMPLETION_OUTCOMES_MISSING")
                if executed != int(executed) or abs(executed/planned*100-pct)>0.15:
                    raise ValueError("COMPLETION_ARITHMETIC_MISMATCH")
                if pct > 100.15:
                    raise ValueError("EXECUTION_RATE_OVER_100")
            elif executed is not None or pct is not None:
                raise ValueError("EX_POST_EXECUTION_FIELDS_IN_OPEN_PROGRAM")
        except (ValueError,TypeError) as exc:
            rejected.append({"source_index":idx,"candidate_id":key,"reason":str(exc)})
            continue
        seen.add(key)
        results.append({
            "candidate_id":key,"market":market,"stock_id":code,
            "company_name":str(record.get("company_name","")),
            "board_resolution_date":board.isoformat(),"purpose":purpose,
            "planned_shares":int(planned),"planned_start_date":start.isoformat(),
            "planned_end_date":end.isoformat(),
            "completed_at_capture":str(completed).lower(),
            "executed_shares_at_capture":"" if executed is None else int(executed),
            "execution_rate_pct_at_capture":"" if pct is None else pct,
            "actual_disclosure_timestamp":"","original_publication_verified":"false",
            "history_complete_verified":"false","usable_as_announce_signal":"false",
            "usable_as_completion_signal":"false","source_feed":"THIRD_PARTY_LICENSED_EXPORT",
            "source_export_sha256":source_sha
        })
    return results,rejected,dict(skipped)


def run(vendor_json, output_dir):
    blob = Path(vendor_json).read_bytes()
    checksum = hashlib.sha256(blob).hexdigest()
    raw = json.loads(blob.decode("utf-8-sig"))
    accepted,rejected,skipped = normalize(raw,checksum)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    with (target/"vendor_buyback_candidates_QUARANTINED.csv").open(
            "w",newline="",encoding="utf-8") as file:
        writer = csv.DictWriter(file,fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(accepted)
    summary={
        "schema":"BUYBACK_VENDOR_QUARANTINE_V1",
        "status":"DATE_ONLY_VENDOR_CANDIDATES_NOT_BACKTEST_EVENTS",
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "input_sha256":checksum,
        "candidates":len(accepted),"rejected":len(rejected),
        "skipped":skipped,"rejections":rejected,
        "verified_disclosure_timestamps":0,
        "certified_historical_universe":False,
        "source_provenance_verified":False,
        "vendor_usage_requires_appropriate_license":True,
        "production_events_written":False,"formal_a_plus_unchanged":True,
        "orders_created":False
    }
    (target/"manifest.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--vendor-json",required=True,
                        help="Authorized JSON export; no vendor API called")
    parser.add_argument("--out",default="/tmp/buyback-vendor-quarantine")
    args=parser.parse_args()
    result=run(args.vendor_json,args.out)
    print(json.dumps({k:result[k] for k in
                      ("status","candidates","rejected","verified_disclosure_timestamps")},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
