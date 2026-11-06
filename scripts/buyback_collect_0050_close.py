#!/usr/bin/env python3
"""Monthly ORIGINAL 0050 ETF quotes, not total returns. Buyback research only."""
import argparse
import csv
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from scripts.tw_history_backfill import historical_url, parse, request

def collect(year, destination, fetcher=request):
    if not 2020<=year<=2025:
        raise ValueError("HISTORICAL_ETF_YEAR_OUTSIDE_RESEARCH")
    output=Path(destination)
    output.mkdir(parents=True,exist_ok=True)
    rows,receipts,seen=[],[],set()
    for month in range(1,13):
        yearmonth=f"{year:04d}-{month:02d}"
        url=historical_url("0050",yearmonth)
        raw=b""
        try:
            raw=fetcher(url)
            parsed=parse(raw,"0050",yearmonth)
            if any(x["date"] in seen for x in parsed):
                raise ValueError("DUPLICATE_MONTHLY_0050_DATE")
            if len(parsed)<8:
                raise ValueError("UNEXPECTED_SHORT_0050_MONTH")
            rows.extend(parsed)
            seen.update(x["date"] for x in parsed)
            status="ORIGINAL_QUOTE_COLLECTED_TR_PENDING"
        except (ValueError,KeyError,TypeError,OSError,EOFError) as exc:
            parsed=[]
            status="FAILED:"+type(exc).__name__+":"+str(exc)[:100]
        receipt={
            "month":yearmonth,"source_url":url,
            "raw_original_sha256":hashlib.sha256(raw).hexdigest() if raw else None,
            "rows_accepted":len(parsed),"bytes":len(raw),"status":status,
            "archive_name":f"0050_raw_{yearmonth}.json.gz" if raw else None,
        }
        if raw:
            (output/receipt["archive_name"]).write_bytes(gzip.compress(raw))
        receipts.append(receipt)
    rows.sort(key=lambda x:x["date"])
    with (output/f"0050_unadjusted_close_{year}.csv").open(
            "w",encoding="utf-8",newline="") as stream:
        w=csv.DictWriter(stream,fieldnames=["date","close","volume_shares","turnover_ntd"])
        w.writeheader()
        w.writerows([{k:r[k] for k in w.fieldnames} for r in rows])
    passed=sum(x["rows_accepted"]>0 for x in receipts)
    doc={
        "schema":"BUYBACK_0050_UNADJUSTED_ORIGINALS_V1",
        "year":year,"months_collected":passed,"trading_days":len(rows),
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "status":"CLOSE_SOURCE_COLLECTED_TOTAL_RETURN_PENDING" if passed==12 else
                 "INCOMPLETE_UNADJUSTED_CLOSE_HISTORY",
        "quotes_are_unadjusted":True,"corporate_actions_verified":False,
        "split_2025_06_cannot_be_ignored":True,
        "dividends_must_be_reinvested_for_total_return":True,
        "eligible_as_0050_total_return_benchmark":False,
        "use_for_trading_or_a_plus":False,
        "receipts":receipts,
    }
    (output/"manifest.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({key:doc[key] for key in
                      ("year","months_collected","trading_days","status")}))
    return doc

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",required=True,type=int)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    done=collect(args.year,args.out)
    if done["months_collected"]!=12:
        raise SystemExit(2)
