#!/usr/bin/env python3
"""Archive 2020-25 monthly TWSE Taiwan50 TOTAL-RETURN INDEX as research benchmark.

Important: Taiwan50 index != ETF 0050 investable total return. Never populate
buyback_event_backtest.py's 0050_tr_daily.csv from this collector.
Source bytes are collected NOW and do not imply original 2020 capture.
"""
import argparse
import csv
import gzip
import hashlib
import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from scripts.buyback_source_probe import fetch, parse_tai50

def collect(year, out):
    if not isinstance(year, int) or not 2020 <= year <= 2025:
        raise ValueError("YEAR_OUTSIDE_FROZEN_STUDY")
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    items, rows, dates = [], [], set()
    for month in range(1, 13):
        url = "https://www.twse.com.tw/indicesReport/TAI50I?" + urllib.parse.urlencode(
            {"response": "json", "date": f"{year:04d}{month:02d}01"})
        status, actual, payload, error = fetch(url)
        try:
            parsed, reason = parse_tai50(payload, year, month) if payload else ([], "EMPTY_RESPONSE")
        except (ValueError, TypeError, UnicodeError, KeyError) as exc:
            parsed, reason = [], "UNPARSABLE:" + type(exc).__name__
        archive = f"official_original_{year}_{month:02d}.json.gz" if payload else None
        if payload:
            (folder / archive).write_bytes(gzip.compress(payload))
        if any(p["date"] in dates for p in parsed):
            parsed, reason = [], "DUPLICATED_CROSS_MONTH_DATE"
        if reason == "RESPONSE_MONTH_PARSED_NOT_INDEPENDENTLY_AUDITED" and status == 200:
            rows.extend(parsed)
            dates.update(p["date"] for p in parsed)
        items.append({"month": month, "source_url": url, "effective_url": actual,
                      "http_status": status, "status": reason,
                      "rows_accepted": len(parsed) if status == 200 and reason ==
                      "RESPONSE_MONTH_PARSED_NOT_INDEPENDENTLY_AUDITED" else 0,
                      "response_bytes": len(payload),
                      "response_sha256": hashlib.sha256(payload).hexdigest() if payload else None,
                      "raw_archive": archive, "source_error": error})
    rows.sort(key=lambda r:r["date"])
    csvpath = folder / f"taiwan50_index_tr_{year}.csv"
    with csvpath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "taiwan50_total_return_index"])
        writer.writeheader()
        writer.writerows(rows)
    accepted = sum(x["rows_accepted"] > 0 for x in items)
    status = ("MONTHLY_ORIGINALS_COLLECTED_AUDIT_PENDING" if accepted == 12
              else "INCOMPLETE_UNVERIFIED_HISTORICAL_INDEX")
    summary = {"schema": "OFFICIAL_TW50_TR_MONTHLY_ARCHIVE_V1",
               "research_only": True,
               "benchmark_id": "TAIWAN50_TOTAL_RETURN_INDEX_NOT_ETF_0050",
               "captured_at_utc": datetime.now(timezone.utc).isoformat(),
               "historical_dates_are_not_original_capture_timestamps": True,
               "year": year, "expected_months": 12, "accepted_months": accepted,
               "row_count": len(rows), "status": status, "months": items,
               "valid_for_buyback_0050_etf_tr_column": False,
               "formal_a_plus_unchanged": True, "orders_created": False}
    (folder / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("year", "status", "accepted_months",
                                             "row_count", "benchmark_id")},
                     ensure_ascii=False))
    return summary

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int,required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    result=collect(args.year,args.out)
    if result["accepted_months"] != 12:
        raise SystemExit(2)
