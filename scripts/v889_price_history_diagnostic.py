#!/usr/bin/env python3
"""Fail-closed diagnostics for dated daily price archives; never fabricate missing sessions."""
import argparse
import json
from pathlib import Path

def diagnose(folder, reference_date):
    paths=sorted((p for p in Path(folder).glob("????-??-??.json") if p.stem<=reference_date),reverse=True)
    dates=[p.stem for p in paths]
    return {"reference_date":reference_date,"available_sessions":len(dates),
            "latest_archived_session":dates[0] if dates else None,
            "earliest_archived_session":dates[-1] if dates else None,
            "missing_to_20_sessions":max(0,20-len(dates)),
            "twenty_session_certified":False,
            "note":"Archive count is not per-issuer liquidity certification; original market sources, turnover, dates and exit capacity still require validation."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--prices",default="tw-market-data/prices")
    p.add_argument("--manifest",default="tw-market-data/prices/latest_manifest.json")
    p.add_argument("--output",default="tw-market-data/rankings/v889_price_history_diagnostic.json")
    a=p.parse_args()
    manifest=json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    result=diagnose(a.prices,manifest["date"])
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))

if __name__=="__main__":main()
