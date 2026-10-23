#!/usr/bin/env python3
"""One-shot MOPS legacy read-only verification; NO event import or backtest."""
import gzip
import hashlib
import json
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://mops.twse.com.tw/mops/web/"
PARAMS = dict(encodeURIComponent="1", step="1", firstin="1", off="1",
              d1="1090204", d2="1090429", RD="1")

def one(market, folder):
    params = dict(PARAMS, TYPEK=market)
    url = BASE + "ajax_t35sc09"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(params).encode("ascii"),
        headers={"User-Agent":"Mozilla/5.0",
                 "Content-Type":"application/x-www-form-urlencoded",
                 "Accept":"text/html,*/*",
                 "Referer":BASE+"t35sc09",
                 "Cache-Control":"no-cache",
                 "Pragma":"no-cache",
                 "If-Modified-Since":"Sat, 1 Jan 2000 00:00:00 GMT",
                 "X-Requested-With":"XMLHttpRequest"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status, raw, effective = resp.status, resp.read(2000001), resp.url
    except urllib.error.HTTPError as exc:
        status, raw, effective = exc.code,exc.read(100000),exc.url
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        return {"market":market,"error":str(exc)[:160],
                "status":"SOURCE_UNREACHABLE_NOT_DATA"}
    if raw:
        (folder/f"mops_legacy_{market}.html.gz").write_bytes(gzip.compress(raw))
    decoded=raw.decode("utf-8",errors="replace")
    tables=decoded.lower().count("<table")
    plain=re.sub(r"<[^>]+>"," ",decoded)
    plain=re.sub(r"\s+"," ",plain).strip()[:350]
    usable=(status==200 and tables>=1 and
            any(x in decoded for x in ("公司代號","買回股數","庫藏股")))
    return {"market":market,"http_status":status,
            "effective_url":effective,"source_url":url,
            "response_bytes":len(raw),"source_sha256":hashlib.sha256(raw).hexdigest(),
            "html_tables":tables,"preview_for_debug_only":plain,
            "status":"POTENTIAL_TABLE_NOT_EVENT_VERIFIED" if usable else
                     "NO_VERIFIED_EVENT_ROWS",
            "event_count":None}

def main(out="/tmp/mops-reprobe"):
    folder=Path(out)
    folder.mkdir(parents=True,exist_ok=True)
    records=[one(m,folder) for m in ("sii","otc")]
    report={"schema":"MOPS_LEGACY_REPROBE_V1",
            "captured_at_utc":datetime.now(timezone.utc).isoformat(),
            "data_status":"DIAGNOSTIC_ONLY_NO_VERIFIED_DISCLOSURE_TIMES",
            "orders_created":False,"formal_a_plus_unchanged":True,
            "results":records}
    (folder/"status.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))
    return report

if __name__=="__main__":
    main()
