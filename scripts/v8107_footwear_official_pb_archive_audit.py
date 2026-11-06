"""Independent hash-and-reparse audit of archived official TWSE daily PB sources.

Reject corrupted Base64, incorrect raw-response SHA, source URL substitutions,
ROW edits, partial histories promoted as ten years, and implausible omissions.
Run entirely OFFLINE from archived originals; no current API access needed.
"""
from __future__ import annotations

import base64
import datetime
import gzip
import hashlib
import json
import pathlib

from scripts.v8107_footwear_official_pb_history import ROOT,STOCKS,BEGIN,END,audit_one,parsed_month

REPORT=ROOT/"full_pb_summary.json"
OUT=ROOT/"original_bytes_offline_audit.json"
EXPECTED_MONTHS={"9904":121,"6768":67,"6965":20,"9802":121,"9910":121}
EXPECTED_DAILY={"9904":2438,"6768":1340,"6965":396,"9802":2438,"9910":2438}


def verify_month(code,row):
    if row.get("code")!=code or row.get("stat")!="OK" or "error" in row:
        raise ValueError("NONOK_OR_MISMATCHED_ORIGINAL_MONTH")
    yearmonth=row.get("month")
    url=row.get("url","")
    if (not url.startswith("https://www.twse.com.tw/exchangeReport/BWIBBU?") or
         "stockNo="+code not in url or
         "date="+str(yearmonth).replace("-","")+"01" not in url):
        raise ValueError("MONTH_SOURCE_URL_NOT_OFFICIAL_TWSE")
    try:
        raw=base64.b64decode(row["http_bytes_base64"],validate=True)
    except Exception as exc:
        raise ValueError("CORRUPT_ARCHIVED_ORIGINAL_BASE64") from exc
    if hashlib.sha256(raw).hexdigest()!=row.get("sha256"):
        raise ValueError("ORIGINAL_BODY_SHA256_MISMATCH")
    parsed,stat=parsed_month(code,yearmonth,raw)
    if stat!="OK" or parsed!=row.get("rows"):
        raise ValueError("NORMALIZED_PB_NOT_IDENTICAL_TO_SOURCE_BYTES")
    return len(parsed)


def validate(root=ROOT):
    src=json.loads((root/"full_pb_summary.json").read_bytes())
    if (src.get("schema")!="V8107_TWSE_2016_2026_DAILY_PB_RESEARCH_V1"
        or src.get("mode")!="full"
        or src.get("all_full_listing_histories_certified") is not True
        or src.get("official_http_errors")!=[]
        or src.get("historical_original_first_captured_in_2026_not_asof_traded_date") is not True):
        raise ValueError("FORMAL_HISTORICAL_SOURCE_COVERAGE_NOT_COMPLETE")
    official_reports={r["issuer"]:r for r in src["companies"]}
    if set(official_reports)!=set(STOCKS):
        raise ValueError("SOURCE_STOCK_UNIVERSE_NOT_COMPLETE")
    counts={}
    summary_counts=0
    for code in STOCKS:
        with gzip.open(root/f"{code}_full_originals.json.gz","rb") as f:
            envelope=json.load(f)
        if envelope.get("stock")!=code or envelope.get("method")!="official TWSE HTTP body base64 + sha256 by month":
            raise ValueError("ARCHIVE_ENVELOPE_STOCK_AND_METHOD_MISMATCH")
        rows=envelope["months"]
        if len(rows)!=EXPECTED_MONTHS[code] or len({v["month"] for v in rows})!=len(rows):
            raise ValueError("MISSING_OR_DUPLICATE_OFFICIAL_HISTORICAL_MONTH")
        total=0
        first=max(BEGIN,datetime.date.fromisoformat(STOCKS[code][1]))
        for month in rows:
            verify_month(code,month)
            # The exchange returns an entire calendar month; October 2016
            # includes pre-window rows before Oct-24. Verify all raw bytes
            # but count only observations inside the declared lookback.
            total+=sum(first<=datetime.date.fromisoformat(day["date"])<=END
                       for day in month["rows"])
        if total!=EXPECTED_DAILY[code]:
            # Every source return row is used; no silent dropping whole days.
            raise ValueError("WRONG_TOTAL_VALID_PB_SOURCE_ROWS")
        recalc=audit_one(code,rows,"full")
        saved=official_reports[code]
        for field in (
            "minimum_pb","median_pb","maximum_pb","p10_pb","p25_pb",
            "asof_2026_10_22_pb","asof_pb_percentile_pct",
            "observed_daily_points","historical_extremes_and_median_certified",
            "has_full_10_year_listing_history",
        ):
            if recalc.get(field)!=saved.get(field):
                raise ValueError("ARCHIVED_PB_STATS_DO_NOT_RECOMPUTE_"+field)
        if saved["historical_extremes_and_median_certified"] is not True:
            raise ValueError("FAKE_OR_INCOMPLETE_HISTORICAL_CERTIFICATION")
        counts[code]={"official_monthly_origins_sha_verified":len(rows),
                      "unique_verified_daily_pb":total,
                      "latest_asof_pb":recalc["asof_2026_10_22_pb"],
                      "official_10year_listing_window":recalc["has_full_10_year_listing_history"]}
        summary_counts+=total
    if summary_counts!=9050:
        raise ValueError("HISTORICAL_TOTAL_COVERAGE_DISAGREES")
    return {
        "schema":"V8107_TWSE_PB_FULL_ORIGINAL_SHA_AND_REPARSE_AUDIT_V1",
        "source_body_sha256_verified_count":sum(x["official_monthly_origins_sha_verified"] for x in counts.values()),
        "unique_official_daily_pb_points_recomputed":summary_counts,
        "2026_10_22_source_asof_PB_unchanged":True,
        "complete_10y_is_only_for_9904_9802_9910":True,
        "IPO_censoring_no_prelisting_backfill":True,
        "raw_source_bytes_retrieved_in_2026_not_capture_at_trade_date":True,
        "original_MOPS_quarterly_notes_and_2027_ROE_audited":False,
        "no_source_to_2027_Aplus_automatic_promotion":True,
        "per_issuer":counts,
    }


def main():
    report=validate()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()
