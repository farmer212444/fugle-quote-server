#!/usr/bin/env python3
"""Bounded official 252-session footwear price-source capture, research only.

Read live TWSE STOCK_DAY historical JSON for two footwear issuers and 0050.
Archive the original response, hash, capture timestamp and parsed daily OHLC,
then validate a *contiguous stock-session calendar* using 0050 as a reference.
A past original fetched today is NOT a historical filing publication stamp.
No A+ upgrade, no alpha, no broker fill, no margin/insider official promotion.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.tw_history_backfill import historical_url, parse, request
from scripts.history_archive import archive_original, verify_original, canonical

CODES = ("0050", "9802", "6965")
ISSUERS = ("9802", "6965")
REFERENCE = "2026-10-22"
MONTH_START = "2025-08"
MONTH_END = "2026-10"
N = 252
REPORT = Path("tw-market-data/evidence/v880/insider_reviews/footwear_252_official_price_readiness.json")


def months_between(first=MONTH_START, last=MONTH_END):
    def index(d):
        y, m = [int(n) for n in d.split("-")]
        if not (1 <= m <= 12):
            raise ValueError("INVALID_MONTH")
        return y * 12 + m - 1
    i, e = index(first), index(last)
    if i > e or e-i > 18:
        raise ValueError("UNSUPPORTED_MONTH_RANGE")
    return [f"{n//12:04d}-{n%12+1:02d}" for n in range(i, e+1)]


def snapshot_window(daily_by_code, *, anchor_code="0050", ref_date=REFERENCE,
                    window=N, source_verified_months=None):
    """Only compute price range if all 252 exchange sessions exist for issuer.

    'source_verified_months' represents independently verified, immutable
    official original bytes (pass only AFTER actual verify_original call).
    """
    ref = dt.date.fromisoformat(ref_date)
    if type(window) is not int or window < 10:
        raise ValueError("INVALID_LOOKBACK_SESSIONS")
    if source_verified_months is None:
        return {"status": "PENDING_OFFICIAL_SOURCE_ORIGINALS",
                "signal_created": False, "research_price_candidates": {}}
    for code in CODES:
        if code not in daily_by_code:
            return {"status": "PENDING_SOURCE_CODE_"+code, "signal_created": False,
                    "research_price_candidates": {}}
    checked = {}
    for code in CODES:
        entries = daily_by_code[code]
        bydate = {}
        for row in entries:
            day = row.get("date")
            if (not isinstance(day, str) or dt.date.fromisoformat(day) > ref
                    or day in bydate or
                    not isinstance(row.get("close"), (float, int)) or
                    type(row["close"]) is bool or row["close"] <= 0):
                raise ValueError("INVALID_DUPLICATE_OR_FUTURE_PRICE_ROW")
            if row.get("source_original_verified") is not True:
                return {"status": "PENDING_UNVERIFIED_ROW_ORIGINAL", "signal_created": False,
                        "research_price_candidates": {}}
            if day[:7] not in source_verified_months.get(code, set()):
                return {"status": "PENDING_MONTH_SOURCE_"+code, "signal_created": False,
                        "research_price_candidates": {}}
            bydate[day] = float(row["close"])
        checked[code] = bydate
    reference_days = sorted(checked[anchor_code])
    if len(reference_days) < window or reference_days[-1] != ref_date:
        return {"status": "PENDING_COMPLETE_ANCHOR_252_SESSIONS",
                "known_reference_days": len(reference_days), "signal_created": False,
                "research_price_candidates": {}}
    window_days = reference_days[-window:]
    output = {}
    for code in ISSUERS:
        missing = [day for day in window_days if day not in checked[code]]
        if missing:
            output[code] = {"status": "PENDING_MISSING_EXCHANGE_SESSIONS",
                            "missing_session_count": len(missing),
                            "missing_session_dates": missing[:10],
                            "price_low_window_certified": False}
            continue
        values = [checked[code][d] for d in window_days]
        low, high = min(values), max(values)
        if low == high:
            output[code] = {"status": "PENDING_ZERO_RANGE", "price_low_window_certified": False}
            continue
        frac = (values[-1]-low)/(high-low)
        output[code] = {
            "status": "252_SOURCE_BACKED_UNADJUSTED_CLOSE_RESEARCH_ONLY",
            "window_start": window_days[0], "window_end": window_days[-1],
            "window_sessions": window,
            "range_min_close": low, "range_max_close": high,
            "reference_close": values[-1],
            "range_position": round(frac, 8),
            "provisional_bottom_20pct": frac <= .2,
            "source_backed_unadjusted_prices": True,
            "complete_dividend_and_splits_window_review": False,
            "price_low_window_certified": False,
            "entry_open_and_fillability_verified": False,
        }
    return {"status": "RESEARCH_UNADJUSTED_PRICE_WINDOW_ONLY",
            "ref_date": ref_date, "benchmark_calendar": anchor_code,
            "calendar_window": [window_days[0], window_days[-1]],
            "calendar_sessions": window, "research_price_candidates": output,
            "signal_created": False, "formal_Aplus_changed": False,
            "benchmark_0050_dividend_adjusted_12m_return_certified": False}


def run(*, root=Path("tw-market-data"), ref_date=REFERENCE,
        request_func=request, sleep=.35, out=REPORT):
    root = Path(root)
    months = months_between()
    asof = dt.date.fromisoformat(ref_date)
    if asof > dt.date(2026,10,23):
        raise ValueError("REFERENCE_FUTURE_DATE")
    # Cross-check today's reference closes against independently collected
    # daily official market archive rather than silently trusting a vendor.
    manifest = json.loads((root/"prices/latest_manifest.json").read_bytes())
    if manifest.get("date") != ref_date:
        raise ValueError("REFERENCE_DAILY_MANIFEST_NOT_MATCHING_DATE")
    daily_raw = (root/"prices"/(ref_date+".json")).read_bytes()
    if hashlib.sha256(daily_raw).hexdigest() != manifest["normalized_sha256"]:
        raise ValueError("OFFICIAL_DAILY_MANIFEST_HASH_MISMATCH")
    close_by_code = {r["code"]:float(r["close"]) for r in json.loads(daily_raw)
                     if r.get("market")=="TWSE" and r.get("code") in CODES}
    if set(close_by_code) != set(CODES):
        raise ValueError("MISSING_CURRENT_REFERENCE_ISSUER_OR_ETF")

    records, provenance, attempts = {}, {}, []
    for code in CODES:
        records[code] = []
        provenance[code] = set()
        for month in months:
            url = historical_url(code, month)
            try:
                raw = request_func(url)
                rows = parse(raw, code, month)
                receipt = archive_original(root, "TWSE", f"{code}-{month}", url, raw, rows)
                if verify_original(root, receipt) != raw:
                    raise ValueError("OFFICIAL_ORIGINAL_REVERIFY_CHANGED_BYTES")
                provenance[code].add(month)
                records[code].extend([dict(row,source_original_verified=True)
                                      for row in rows if row["date"] <= ref_date])
                attempts.append({"code":code,"month":month,"status":"ORIGINAL_REPARSED_AND_SHA256_VERIFIED",
                                 "row_count":len(rows),"receipt_path":receipt["receipt_path"],
                                 "original_sha256":receipt["original_response_sha256"]})
            except Exception as exc:
                attempts.append({"code":code,"month":month,"status":"SOURCE_MISSING_RETRY_REQUIRED",
                                 "error":type(exc).__name__+":"+str(exc)[:150]})
            if sleep:
                time.sleep(sleep)
    result = snapshot_window(records, ref_date=ref_date, source_verified_months=provenance)
    for code in CODES:
        actual=[r for r in records[code] if r["date"]==ref_date]
        if len(actual)!=1 or abs(float(actual[0]["close"])-close_by_code[code])>.011:
            result["status"]="REFERENCE_DAILY_CLOSE_MISMATCH_OR_MISSING"
            result["signal_created"]=False
            result["research_price_candidates"]={}
    result["source_data"] = {
        "issuer_universe":"9802_AND_6965_NOT_COMPLETE_FOOTWEAR_SECTOR",
        "capture_method":"OFFICIAL_TWSE_STOCK_DAY_MONTHLY_ORIGINAL_BYTES",
        "latest_daily_official_reference":ref_date,
        "months_requested":months, "attempts":attempts,
        "verified_original_months_by_code":{c:sorted(provenance[c]) for c in CODES},
        "official_price_originals_are_not_historical_disclosure_receipts":True,
        "unadjusted_prices_may_contain_corporate_action_distortions":True,
    }
    result["stock_one_year_vs_0050_win_rate"]=None
    result["historical_13_gates_modified"]=False
    out=Path(out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"price_research":result.get("research_price_candidates"),
                     "originals":{c:len(provenance[c]) for c in CODES},
                     "errors":sum(r["status"]=="SOURCE_MISSING_RETRY_REQUIRED" for r in attempts)},
                     ensure_ascii=False))
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ref-date",default=REFERENCE)
    args=p.parse_args()
    run(ref_date=args.ref_date)


if __name__ == "__main__":
    main()
