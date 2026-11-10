#!/usr/bin/env python3
"""Prospective risk-cohort registry. Never a backdated PIT trading backtest.

The first immutable registration is AFTER the latest market report was formed.
A historical price-date must not become a fabricated same-day trade signal.
A future outcome is only eligible after this real registration timestamp.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.v897_freeze_model_vintage import aware

SCHEMA = "V8108_PROSPECTIVE_DRAWDOWN_COHORT_V1"
SOURCE_SCHEMA = "V8108_MARKETWIDE_DRAWDOWN_COVERAGE_V1"
FOLDER = "experiments/prospective_drawdown_v1/cohorts"
TAIPEI = dt.timezone(dt.timedelta(hours=8))
STATUS = {"PAUSE_SHARP_DRAWDOWN_RESEARCH", "WATCH_RELATIVE_WEAKNESS",
          "NO_PROVISIONAL_PRICE_THRESHOLD_HIT_NOT_CERTIFIED_SAFE",
          "PENDING_PRICE_HISTORY_OR_COMPANY_ACTIONS",
          "PENDING_INVALID_HISTORY_PACKET", "PENDING_VERIFIED_BENCHMARK_ASOF",
          "PENDING_CONFLICTING_HISTORY_VERSUS_DAILY", "PENDING_MISSING_CURRENT_CLOSE"}

def rawhash(blob):
    return hashlib.sha256(blob).hexdigest()

def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def require(condition, reason):
    if not condition:
        raise ValueError("PROSPECTIVE_DRAWDOWN_"+reason)

def read(path):
    return json.loads(Path(path).read_bytes())

def seal(core):
    return {**core, "cohort_sha256": rawhash(canonical(core))}

def verify(path):
    frozen = read(path)
    require(frozen.get("schema")==SCHEMA,"WRONG_SCHEMA")
    core = {k:v for k,v in frozen.items() if k!="cohort_sha256"}
    require(frozen.get("cohort_sha256")==rawhash(canonical(core)),
            "CHANGED_COHORT_BYTES")
    require(frozen.get("price_date")==Path(path).stem,
            "FILENAME_PRICE_DATE_MISMATCH")
    registered=aware(frozen["registered_at_utc"])
    formation=aware(frozen["model_formed_at"])
    close=dt.datetime.fromisoformat(frozen["price_date"]+"T13:30:00+08:00")
    require(formation>=close and registered>=formation,
            "RETROSPECTIVE_SIGNAL_OR_FUTURE_MODEL")
    require(frozen.get("first_eligible_market_open") is None,
            "UNVERIFIED_MARKET_OPEN_CLAIM")
    require(frozen.get("formal_Aplus_added")==0 and frozen.get("trades_created")==0
            and frozen.get("verified_future_returns")==0
            and frozen.get("official_historical_PIT_certified") is False
            and frozen.get("corporate_actions_verified") is False
            and frozen.get("oos_predictive_edge_certified") is False,
            "FALSE_CERTIFICATION")
    entries=frozen.get("issuers",[])
    keys=[(x.get("market"),x.get("code")) for x in entries]
    require(len(keys)==frozen.get("issuer_count") and len(keys)==len(set(keys)),
            "DUPLICATE_OR_MISSING_ISSUERS")
    require(all(x.get("risk_state") in STATUS for x in entries),
            "INVALID_RISK_STATE")
    require(all(x.get("source_close") is None or
                (type(x["source_close"]) in (int,float)
                 and math.isfinite(x["source_close"]) and x["source_close"]>0)
                for x in entries), "INVALID_SOURCE_PRICE")
    return frozen

def make(root, now, git_sha=None):
    root=Path(root)
    now=now.astimezone(dt.timezone.utc)
    risk_path=root/"rankings/latest_marketwide_drawdown_coverage.json"
    quality_path=root/"rankings/v8a5_quality_decision_lane.json"
    report_blob=risk_path.read_bytes()
    quality_blob=quality_path.read_bytes()
    report=json.loads(report_blob)
    quality=json.loads(quality_blob)
    require(report.get("schema")==SOURCE_SCHEMA,"RISK_SCHEMA_MISMATCH")
    require(quality.get("schema")=="V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
            "QUALITY_SCHEMA_MISMATCH")
    date=report.get("price_date")
    require(isinstance(date,str) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}",date),
            "PRICE_DATE_INVALID")
    session_day=dt.date.fromisoformat(date)
    require(session_day<=now.astimezone(TAIPEI).date(),
            "FUTURE_REFERENCE_PRICE")
    # Old research cannot be re-issued as if its signal existed months ago.
    # This guard also limits accidental stale reports while allowing weekends.
    require((now.date()-session_day).days<=7,"STALE_FIRST_REGISTRATION")
    formation=aware(report.get("estimate_vintage"))
    require(formation<=now,"FUTURE_ESTIMATE")
    require(formation>=dt.datetime.fromisoformat(date+"T13:30:00+08:00"),
            "ESTIMATE_BEFORE_MARKET_CLOSE")
    require(quality.get("asof_price_date")==date
            and quality.get("estimate_vintage")==report.get("estimate_vintage"),
            "QUALITY_TIME_OR_DATE_CONFLICT")
    require((report.get("source_sha256") or {}).get("quality")==rawhash(quality_blob),
            "QUALITY_CONTENT_HASH_MISMATCH")
    require(report.get("formal_Aplus_added")==0
            and report.get("trade_signals_created")==0
            and report.get("calibrated_oos_strategy_improvement") is False
            and report.get("corporate_actions_and_total_returns_verified") is False
            and report.get("historical_issuer_capture_point_in_time_verified") is False,
            "UNVERIFIED_TRADING_OR_PIT_PROMOTION")
    market_path=root/"prices"/(date+".json")
    quotes_blob=market_path.read_bytes()
    price_manifest=read(root/"prices/latest_manifest.json")
    require(price_manifest.get("date")==date
            and price_manifest.get("normalized_sha256")==rawhash(quotes_blob)
            and report["source_sha256"].get("dated_prices",{}).get(date)==rawhash(quotes_blob),
            "MARKET_PRICE_SOURCE_HASH_CONFLICT")
    quotes=json.loads(quotes_blob)
    require(isinstance(quotes,list) and len(quotes)==report.get("marketwide_snapshot_rows"),
            "MARKET_UNIVERSE_COUNT_MISMATCH")
    source_index={}
    for q in quotes:
        key=(q.get("market"),q.get("code"))
        require(key[0] in ("TWSE","TPEX") and isinstance(key[1],str)
                and re.fullmatch(r"\d{4}",key[1]) and key not in source_index
                and q.get("date")==date,"MARKET_QUOTE_IDENTITY_CONFLICT")
        source_index[key]=q
    entries=[]
    for row in report["issuers"]:
        key=(row.get("market"),row.get("code"))
        require(key in source_index,"RISK_ISSUER_NOT_IN_MARKET")
        q=source_index.pop(key)
        price=q.get("close")
        if type(price) not in (int,float) or not math.isfinite(price) or price<=0:
            price=None
        require(row.get("latest_close")==price,"RISK_CLOSE_SOURCE_CONFLICT")
        require(row.get("status") in STATUS,"RISK_STATUS_INVALID")
        entries.append(dict(market=key[0],code=key[1],
                            source_close=price,risk_state=row["status"],
                            provisional_pause=row.get("provisional_pause") is True,
                            coverage_20=bool(row.get("session_coverage",{}).get("20")),
                            coverage_60=bool(row.get("session_coverage",{}).get("60"))))
    require(not source_index,"MISSING_RISK_MEMBERS")
    entries.sort(key=lambda r:(r["market"],r["code"]))
    counts={s:sum(r["risk_state"]==s for r in entries) for s in sorted(STATUS)}
    core=dict(schema=SCHEMA,policy="RESEARCH_SHADOW_PRECOMMITTED_V1",
        price_date=date,model_formed_at=report["estimate_vintage"],
        registered_at_utc=now.isoformat(),first_eligible_market_open=None,
        next_session_eligible_only_after=now.isoformat(),
        source_git_sha=git_sha,
        issuer_count=len(entries),valid_closes=sum(r["source_close"] is not None for r in entries),
        source_sha256=dict(risk_report=rawhash(report_blob),quality=rawhash(quality_blob),
                           market_quotes=rawhash(quotes_blob)),
        formation_thresholds="5d -15pct;10d -20pct;10d peak drawdown -20pct;10d weak -10pct and relative lag >=5pp",
        risk_counts=counts,issuers=entries,
        horizon_sessions=[21,63],verified_future_returns=0,
        future_sessions_elapsed=0,entry_fillability_verified=False,
        historical_universe_membership_verified=False,
        corporate_actions_verified=False,
        official_historical_PIT_certified=False,
        oos_predictive_edge_certified=False,
        formal_Aplus_added=0,trades_created=0,
        interpretation="FIRST_PROSPECTIVE_RISK_REGISTRATION_NOT_PAST_SIGNAL_OR_TRADE")
    return seal(core)

def issue(root, now=None, git_sha=None):
    root=Path(root)
    now=now or dt.datetime.now(dt.timezone.utc)
    require(now.tzinfo is not None,"NAIVE_NOW")
    if git_sha is not None:
        require(isinstance(git_sha,str) and re.fullmatch(r"[a-f0-9]{40}",git_sha),
                "INVALID_SOURCE_COMMIT_SHA")
    date=read(root/"rankings/latest_marketwide_drawdown_coverage.json").get("price_date")
    require(isinstance(date,str) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}",date),
            "SOURCE_DATE_MISSING")
    path=root/FOLDER/(date+".json")
    if path.exists():
        item=verify(path)
        return dict(status="ALREADY_FROZEN_FIRST_REGISTRATION_PRESERVED",
                    path=str(path),registered_at_utc=item["registered_at_utc"],
                    price_date=date,issuer_count=item["issuer_count"],
                    future_verified=0)
    obj=make(root,now,git_sha)
    path.parent.mkdir(parents=True,exist_ok=True)
    # x mode prevents silent overwrite. Commit publication preserves this file.
    with path.open("x",encoding="utf-8") as stream:
        json.dump(obj,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    verify(path)
    return dict(status="FIRST_PROSPECTIVE_REGISTRATION_NO_OOS_RESULTS",
                path=str(path),registered_at_utc=obj["registered_at_utc"],
                price_date=obj["price_date"],issuer_count=obj["issuer_count"],
                risk_counts=obj["risk_counts"],future_verified=0)

def report(root):
    folder=Path(root)/FOLDER
    outputs=[]
    for path in sorted(folder.glob("20??-??-??.json")):
        obj=verify(path)
        outputs.append(dict(price_date=obj["price_date"],
              registered_at_utc=obj["registered_at_utc"],issuer_count=obj["issuer_count"],
              risk_counts=obj["risk_counts"],future_verified=0))
    return dict(schema="V8108_PROSPECTIVE_DRAWDOWN_REGISTRY_STATUS_V1",
        registered_cohorts=len(outputs),verified_forward_returns=0,
        adjusted_total_return_scores=None,
        causal_avoidance_effect=None,
        oos_predictive_edge_certified=False,formal_Aplus_added=0,
        registration_records=outputs)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root",default="tw-market-data")
    ap.add_argument("--source-git-sha",default=None)
    ap.add_argument("mode",choices=["issue","report"])
    args=ap.parse_args()
    if args.mode=="issue":
        result=issue(args.data_root,git_sha=args.source_git_sha)
    else:
        result=report(args.data_root)
    print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
    main()
