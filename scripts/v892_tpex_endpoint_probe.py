#!/usr/bin/env python3
"""Inspect modern official TPEx historical endpoints; diagnostic only, never publish prices."""
import datetime as dt
import gzip
import json
import time
import urllib.error
import urllib.request

def probe(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (historical source diagnostic)","Accept":"application/json,*/*","Accept-Encoding":"gzip"})
    try:
        content=None
        for attempt in range(1,8):
            try:
                with urllib.request.urlopen(req,timeout=20) as r:
                    content=r.read(12000000)
                    if r.headers.get("Content-Encoding","").lower()=="gzip":content=gzip.decompress(content)
                    print("STATUS",r.status,"CONTENT_TYPE",r.headers.get("Content-Type"),"LEN",len(content),
                          "HEAD",repr(content[:130]),flush=True)
                break
            except (urllib.error.URLError, OSError, EOFError, gzip.BadGzipFile) as e:
                print("RETRY",attempt,type(e).__name__,str(e)[:90],flush=True)
                if attempt==7:raise
                time.sleep(min(attempt,3))
        try:
            data=json.loads(content.decode("utf-8-sig"))
            print("JSON_SHAPE",type(data).__name__,
                  (sorted(data.keys()) if isinstance(data,dict) else f"ROWS={len(data)}"),flush=True)
            if isinstance(data,dict) and isinstance(data.get("tables"),list):
                for tbl in data["tables"][:2]:
                    print("TABLE_TITLE",tbl.get("title"),
                          "FIELDS",repr(tbl.get("fields",[])[:24]),
                          "TABLE_KEYS",list(tbl.keys())[:20],
                          "FIRST_ROWS",repr(tbl.get("data",[])[:2])[:1300],flush=True)
            if isinstance(data,dict):
                for key in ("date","reportDate","report_date","stat","aaData"):
                    v=data.get(key)
                    if v is not None:
                        print("ITEM",key,str(v)[:350],flush=True)
        except Exception as e:print("JSON_ERROR",type(e).__name__,str(e)[:120],flush=True)
    except Exception as e:print("SOURCE_ERROR",type(e).__name__,str(e)[:150],flush=True)

def main():
    urls=["https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date=115%2F10%2F16"]
    for url in urls:
        print("CHECK",url,flush=True)
        probe(url)
if __name__=="__main__":main()
