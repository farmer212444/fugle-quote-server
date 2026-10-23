#!/usr/bin/env python3
"""V8.9.3 public TPEx dated dailyQuotes source backfill for >=30% research issuers.

No PIT trading backtest, exchange digital signature, full microstructure
review or A+ certification. Failed or truncated sources cannot become evidence.
"""
import argparse
import datetime as dt
import hashlib
import http.client
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from scripts.tw_history_backfill import ROOT, sha, require, stats
from scripts.history_archive import archive_original, observed_ohlc, quote_source_ready, verify_original, canonical,outstanding_benchmark_codes

RAW=Path("market-raw-tpex-daily")
OUT=ROOT/"prices/issuer_history/TPEX"
DATE_RE=re.compile(r"20\d\d-\d\d-\d\d\Z")
CODE_RE=re.compile(r"\d{4}\Z")
BASE="https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"

def daily_url(date):
    day=dt.date.fromisoformat(date)
    roc=f"{day.year-1911}/{day.month:02d}/{day.day:02d}"
    return BASE+"?"+urllib.parse.urlencode({"response":"json","date":roc})

def download(url,retries=3):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (official source historic research)",
                  "Referer":"https://www.tpex.org.tw/","Accept":"application/json,text/plain,*/*"})
    last=None
    for n in range(retries):
        try:
            with urllib.request.urlopen(req,timeout=28) as r:
                require(r.status==200 and urllib.parse.urlparse(r.url).hostname=="www.tpex.org.tw",
                        "UNOFFICIAL_TPEX_REDIRECT")
                data=r.read(4000001)
            require(500<len(data)<=4000000 and b"<html" not in data[:150].lower(),
                    "TPEX_NOT_COMPLETE_JSON")
            # Enforce complete valid UTF-8 JSON, not an HTML 200 or truncated HTTP body.
            json.loads(data.decode("utf-8-sig"))
            return data
        except (ValueError,UnicodeError,EOFError,OSError,TimeoutError,http.client.IncompleteRead) as e:
            last=e
            if n<retries-1:time.sleep(min(n+1,3))
    raise RuntimeError("TPEX_DOWNLOAD_FAILED_AFTER_RETRIES:"+repr(last)[:160])

def money(s):
    if isinstance(s,bool):return None
    text=str(s).replace(",","").strip()
    return int(text) if re.fullmatch(r"\d+",text) else None

def parse_daily(raw,day):
    require(DATE_RE.fullmatch(day) is not None,"UNSAFE_DAILY_DATE")
    doc=json.loads(raw.decode("utf-8-sig"))
    require(isinstance(doc,dict) and doc.get("date")==day.replace("-",""),
            "TPEX_OFFICIAL_RESPONSE_DATE_MISMATCH")
    require(str(doc.get("stat","")).lower()=="ok","TPEX_MARKET_NOT_OPEN_OR_NO_QUOTES")
    tables=doc.get("tables")
    require(isinstance(tables,list),"TPEX_OFFICIAL_TABLES_ABSENT")
    matches=[x for x in tables if isinstance(x,dict) and x.get("title")=="上櫃股票行情"]
    require(len(matches)==1,"TPEX_STOCK_QUOTES_TABLE_MISSING")
    table=matches[0];fields=table.get("fields")
    require(isinstance(fields,list),"TPEX_OFFICIAL_FIELDS_MISSING")
    def field(name):
        idx=[i for i,t in enumerate(fields) if str(t).replace(" ","")==name]
        require(len(idx)==1,"TPEX_EXPECTED_UNIQUE_FIELD_"+name)
        return idx[0]
    codecol=field("代號");closecol=field("收盤")
    opencol=field("開盤");highcol=field("最高");lowcol=field("最低")
    volumecol=field("成交股數");turnovercol=field("成交金額(元)")
    quotes={}
    for row in table.get("data",[]):
        if not isinstance(row,list) or len(row)<len(fields):
            raise ValueError("TPEX_OFFICIAL_ROW_SHAPE")
        code=str(row[codecol]).strip()
        if CODE_RE.fullmatch(code) is None:continue
        require(code not in quotes,"TPEX_OFFICIAL_DUPLICATE_ISSUER")
        value=money(row[turnovercol]);vol=money(row[volumecol])
        cs=str(row[closecol]).replace(",","").strip()
        try:closing=float(cs)
        except ValueError:closing=None
        if closing is not None and (not math.isfinite(closing) or closing<=0):closing=None
        # A suspended listing with no trade can have no closing quote, not 0 turnover by assumption.
        quotes[code]=observed_ohlc({"date":day,"code":code,"market":"TPEX",
                      "close":closing,"turnover_ntd":value,"volume_shares":vol},
                      row[opencol],row[highcol],row[lowcol])
    require(len(quotes)>=300,"TPEX_OFFICIAL_MARKET_SHARD_UNDERSIZED")
    return quotes

