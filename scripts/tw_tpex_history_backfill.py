#!/usr/bin/env python3
"""V8.9.2: bounded official TPEx issuer monthly turnover history, research only.

Uses public TPEx st43_result JSON at dated ROC month. Captured HTTP bytes in
GitHub Actions artifact, normalized receipts stored in repo. Never infers A+.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from scripts.tw_history_backfill import (ROOT, require, sha, iso_roc, integer,
                                          price, combine, stats, recent_months)

BASE="https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"
OUT=ROOT/"prices/issuer_history/TPEX"
RAW=Path("market-raw-tpex-history")
CODE=re.compile(r"\d{4}\Z")

def url_for(code,month):
    require(CODE.fullmatch(str(code)) is not None,"WRONG_TPEX_ISSUER")
    require(re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])",month) is not None,"INVALID_TPEX_MONTH")
    year,m=map(int,month.split("-"))
    require(year>=2010,"INVALID_TPEX_YEAR")
    return BASE+"?"+urllib.parse.urlencode(dict(d=f"{year-1911}/{m:02d}",stkno=code))

def request(url):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; dated market research archive)",
        "Accept":"application/json,text/plain,*/*",
        "Referer":"https://www.tpex.org.tw/"})
    with urllib.request.urlopen(req,timeout=28) as r:
        require(r.status==200 and urllib.parse.urlparse(r.url).hostname=="www.tpex.org.tw",
                "TPEX_HISTORY_REDIRECT_OR_HTTP_ERROR")
        raw=r.read(3000001)
    require(100<len(raw)<=3000000 and b"<html" not in raw[:200].lower(),
            "NOT_PLAUSIBLE_TPEX_JSON")
    return raw

def parse(raw,month):
    doc=json.loads(raw.decode("utf-8-sig"))
    require(isinstance(doc,dict),"TPEX_NOT_JSON_OBJECT")
    data=doc.get("aaData")
    require(isinstance(data,list) and 5<=len(data)<=32,"TPEX_MONTHLY_AADATA_INVALID")
    rows={}
    for r in data:
        require(isinstance(r,list) and len(r)>=7,"TPEX_PRICE_ROW_SHAPE_INVALID")
        day=iso_roc(r[0])
        require(day[:7]==month,"TPEX_MONTH_DATE_MISMATCH")
        require(day not in rows,"TPEX_DUPLICATE_DATE")
        volume=integer(r[1]);turnover=integer(r[2]);closing=price(r[6])
        require(volume is not None and turnover is not None and
                volume>=0 and turnover>=0,"TPEX_INVALID_VOLUME_OR_TURNOVER")
        rows[day]=dict(date=day,volume_shares=volume,turnover_ntd=turnover,close=closing)
    return [rows[d] for d in sorted(rows)]

def candidates(raw_price,asof,cap=12,root=ROOT):
    rows=json.loads(raw_price)
    latest={str(x.get("code")):x for x in rows if x.get("market")=="TPEX"
            and CODE.fullmatch(str(x.get("code","")))}
    path=Path(root)/"rankings/v891_gate_progress.json"
    if not path.exists():return []
    stages=json.loads(path.read_text(encoding="utf-8"))
    require(stages.get("asof_price_date")==asof,"TPEX_RANK_AND_PRICE_DATE_MISMATCH")
    backlog=[]
    seen=set()
    for x in stages.get("issuer_diagnostics",[]):
        code=str(x.get("code"))
        if (code in seen or code not in latest or x.get("market")!="TPEX" or
            x.get("research_upside_pct") is None or x["research_upside_pct"]<30):
            continue
        seen.add(code)
        existing=Path(root)/"prices/issuer_history/TPEX"/(code+".json")
        if existing.exists():
            old=json.loads(existing.read_text(encoding="utf-8"))
            require(old.get("issuer")==code and old.get("market")=="TPEX",
                    "TPEX_PRIOR_ARCHIVE_IDENTITY_MISMATCH")
            if old.get("price_reference_asof")==asof and old.get("liquidity",{}).get("20"):
                continue
        backlog.append(code)
    return backlog[:cap]

def process(code,asof,months,fetch=request,out=OUT,rawdir=RAW,sleep=0.35,reference_close=None):
    path=Path(out)/(code+".json")
    old=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    require(not old or (old.get("issuer")==code and old.get("market")=="TPEX"),
            "TPEX_SOURCE_EXISTING_ISSUER_MISMATCH")
    collection=dict(old.get("by_month",{}));errors=[];n=0
    for month in months:
        if month in collection and month!=months[0]:continue
        url=url_for(code,month)
        try:
            raw=fetch(url)
            rows=[x for x in parse(raw,month) if x["date"]<=asof]
            require(rows,"TPEX_NO_SESSIONS_BEFORE_ASOF")
            if (month in collection and collection[month].get("original_response_sha256")==sha(raw)
                    and collection[month].get("rows")==rows):
                continue
            rawpath=Path(rawdir)/code/(month+".json")
            rawpath.parent.mkdir(parents=True,exist_ok=True)
            rawpath.write_bytes(raw)
            collection[month]=dict(source_url=url,original_response_sha256=sha(raw),
                captured_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                original_exchange_signature_verified=False,rows=rows)
            n+=1
        except Exception as e:
            errors.append(dict(code=code,month=month,status="SOURCE_RETRY_REQUIRED",
                               error=type(e).__name__+":"+str(e)[:150]))
            # An unavailable modern market endpoint usually fails for every
            # month. Avoid 36 near-identical requests before investigating.
            if not collection and month==months[0]:
                break
        if sleep:time.sleep(sleep)
    normalized=combine({m:d["rows"] for m,d in collection.items()},asof,code)
    if reference_close is not None and normalized and normalized[0]["date"]==asof:
        require(normalized[0]["close"] is not None and
                abs(normalized[0]["close"]-float(reference_close))<=.011,
                "TPEX_HISTORY_CLOSE_DOES_NOT_MATCH_OFFICIAL_DAILY_CLOSE")
    metric=stats(normalized,asof)
    entry=dict(schema="V892_OFFICIAL_TPEX_ISSUER_MONTHLY",issuer=code,market="TPEX",
        price_reference_asof=asof,source_type="OFFICIAL_TPEX_MONTHLY_ST43",
        original_raw_responses_preserved_in_actions_artifact_not_repository=True,
        backfill_capture_not_point_in_time_trade_history=True,
        share_adjustments_dividends_and_spread_not_verified=True,
        original_source_not_cryptographically_signed=True,
        formal_tradability_gate="PENDING_NOT_CERTIFIED",
        source_errors=errors,by_month=collection,sessions=normalized,liquidity=metric)
    Path(out).mkdir(parents=True,exist_ok=True)
    written=json.dumps(entry,ensure_ascii=False,indent=2)+"\n"
    if not path.exists() or path.read_text(encoding="utf-8")!=written:path.write_text(written,encoding="utf-8")
    return dict(code=code,months=len(collection),new_months=n,days=len(normalized),
                twenty=metric["20"] is not None,source_errors=errors)

def run(cap=12,months=3,fetch=request,sleep=.35):
    price_manifest=json.loads((ROOT/"prices/latest_manifest.json").read_text(encoding="utf-8"))
    asof=price_manifest["date"]
    raw=(ROOT/"prices"/(asof+".json")).read_bytes()
    require(sha(raw)==price_manifest["normalized_sha256"],"TPEX_REFERENCE_ARCHIVE_CHECKSUM_MISMATCH")
    keys=candidates(raw,asof,cap,ROOT)
    snap=json.loads(raw)
    prices={str(x["code"]):x.get("close") for x in snap if x.get("market")=="TPEX"}
    window=recent_months(dt.date.fromisoformat(asof),months)
    checks=[process(code,asof,window,fetch=fetch,sleep=sleep,reference_close=prices[code])
            for code in keys]
    result=dict(reference_date=asof,selected_codes=keys,issuer_probes=checks,
        source_scope="TPEX_TOP_UPSIDE_ONLY_NOT_FULL_MARKET",
        backfill_but_not_tradeable_CERTIFICATE=True,formal_Aplus_created=0)
    dest=ROOT/"rankings/v892_tpex_backfill_progress.json"
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# V8.9.2 上櫃歷史成交額增量回補","",
        f"價格參考日：{asof}；此結果只完成公開原始月資料封存，不代表13項正式A+已通過。","",
        "|股票|已收月份|交易日|20日成交|來源重試|","|---|---:|---:|---|---:|"]
    for x in checks:
        lines.append(f"|{x['code']}|{x['months']}|{x['days']}|{'20/20' if x['twenty'] else '不足'}|{len(x['source_errors'])}|")
    lines+=["","櫃買資料來源為公開 st43_result.php 月別資料，依股票代碼取得並與官方基準日收盤核對。",
        "HTTP原始回應置於 GitHub Actions artifact；雜湊收據、網站回應及20日金額皆不代表原始公告PIT或實際可成交性已認證。"]
    (ROOT/"rankings/v892_tpex_backfill_progress.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"selected":keys,"new_complete":sum(x["twenty"] for x in checks),
        "source_errors":sum(len(x["source_errors"]) for x in checks),
        "first_errors":[x["source_errors"][0] for x in checks if x["source_errors"]][:6]},ensure_ascii=False))
    if checks and not any(x["twenty"] or x["new_months"] for x in checks):
        raise RuntimeError("TPEX_HISTORICAL_BACKFILL_NOT_PROGRESSING")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--max-issuers",type=int,default=12)
    p.add_argument("--months",type=int,default=3)
    args=p.parse_args()
    require(1<=args.max_issuers<=25 and 2<=args.months<=12,"INVALID_TPEX_FETCH_BUDGET")
    run(args.max_issuers,args.months)
if __name__=="__main__":main()
