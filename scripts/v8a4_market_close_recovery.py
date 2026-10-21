#!/usr/bin/env python3
"""Validated, dated TWSE/TPEx whole-market closing quotes, for stale OpenAPI rescue.

Fail closed: use the same exact trading date for both exchanges, source JSON
must report the expected date, and no synthetic quote or last-close carry-forward.
"""
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

DATE=re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}\Z")
ORDINARY=re.compile(r"[0-9]{4}\Z")
METHODS={
    "TWSE":("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
            "TWSE_MI_INDEX_DATED_ALLBUT0999"),
    "TPEX":("https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
            "TPEX_DAILY_QUOTES_DATED"),
}

def source_url(market,day):
    if market not in METHODS or DATE.fullmatch(str(day)) is None:
        raise ValueError("INVALID_DATED_EXCHANGE_REQUEST")
    d=dt.date.fromisoformat(day)
    qs={"date":d.strftime("%Y%m%d"),"type":"ALLBUT0999","response":"json"} if market=="TWSE" else {
        "date":f"{d.year-1911}/{d.month:02d}/{d.day:02d}","response":"json"}
    return METHODS[market][0]+"?"+urllib.parse.urlencode(qs)

def download(url,attempts=4):
    if not any(url.startswith(base+"?") for base,_ in METHODS.values()):
        raise ValueError("UNTRUSTED_EXCHANGE_SOURCE_URL")
    err=None
    for n in range(attempts):
        try:
            req=urllib.request.Request(url,headers={
                "User-Agent":"Mozilla/5.0 (Taiwan dated official-market research archive)",
                "Accept":"application/json,text/plain,*/*"})
            with urllib.request.urlopen(req,timeout=55) as r:
                if r.status!=200 or urllib.parse.urlsplit(r.url).hostname not in (
                        "www.twse.com.tw","www.tpex.org.tw"):
                    raise ValueError("EXCHANGE_REDIRECT_OR_HTTP_STATUS")
                data=r.read(20000001)
            if not 8000<len(data)<=20000000 or b"<html" in data[:200].lower():
                raise ValueError("EXCHANGE_RESPONSE_NOT_JSON")
            json.loads(data.decode("utf-8-sig"))
            return data
        except (OSError,ValueError,UnicodeError,EOFError,http.client.IncompleteRead) as ex:
            err=ex
            if n<attempts-1:time.sleep(1+n)
    raise ValueError("DATED_MARKET_FETCH_FAILED:"+type(err).__name__+":"+str(err)[:120])

def numeric(s,whole=False):
    s=str(s if s is not None else "").replace(",","").strip()
    if s in ("","--","---","-","N/A","nan"):return None
    if whole:return int(s) if re.fullmatch(r"[0-9]+",s) else None
    try:
        value=float(s)
    except (TypeError,ValueError):
        return None
    return value if math.isfinite(value) and 0<value<1000000 else None

def parse(market,raw,day,min_issuers=300):
    if market not in METHODS or DATE.fullmatch(str(day)) is None:
        raise ValueError("INVALID_EXCHANGE_OR_DATE")
    document=json.loads(raw.decode("utf-8-sig"))
    if not isinstance(document,dict) or document.get("date")!=day.replace("-",""):
        raise ValueError("DATED_MARKET_RESPONSE_DATE_MISMATCH")
    if str(document.get("stat","")).strip().lower()!="ok":
        raise ValueError("DATED_MARKET_NOT_OPEN_OR_NOT_FINAL")
    tables=document.get("tables")
    if not isinstance(tables,list):raise ValueError("DATED_MARKET_TABLES_ABSENT")
    if market=="TWSE":
        candidates=[t for t in tables if isinstance(t,dict)
            and "每日收盤行情" in str(t.get("title",""))
            and "證券代號" in t.get("fields",[])
            and "收盤價" in t.get("fields",[])]
        names=dict(code="證券代號",name="證券名稱",close="收盤價",
                   volume="成交股數",turnover="成交金額")
    else:
        candidates=[t for t in tables if isinstance(t,dict)
            and t.get("title")=="上櫃股票行情"
            and "代號" in t.get("fields",[])]
        names=dict(code="代號",name="名稱",close="收盤",
                   volume="成交股數",turnover="成交金額(元)")
    if len(candidates)!=1:raise ValueError("DATED_MARKET_OFFICIAL_PRICE_TABLE_AMBIGUOUS")
    tb=candidates[0];fields=tb.get("fields")
    if not isinstance(fields,list):raise ValueError("DATED_MARKET_BAD_FIELDS")
    indices={}
    for key,field in names.items():
        if fields.count(field)!=1:raise ValueError("DATED_MARKET_FIELD_MISSING_OR_DUPLICATE_"+field)
        indices[key]=fields.index(field)
    rows=tb.get("data")
    if not isinstance(rows,list):raise ValueError("DATED_MARKET_DATA_ABSENT")
    parsed=[];seen=set()
    for rec in rows:
        if not isinstance(rec,list) or len(rec)<len(fields):
            raise ValueError("DATED_MARKET_ROW_MALFORMED")
        code=str(rec[indices["code"]]).strip()
        if ORDINARY.fullmatch(code) is None:continue
        if code in seen:raise ValueError("DATED_MARKET_DUPLICATE_STOCK")
        seen.add(code)
        volume=numeric(rec[indices["volume"]],True)
        amount=numeric(rec[indices["turnover"]],True)
        close=numeric(rec[indices["close"]])
        if volume is None or amount is None:
            # A genuine suspended zero-volume issuer may lack quote volume;
            # refuse the source rather than invent these amounts.
            raise ValueError("DATED_MARKET_ISSUER_TURNOVER_INVALID")
        parsed.append(dict(market=market,date=day,code=code,
            name=str(rec[indices["name"]]).strip(),close=close,
            volume_shares=volume,turnover_ntd=amount))
        opening_field='開盤價' if market=='TWSE' else '開盤'
        from scripts.execution_quote_archive import execution_fields
        opening=rec[fields.index(opening_field)] if fields.count(opening_field)==1 else None
        parsed[-1].update(execution_fields(day,opening))
    if len(parsed)<min_issuers or sum(x["close"] is not None for x in parsed)<min_issuers-20:
        raise ValueError("DATED_MARKET_INSUFFICIENT_ORDINARY_STOCKS")
    return parsed

def recover(market,requested_date,last_openapi_date,rawdir,fetch=download):
    if market not in METHODS or DATE.fullmatch(str(requested_date)) is None:
        raise ValueError("INVALID_EXCHANGE_DATE")
    if requested_date<=str(last_openapi_date):
        raise ValueError("BACKFILL_DATE_NOT_NEWER_THAN_OPENAPI")
    u=source_url(market,requested_date)
    payload=fetch(u)
    rows=parse(market,payload,requested_date)
    p=Path(rawdir)/(market.lower()+"_dated_"+requested_date+".json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(payload)
    return rows,requested_date,hashlib.sha256(payload).hexdigest(),u
