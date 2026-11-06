#!/usr/bin/env python3
"""Read-only official-source connectivity probe; never treats a probe as an event backtest."""
import argparse
import gzip
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

def rocdate(value):
    v = re.sub(r"\D", "", str(value))
    if len(v) == 7:
        return f"{int(v[:3])+1911:04d}-{v[3:5]}-{v[5:7]}"
    if len(v) == 8:
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    return None

def parse_tai50(raw, year, month):
    body = json.loads(raw.decode("utf-8-sig"))
    if isinstance(body, dict):
        fields = body.get("fields") or []
        records = body.get("data") or body.get("rows") or []
        if records and isinstance(records[0], list):
            d_col = next((i for i,f in enumerate(fields) if "日期" in f or f.lower()=="date"), None)
            tr_col = next((i for i,f in enumerate(fields) if "報酬" in f or "totalreturn" in f.lower()), None)
            if d_col is None or tr_col is None:
                return [], "UNRECOGNIZED_INDEX_FIELDS"
            body = [{"Date":r[d_col],"Taiwan50TotalReturnIndex":r[tr_col]} for r in records]
        else:
            body = records
    if not isinstance(body, list):
        return [], "NOT_ARRAY"
    rows, seen = [], set()
    for r in body:
        if not isinstance(r, dict):
            continue
        d = rocdate(r.get("Date") or r.get("date") or "")
        value = r.get("Taiwan50TotalReturnIndex")
        if not d or value in (None, "", "--", "—"):
            continue
        if not d.startswith(f"{year:04d}-{month:02d}"):
            return [], "DATE_OUTSIDE_QUERY_MONTH"
        try:
            n = float(str(value).replace(",", ""))
        except ValueError:
            return [], "NON_NUMERIC_INDEX_LEVEL"
        if not 0<n<1e8 or d in seen:
            return [], "INVALID_OR_DUPLICATE_INDEX_LEVEL"
        rows.append({"date":d,"taiwan50_total_return_index":n})
        seen.add(d)
    if len(rows)<8:
        return rows,"UNUSABLE_TOO_FEW_SESSIONS"
    return sorted(rows,key=lambda r:r["date"]),"RESPONSE_MONTH_PARSED_NOT_INDEPENDENTLY_AUDITED"

def mops_response_status(raw, status):
    s = raw.decode("utf-8",errors="replace")
    if status!=200:
        return "HTTP_NON_200"
    if any(x in s.lower() for x in ("/mops/error","access denied","captcha","驗證碼")):
        return "CHALLENGE_OR_SITE_ERROR"
    if "<table" in s.lower() and any(x in s for x in ("庫藏","買回","公司代號")):
        return "HTML_TABLE_PRESENT_UNPARSED"
    if "<html" in s.lower() or "<script" in s.lower():
        return "HTML_BUT_NO_IDENTIFIED_BUYBACK_TABLE"
    return "UNRECOGNIZED_RESPONSE"

def fetch(url, data=None):
    headers = {
        "User-Agent":"Mozilla/5.0 (compatible; Buyback-PIT-Research/1.0)",
        "Accept":"application/json,text/html,*/*",
        "Referer":"https://mops.twse.com.tw/mops/web/t35sc09" if data else "https://www.twse.com.tw/",
    }
    if data is not None:
        headers["X-Requested-With"]="XMLHttpRequest"
    req=urllib.request.Request(url,data=data,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=18) as resp:
            return resp.status, resp.url, resp.read(5_000_001), None
    except urllib.error.HTTPError as exc:
        return exc.code,exc.url,exc.read(200_000),f"HTTPError:{exc.code}"
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        return None,url,b"",f"{type(exc).__name__}:{str(exc)[:150]}"

def run(year=2020,month=1,out="/tmp/buyback-source-probe"):
    folder=Path(out)
    folder.mkdir(parents=True,exist_ok=True)
    results=[]
    query=urllib.parse.urlencode({"response":"json","date":f"{year:04d}{month:02d}01"})
    urls=[
        "https://www.twse.com.tw/indicesReport/TAI50I?"+query,
        "https://www.twse.com.tw/rwd/zh/indices/ftse/tai50i?"+query,
    ]
    for i,url in enumerate(urls):
        code,effective,raw,error=fetch(url)
        try:
            rows,reason=parse_tai50(raw,year,month) if raw else ([],"EMPTY_RESPONSE")
        except (ValueError,TypeError,KeyError,UnicodeError) as exc:
            rows,reason=[],"INVALID_JSON:"+type(exc).__name__
        results.append({
            "source":"TWSE_TAIWAN50_TR_INDEX_NOT_0050_ETF",
            "url":url,"effective_url":effective,"http_status":code,
            "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest() if raw else None,
            "error":error,"status":reason,"parsed_sessions":len(rows),
            "first":rows[0] if rows else None,"last":rows[-1] if rows else None})
        if raw:
            (folder/f"tw50_probe_{i}.json.gz").write_bytes(gzip.compress(raw))
    for market in ("sii","otc"):
        params={"step":"1","firstin":"1","TYPEK":market,"RD":"1",
                "d1":f"{year-1911:03d}0101","d2":f"{year-1911:03d}1231"}
        url="https://mops.twse.com.tw/mops/web/ajax_t35sc09"
        code,effective,raw,error=fetch(url,urllib.parse.urlencode(params).encode("ascii"))
        results.append({
            "source":"MOPS_BUYBACK_LEGACY_POST_UNVERIFIED","market":market,
            "url":url,"effective_url":effective,"http_status":code,
            "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest() if raw else None,
            "error":error,"status":mops_response_status(raw,code),
            "event_disclosure_times_verified":False,"event_rows":None})
        if raw:
            (folder/f"mops_probe_{market}.html.gz").write_bytes(gzip.compress(raw))
    report={"schema":"BUYBACK_SOURCE_PROBE_V1","checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "data_status":"SOURCE_PROBE_ONLY_NO_BACKTEST","year":year,"month":month,
            "formal_a_plus_unchanged":True,"orders_created":False,"sources":results}
    (folder/"latest_probe.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))
    return report

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,default=2020)
    ap.add_argument("--month",type=int,default=1)
    ap.add_argument("--out",default="/tmp/buyback-source-probe")
    args=ap.parse_args()
    if not 2020<=args.year<=2025 or not 1<=args.month<=12:
        ap.error("year must be 2020-2025; month 1-12")
    run(args.year,args.month,args.out)
