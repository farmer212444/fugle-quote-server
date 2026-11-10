"""Bounded breadth-first historical price backlog, never a trading universe.

The frozen A+ issuer evidence and benchmark-cohort obligations retain priority,
but high-turnover issuers without *any* archived issuer history must have a
minimum collection lane to prevent permanent starvation.
"""
import json
import math
import re
from pathlib import Path

CODE = re.compile(r"\d{4}\Z")

def _positive(v):
    return type(v) in (int,float) and math.isfinite(v) and v>0

def marketwide_uncovered(root,raw_price,market,asof,excluded=(),cap=4):
    root=Path(root)
    if market not in ("TWSE","TPEX") or not isinstance(asof,str) or not 0<=cap<=20:
        raise ValueError("MARKETWIDE_HISTORY_INVALID_PARAMETERS")
    rows=json.loads(raw_price)
    if not isinstance(rows,list):
        raise ValueError("MARKETWIDE_HISTORY_SNAPSHOT_NOT_LIST")
    # Require the same official reference date and never take ranking from a
    # later-vintage coverage report. That report is diagnostic, not a forecast.
    covpath=root/"rankings/latest_marketwide_drawdown_coverage.json"
    coverage={}
    if covpath.is_file():
        data=json.loads(covpath.read_text(encoding="utf-8"))
        if data.get("price_date")==asof and data.get("schema")=="V8108_MARKETWIDE_DRAWDOWN_COVERAGE_V1":
            coverage={(x["market"],x["code"]):x
                      for x in data.get("issuers",[])
                      if x.get("market") in ("TWSE","TPEX") and isinstance(x.get("code"),str)}
    exclude=set(excluded)
    unique={}
    for r in rows:
        code=r.get("code")
        if (r.get("market")!=market or not isinstance(code,str)
                or CODE.fullmatch(code) is None):
            continue
        if r.get("date")!=asof:
            raise ValueError("MARKETWIDE_HISTORY_SNAPSHOT_DATE_MISMATCH")
        if code in unique:
            raise ValueError("MARKETWIDE_HISTORY_DUPLICATE_ISSUER")
        unique[code]=r
    eligible=[]
    for code,r in unique.items():
        if code in exclude or not _positive(r.get("close")):
            continue
        if (root/"prices/issuer_history"/market/(code+".json")).is_file():
            continue
        c=coverage.get((market,code))
        if c is not None and (c.get("session_coverage") or {}).get("60") is True:
            continue
        turnover=r.get("turnover_ntd")
        # Turnover ranking is only data-collection order, not an investment
        # recommendation, and not an execution-capacity certificate.
        eligible.append((-(turnover if _positive(turnover) else 0),code))
    return [code for _,code in sorted(eligible)[:cap]]