def selected_codes(root,asof,raw_market):
    rows=json.loads(raw_market)
    official={str(x.get("code")):x for x in rows if x.get("market")=="TPEX"
              and CODE_RE.fullmatch(str(x.get("code","")))}
    progress=json.loads((Path(root)/"rankings/v891_gate_progress.json").read_text(encoding="utf-8"))
    require(progress.get("asof_price_date")==asof,"TPEX_RESEARCH_PRICE_DATE_MISMATCH")
    chosen=outstanding_benchmark_codes(root,'TPEX')
    for x in progress.get("issuer_diagnostics",[]):
        code=str(x.get("code"))
        if x.get("market")=="TPEX" and x.get("research_upside_pct") is not None and x["research_upside_pct"]>=30 and code in official:
            if code not in chosen:chosen.append(code)
    require(len(chosen)==len(set(chosen)),"TPEX_CANDIDATE_DUPLICATE")
    return chosen,official

def load_old(root,codes,asof):
    old={}
    for code in codes:
        p=Path(root)/"prices/issuer_history/TPEX"/(code+".json")
        j=json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        if j:
            require(j.get("issuer")==code and j.get("market")=="TPEX" and
                    j.get("schema")=="V893_OFFICIAL_TPEX_DAILY",
                    "TPEX_EXISTING_ARCHIVE_IDENTITY_OR_SCHEMA_MISMATCH")
            require(j.get("price_reference_asof")<=asof,"TPEX_FUTURE_ARCHIVE")
        old[code]=j
    return old

def dates_before(asof,lookback=65):
    ref=dt.date.fromisoformat(asof)
    return [(ref-dt.timedelta(days=n)).isoformat() for n in range(lookback)
            if (ref-dt.timedelta(days=n)).weekday()<5]

def build_issuer(code,asof,by_day,root=ROOT,verified_sources=None):
    keep={d:row for d,row in by_day.items() if d<=asof}
    sessions=[keep[k]["row"] for k in sorted(keep,reverse=True)]
    stat=stats(sessions,asof)
    return dict(schema="V893_OFFICIAL_TPEX_DAILY",issuer=code,market="TPEX",
                price_reference_asof=asof,source_type="OFFICIAL_TPEX_DAILY_MARKET",
                original_raw_responses_preserved_in_actions_artifact_not_repository=not all(
                    quote_source_ready(root,item,verified_sources) for item in keep.values()),
                durable_original_sessions=sum(quote_source_ready(root,item,verified_sources) for item in keep.values()),
                original_source_not_cryptographically_signed=True,
                issuer_PIT_history_verified=False,share_adjusted_history=False,
                spread_and_exit_capacity_verified=False,
                formal_tradability_gate="PENDING_NOT_CERTIFIED",
                by_day=keep,sessions=sessions,liquidity=stat)

