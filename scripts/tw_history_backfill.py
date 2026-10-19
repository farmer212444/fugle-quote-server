#!/usr/bin/env python3
"""V8.8.9: incremental historical TWSE *issuer* turnover, not all-market/PIT certification.

Official exchange STOCK_DAY monthly endpoint is the original historical source.
Historical retrieval date != issuer filing date. Price/turnover unadjusted. Does not
pass formal A+ tradability gate or change ranked valuations.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time
import urllib.parse
import urllib.request

ROOT=Path("tw-market-data")
OUT=ROOT/"prices/issuer_history/TWSE"
RAW=Path("market-raw-price-history")
URL="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
PREFERRED=("6206","9802","1714","1785","3305","4739","6741","2317","2376","2330")
CODE=re.compile(r"\d{4}\Z")

def sha(b):return hashlib.sha256(b).hexdigest()
def require(ok,reason):
    if not ok:raise ValueError(reason)
def request(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; public market research historical audit)",
       "Accept":"application/json,text/plain,*/*","Referer":"https://www.twse.com.tw/"})
    with urllib.request.urlopen(req,timeout=28) as r:
        require(r.status==200 and urllib.parse.urlparse(r.url).hostname=="www.twse.com.tw","OFFICIAL_TWSE_FETCH_REDIRECT")
        raw=r.read(3000001)
    require(150<len(raw)<=3000000 and b"<html" not in raw[:200].lower(),"NOT_PLAUSIBLE_TWSE_JSON")
    return raw
def historical_url(code,month):
    require(CODE.fullmatch(str(code)) is not None,"WRONG_STOCK_CODE")
    require(re.fullmatch(r"20\d{2}-(0[1-9]|1[012])",month),"INVALID_MONTH")
    return URL+"?"+urllib.parse.urlencode(dict(date=month.replace("-","")+"01",stockNo=code,response="json"))
def iso_roc(s):
    fields=str(s).strip().replace("-","/").split("/")
    require(len(fields)==3,"INVALID_TWSE_ROC_DATE")
    y,m,d=map(int,fields)
    if y<1911:y+=1911
    return dt.date(y,m,d).isoformat()
def integer(v):
    v=str(v).replace(",","").strip()
    return int(v) if re.fullmatch(r"\d+",v) else None
def price(v):
    v=str(v).replace(",","").strip()
    try:f=float(v)
    except (ValueError,TypeError):return None
    return f if math.isfinite(f) and f>0 else None
def parse(raw,code,month):
    j=json.loads(raw.decode("utf-8-sig"))
    require(isinstance(j,dict) and j.get("stat")=="OK","TWSE_HISTORY_RESPONSE_NOT_OK")
    header=str(j.get("title",""))
    require(re.search(r"(?<!\\d)"+re.escape(code)+r"(?!\\d)",header) is not None,
            "TWSE_MONTHLY_ISSUER_CODE_NOT_CONFIRMED_IN_TITLE")
    fields=j.get("fields",[])
    require(isinstance(fields,list) and len(fields)>=7,"TWSE_HISTORY_FIELDS_MISSING")
    def locate(term):
        matches=[i for i,f in enumerate(fields) if str(f).replace(" ","").replace("\n","")==term]
        require(len(matches)==1,"TWSE_HISTORY_EXPECTED_FIELD_"+term)
        return matches[0]
    cols={x:locate(x) for x in ("日期","交易股數","成交金額","收盤價")}
    values=j.get("data")
    require(isinstance(values,list) and 5<=len(values)<=32,"MONTH_HISTORY_ROW_COUNT_INVALID")
    data={}
    for r in values:
        require(isinstance(r,list) and len(r)>=len(fields),"HISTORY_ROW_SHAPE_INVALID")
        d=iso_roc(r[cols["日期"]])
        require(d[:7]==month,"HISTORY_MONTH_MISMATCH")
        require(d not in data,"DUPLICATED_TWSE_SESSION")
        vol=integer(r[cols["交易股數"]]);amount=integer(r[cols["成交金額"]]);close=price(r[cols["收盤價"]])
        require(vol is not None and amount is not None and vol>=0 and amount>=0,
                "INVALID_TWSE_TURNOVER_OR_VOLUME")
        data[d]=dict(date=d,volume_shares=vol,turnover_ntd=amount,close=close)
    return [data[k] for k in sorted(data)]
def recent_months(asof,limit=4):
    y,m=asof.year,asof.month;out=[]
    for _ in range(limit):
        out.append(f"{y}-{m:02d}")
        m-=1
        if not m:m=12;y-=1
    return out
def candidates(raw_price,cap=8):
    data=json.loads(raw_price)
    bycode={x["code"]:x for x in data if x.get("market")=="TWSE" and CODE.fullmatch(x.get("code",""))}
    ordered=[x for x in PREFERRED if x in bycode]
    require("6206" in ordered and "9802" in ordered,"CORE_6206_9802_NOT_IN_OFFICIAL_TWSE_PRICE_ARCHIVE")
    return ordered[:cap]
def combine(records,asof,code):
    dates={}
    for month,rows in records.items():
        for x in rows:
            require(x["date"][:7]==month,"MONTHLY_ROW_TIME_WINDOW_MISMATCH")
            require(x["date"] not in dates,"DUPLICATE_CROSS_MONTH_PRICE_SESSION")
            if x["date"]<=asof:dates[x["date"]]=x
    return [dates[k] for k in sorted(dates,reverse=True)]
def stats(dates,asof):
    usable=[x for x in dates if x["date"]<=asof]
    result={}
    for n,maxspan in ((5,15),(20,45),(60,120)):
        sample=usable[:n]
        enough=(len(sample)==n and all(isinstance(r["turnover_ntd"],int) for r in sample)
                and (dt.date.fromisoformat(sample[0]["date"])-dt.date.fromisoformat(sample[-1]["date"])).days<=maxspan)
        if not enough:result[str(n)]=None;continue
        turnovers=[r["turnover_ntd"] for r in sample]
        med=statistics.median(turnovers)
        result[str(n)]=dict(sessions=n,first=sample[-1]["date"],last=sample[0]["date"],
          median_turnover_ntd=med,min_turnover_ntd=min(turnovers),
          zero_turnover_sessions=sum(v==0 for v in turnovers),
          idealized_5m_exit_sessions_at_20pct=(round(5_000_000/(.20*med),2) if med>0 else None))
    return result

def process(code,asof,months,fetch=request,out=OUT,rawdir=RAW,sleep=0.4,reference_close=None):
    path=Path(out)/(code+".json")
    old=json.loads(path.read_text("utf-8")) if path.exists() else {}
    old_months=old.get("by_month",{})
    require(not old or old.get("issuer")==code and old.get("market")=="TWSE",
            "HISTORICAL_ISSUER_ARCHIVE_IDENTITY_MISMATCH")
    items=dict(old_months);new=0;fails=[]
    for month in months:
        # Current month must refresh as new sessions close; older months remain frozen.
        if month in items and month != months[0]:
            continue
        url=historical_url(code,month)
        try:
            raw=fetch(url)
            rows=parse(raw,code,month)
            # Do not retain days beyond known latest official market date.
            rows=[x for x in rows if x["date"]<=asof]
            require(bool(rows),"NO_SESSIONS_UP_TO_REFERENCE_DATE")
            if (month in items and items[month].get("original_response_sha256")==sha(raw)
                    and items[month].get("rows")==rows):
                continue
            rawpath=Path(rawdir)/code/(month+".json")
            rawpath.parent.mkdir(parents=True,exist_ok=True)
            rawpath.write_bytes(raw)
            items[month]=dict(source_url=url,original_response_sha256=sha(raw),
                captured_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                original_exchange_signature_verified=False,rows=rows)
            new+=1
        except Exception as exc:
            fails.append(dict(code=code,month=month,status="SOURCE_RETRY_REQUIRED",
                              error=type(exc).__name__+":"+str(exc)[:150]))
        if sleep:time.sleep(sleep)
    records={month:item["rows"] for month,item in items.items()}
    normalized=combine(records,asof,code)
    require(not normalized or max(x["date"] for x in normalized)<=asof,"FUTURE_PRICE_CANNOT_BE_INCLUDED")
    if reference_close is not None and normalized and normalized[0]["date"]==asof:
        if normalized[0]["close"] is None or abs(normalized[0]["close"]-float(reference_close))>.011:
            raise ValueError("TWSE_HISTORY_CLOSE_DOES_NOT_MATCH_OFFICIAL_DAILY_CLOSE")
    oldstats=stats(normalized,asof)
    result=dict(schema="V889_OFFICIAL_TWSE_ISSUER_MONTHLY",issuer=code,market="TWSE",
      price_reference_asof=asof,source_type="OFFICIAL_TWSE_MONTHLY_STOCK_DAY",
      original_raw_responses_preserved_in_actions_artifact_not_repository=True,
      backfill_capture_not_point_in_time_trade_history=True,
      share_adjustments_dividends_and_spread_not_verified=True,
      original_source_not_cryptographically_signed=True,
      formal_tradability_gate="PENDING_NOT_CERTIFIED",
      source_errors=fails,
      by_month=items,sessions=normalized,liquidity=oldstats)
    Path(out).mkdir(parents=True,exist_ok=True)
    data=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if not path.exists() or path.read_text("utf-8")!=data:path.write_text(data,encoding="utf-8")
    return dict(code=code,months=len(items),new_months=new,days=len(normalized),
                twenty=oldstats["20"] is not None,source_errors=fails)

def run(max_issuers=6,months=4,fetch=request,sleep=0.4):
    manifest=json.loads((ROOT/"prices/latest_manifest.json").read_text("utf-8"))
    asof=manifest["date"]
    rawfile=(ROOT/"prices"/(asof+".json")).read_bytes()
    require(sha(rawfile)==manifest["normalized_sha256"],"LATEST_REFERENCE_PRICE_HASH_MISMATCH")
    ids=candidates(rawfile,max_issuers)
    close_by_code={x["code"]:x.get("close") for x in json.loads(rawfile) if x.get("market")=="TWSE"}
    rr=[];window=recent_months(dt.date.fromisoformat(asof),months)
    for code in ids:
        rr.append(process(code,asof,window,fetch=fetch,sleep=sleep,
                          reference_close=close_by_code[code]))
    result=dict(reference_date=asof,issuer_probes=rr,
        source_scope="TWSE_ISSUERS_ONLY_TPEX_NOT_YET_INCLUDED",
        original_capture_not_independent_PIT_certificate=True,
        formal_Aplus_issuers_created=0)
    loc=ROOT/"rankings/v889_backfill_progress.json"
    loc.parent.mkdir(parents=True,exist_ok=True)
    loc.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# V8.8.9 官方TWSE個股歷史成交補檔","",
           f"參考收盤：{asof}；僅覆蓋證交所TWSE個股，不代表全市場交易歷史完整。","",
           "|股票|已取得月數|交易日|20日成交值|尚待重試月份|","|---|---:|---:|---|---:|"]
    for x in rr:lines.append(f"|{x['code']}|{x['months']}|{x['days']}|{'20/20' if x['twenty'] else '不足'}|{len(x['source_errors'])}|")
    lines+=["","原始HTTP位元組保留於本次GitHub Actions artifact；雜湊為蒐集收據，不是獨立官方數位簽章。",
            "未納入櫃買TPEx歷史資料、價差、漲跌停實際可成交量、股利還原、資料發布PIT；因此正式流動性與A+門檻維持PENDING。"]
    (ROOT/"rankings/v889_backfill_progress.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    if not any(x["days"]>=20 for x in rr) and not any(x["new_months"]>0 for x in rr):
        raise RuntimeError("HISTORY_BACKFILL_NOT_PROGRESSING_REVIEW_SOURCE_ERRORS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--max-issuers",type=int,default=6)
    p.add_argument("--months",type=int,default=4)
    a=p.parse_args()
    require(1<=a.max_issuers<=10 and 2<=a.months<=12,"INVALID_FETCH_BUDGET")
    run(max_issuers=a.max_issuers,months=a.months)
if __name__=="__main__":main()
