#!/usr/bin/env python3
"""Diagnose official TWSE date-scoped ALLBUT0999 market quote JSON (no writes)."""
import datetime as dt
import json
import urllib.parse
import urllib.request

def probe(day="2026-10-20"):
    date=dt.date.fromisoformat(day)
    url="https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?"+urllib.parse.urlencode(
        dict(date=date.strftime("%Y%m%d"),type="ALLBUT0999",response="json"))
    print("OFFICIAL_PROBE_URL",url,flush=True)
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (dated official TWSE quote research)","Accept":"application/json,*/*"})
    with urllib.request.urlopen(req,timeout=55) as r:
        body=r.read(18000001)
        print("HTTP_STATUS",r.status,"BYTES",len(body),"CONTENT_TYPE",r.headers.get("content-type"),flush=True)
    record=json.loads(body.decode("utf-8-sig"))
    print("RESPONSE_KEYS",list(record)[:30],flush=True)
    print("STAT",record.get("stat"),"RESPONSE_DATE",record.get("date"),flush=True)
    if isinstance(record.get("tables"),list):
        for k,t in enumerate(record["tables"][:25]):
            print("TABLE",k,"TITLE",t.get("title"),"FIELDS",repr(t.get("fields",[])[:20]),
                  "ROWS",len(t.get("data",[])),"FIRST",repr(t.get("data",[])[:1])[:350],flush=True)
    for i in range(1,20):
        fields=record.get(f"fields{i}");rows=record.get(f"data{i}")
        if isinstance(rows,list) and len(rows)>10:
            print("LEGACY_SHAPE",i,"FIELDS",repr(fields[:20] if isinstance(fields,list) else fields),
                  "ROWS",len(rows),"FIRST",repr(rows[:1])[:350],flush=True)
    print("RAW_HEAD",repr(body[:140]),flush=True)

if __name__=="__main__":
    probe()