def run(max_dates=20,lookback=65,source=download,root=ROOT,rawdir=RAW,target_sessions=20,*,now=None):
    root=Path(root)
    manifest=json.loads((root/"prices/latest_manifest.json").read_text(encoding="utf-8"))
    asof=manifest["date"]
    price_bytes=(root/"prices"/(asof+".json")).read_bytes()
    require(sha(price_bytes)==manifest["normalized_sha256"],"TPEX_LATEST_MARKET_RECEIPT_MISMATCH")
    codes,latest=selected_codes(root,asof,price_bytes)
    old=load_old(root,codes,asof)
    histories={c:{d:r for d,r in old[c].get("by_day",{}).items() if d<=asof} for c in codes}
    verified_sources=set()
    results=[];failed=[];not_open=[]
    source_dates=dates_before(asof,lookback)
    # The immutable market-wide sources also serve new research candidates.
    # Count this run's most recent verified sessions, not lifetime archive size:
    # reaching the target must never stop collection of the next trading day.
    receipts={}
    for path in sorted((root/'prices/originals/history/TPEX').glob('*/*.json')):
        try:
            item=json.loads(path.read_text())
            day=item.get('identity')
            if day not in source_dates:continue
            ref=dict(item,receipt_path=path.relative_to(root).as_posix())
            prior=receipts.get(day)
            if prior is None or item['captured_at_utc']>prior['captured_at_utc']:receipts[day]=ref
        except (ValueError,KeyError,TypeError,OSError,AttributeError) as exc:
            failed.append(dict(path=path.relative_to(root).as_posix(),error='CACHED_RECEIPT_REJECTED:'+str(exc)[:150]))
    state_path=root/'prices/history_backfill_state/TPEX.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(schema='TPEX_HISTORY_RETRY_V1',dates={})
    require(state.get('schema')=='TPEX_HISTORY_RETRY_V1' and isinstance(state.get('dates'),dict),
            'TPEX_HISTORY_RETRY_STATE_INVALID')
    now=now or dt.datetime.now(dt.timezone.utc)
    require(now.tzinfo is not None,'TPEX_HISTORY_RETRY_TIMEZONE_REQUIRED')
    state['dates']={d:r for d,r in state['dates'].items() if d in source_dates}
    ready_dates=set();reused=[];deferred=[]
    def attach(day,market,original):
        require(original['market']=='TPEX' and original['identity']==day,'TPEX_ORIGINAL_DATE_IDENTITY_MISMATCH')
        require(sha(canonical(market))==original['parsed_rows_sha256'],'TPEX_ORIGINAL_PARSED_HASH_MISMATCH')
        if day==asof:
            for code in codes:
                if code in market and latest.get(code,{}).get('close') is not None and market[code]['close'] is not None:
                    require(abs(float(latest[code]['close'])-market[code]['close'])<=.011,
                            'TPEX_REFERENCE_CLOSE_DIFFERENCE_'+code)
        for code in codes:
            if code in market and market[code]['turnover_ntd'] is not None:
                histories[code][day]=dict(date=day,source_url=original['source_url'],
                    original_response_sha256=original['original_response_sha256'],
                    captured_at_utc=original['captured_at_utc'],original_archive=original,
                    raw_market_response_stored_in_artifact=False,row=market[code])
        ready_dates.add(day)
        state['dates'].pop(day,None)
    fetched=0
    for day in source_dates:
        if not codes or len(ready_dates)>=target_sessions:
            break
        if day in receipts:
            try:
                original=receipts[day]
                attach(day,parse_daily(verify_original(root,original),day),original)
                reused.append(day)
                continue
            except (ValueError,KeyError,TypeError,OSError,EOFError) as exc:
                failed.append(dict(date=day,error='CACHED_SOURCE_REJECTED:'+str(exc)[:150]))
        retry=state['dates'].get(day)
        if retry:
            after=dt.datetime.fromisoformat(retry['retry_after_utc'])
            require(after.tzinfo is not None,'TPEX_HISTORY_RETRY_TIMEZONE_REQUIRED')
            if now<after:
                deferred.append(day)
                continue
        if fetched>=max_dates:continue
        u=daily_url(day)
        try:
            data=source(u);m=parse_daily(data,day)
            original=archive_original(root,'TPEX',day,u,data,m)
            attach(day,m,original)
            rawp=Path(rawdir)/(day+".json");rawp.parent.mkdir(parents=True,exist_ok=True)
            rawp.write_bytes(data)
            results.append(day)
        except ValueError as e:
            if str(e)=="TPEX_MARKET_NOT_OPEN_OR_NO_QUOTES":not_open.append(day)
            else:failed.append(dict(date=day,error=type(e).__name__+":"+str(e)[:150]))
        except Exception as e:
            failed.append(dict(date=day,error=type(e).__name__+":"+str(e)[:150]))
        if day not in ready_dates:
            attempts=(retry or {}).get('attempts',0)+1
            error=next((item['error'] for item in reversed(failed) if item.get('date')==day),
                       'TPEX_MARKET_NOT_OPEN_OR_NO_QUOTES')
            state['dates'][day]=dict(attempts=attempts,last_attempt_utc=now.isoformat(),
                retry_after_utc=(now+dt.timedelta(hours=min(168,6*2**min(attempts-1,5)))).isoformat(),
                source_url=u,last_error=error,
                status='RETRY_REQUIRED_NOT_VERIFIED_AS_NONTRADING')
        fetched+=1
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    out=root/"prices/issuer_history/TPEX";out.mkdir(parents=True,exist_ok=True)
    eligible=0
    for c in codes:
        payload=build_issuer(c,asof,histories[c],root=root,verified_sources=verified_sources)
        if payload["liquidity"]["20"]:eligible+=1
        p=out/(c+".json")
        rendered=json.dumps(payload,ensure_ascii=False,indent=2)+"\n"
        if not p.exists() or p.read_text(encoding="utf-8")!=rendered:p.write_text(rendered,encoding="utf-8")
    progress=dict(price_reference_date=asof,issuer_count=len(codes),
        attempted_dates=fetched,successful_session_dates=results,nontrading_or_unavailable_dates=not_open,
        requested_durable_market_sessions=target_sessions,durable_market_session_count=len(ready_dates),
        reused_durable_market_session_dates=reused,retry_deferred_dates=deferred,
        failed_source_dates=failed,issuers_with_20_source_sessions=eligible,
        formal_tradability_gate_PASSED=0,formal_Aplus_added=0,
        original_issuer_publication_PIT_not_verified=True)
    dst=root/"rankings/v893_tpex_daily_history_progress.json"
    dst.write_text(json.dumps(progress,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"targeted_issuers":len(codes),"downloaded_days":len(results),
                      "failed_days":len(failed),"20_day_issuer_count":eligible,
                      "first_errors":failed[:4],"formal_Aplus_added":0},ensure_ascii=False),flush=True)
    if codes and not ready_dates and not any(len(v)>=20 for v in histories.values()):
        raise RuntimeError("OFFICIAL_TPEX_DATED_DAILY_HISTORY_NO_VALID_SOURCE_PROGRESS")
    return progress

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--max-dates",type=int,default=20)
    parser.add_argument("--lookback",type=int,default=65)
    parser.add_argument("--target-sessions",type=int,default=20)
    args=parser.parse_args()
    require(1<=args.max_dates<=35 and 25<=args.lookback<=2000 and
            1<=args.target_sessions<=1300,"INVALID_TPEX_REQUEST_BUDGET")
    run(args.max_dates,args.lookback,target_sessions=args.target_sessions)

if __name__=="__main__":
    main()
