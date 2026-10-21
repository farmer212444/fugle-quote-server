#!/usr/bin/env python3
"""V8.9.5 ETF PCF exposure-flow research, never institutional executed buying.

Inputs are independently archived, dated issuer PCFs/holdings snapshots. A PCF
basket is not necessarily a fund's actual holdings or secondary-market orders.
Without contemporaneous, provenance-checked snapshots, return BLOCKED, not
fabricated stocks, flow amounts, A+ upgrades or forward return probabilities.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

TAIPEI = timezone(timedelta(hours=8))
CODE = re.compile(r"[0-9]{4}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
SUPPORTED_BASIS = {"ISSUER_PCF_BASKET", "ACTUAL_FUND_HOLDINGS"}
LIMITS = [
    "ETF share creations/redemptions are not executed exchange stock buy/sell orders.",
    "PCF basket weights can differ from actual fund holdings; cash substitutions are excluded.",
    "Changes in published weights also reflect market price drift, not just trades.",
    "Multiple ETFs tracking the same index do not provide independent active-manager confirmation.",
    "Only provenance-checked, dated issuer snapshots and eligible official sessions enter flow estimates.",
    "No calibrated expected returns, ETF trade execution claims, valuation/PE changes, or A+ certification.",
]

def _time(raw):
    if not isinstance(raw, str) or not raw:
        raise ValueError("TIMESTAMP_MISSING")
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return result

def _date(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("DATE_INVALID")
    return date.fromisoformat(raw)

def _number(value, *, positive=False, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("NUMERIC_INVALID")
    if value < 0 or (positive and value <= 0) or (not allow_zero and value == 0):
        raise ValueError("NUMERIC_NEGATIVE_OR_ZERO")
    return float(value)

def _snapshot(raw, asof):
    if not isinstance(raw, dict):
        raise ValueError("ETF_SNAPSHOT_NOT_OBJECT")
    code = str(raw.get("etf_code", ""))
    if not CODE.fullmatch(code):
        raise ValueError("ETF_CODE_INVALID")
    if raw.get("fund_type") != "TAIWAN_EQUITY_UNLEVERAGED":
        raise ValueError("ETF_FUND_TYPE_UNSUPPORTED")
    effective = _date(raw.get("effective_date"))
    published = _time(raw.get("published_at"))
    if published > asof or effective > asof.astimezone(TAIPEI).date():
        raise ValueError("ETF_FUTURE_PIT_INPUT")
    if effective > published.astimezone(TAIPEI).date() + timedelta(days=7):
        raise ValueError("ETF_EFFECTIVE_DATE_IMPLAUSIBLE")
    source = str(raw.get("source_url", ""))
    url = urlparse(source)
    if url.scheme != "https" or not url.hostname or not raw.get("issuer"):
        raise ValueError("ETF_ISSUER_SOURCE_MISSING")
    if raw.get("issuer_source_verified") is not True or not HASH.fullmatch(str(raw.get("raw_sha256", ""))):
        raise ValueError("ETF_RAW_ISSUER_EVIDENCE_UNVERIFIED")
    basis = raw.get("weight_basis")
    if basis not in SUPPORTED_BASIS:
        raise ValueError("ETF_WEIGHT_BASIS_UNVERIFIED")
    units = _number(raw.get("units_outstanding"), positive=True)
    if not units.is_integer():
        raise ValueError("ETF_UNITS_NOT_INTEGER")
    nav = _number(raw.get("nav_per_unit_twd"), positive=True)
    items = raw.get("constituents")
    if not isinstance(items, list) or not items:
        raise ValueError("ETF_BASKET_MISSING")
    names = set()
    weights = {}
    substitutes = set()
    total = 0.0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("ETF_CONSTITUENT_MALFORMED")
        stock = str(item.get("code", ""))
        if not CODE.fullmatch(stock) or stock in names:
            raise ValueError("ETF_STOCK_ID_OR_DUPLICATE")
        names.add(stock)
        weight = _number(item.get("weight"))
        if weight > 1:
            raise ValueError("ETF_WEIGHT_OVER_ONE")
        total += weight
        if item.get("cash_substitution") is True:
            substitutes.add(stock)
        elif item.get("cash_substitution") is False:
            weights[stock] = weight
        else:
            raise ValueError("ETF_CASH_SUBSTITUTION_UNKNOWN")
    if total > 1.0001:
        raise ValueError("ETF_WEIGHTS_EXCEED_100PCT")
    index_family = str(raw.get("index_family", "")).strip()
    return dict(etf_code=code, effective_date=effective.isoformat(),
                published_at=published.isoformat(), units=units, nav=nav,
                source_url=source, raw_sha256=raw["raw_sha256"], issuer=raw["issuer"],
                weight_basis=basis, index_family=index_family or None,
                weights=weights, substitutions=substitutes)

def _interval(old, new, prices):
    if old["etf_code"] != new["etf_code"] or old["effective_date"] >= new["effective_date"]:
        raise ValueError("ETF_INTERVAL_INVALID")
    # Prior NAV and prior constituents isolate share-unit creation exposure
    # without incorrectly calling price-driven weight changes ETF trades.
    delta = new["units"] - old["units"]
    flow_ntd = delta * old["nav"]
    by_stock = {}
    for stock, weight in old["weights"].items():
        if stock not in new["substitutions"] and stock in prices:
            by_stock[stock] = flow_ntd * weight
    return dict(etf_code=old["etf_code"], date=new["effective_date"],
                prior_date=old["effective_date"], units_change=int(delta),
                units_change_pct=round(100 * delta / old["units"], 5),
                estimated_fund_creation_ntd=round(flow_ntd, 2),
                stock_flow_exposure_ntd=by_stock, weight_basis=old["weight_basis"],
                index_family=old["index_family"], not_stock_trading=True)

def _price_map(rows, date_string):
    if not isinstance(rows, list) or not rows:
        raise ValueError("OFFICIAL_PRICE_ROWS_MISSING")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("date") != date_string:
            continue
        code = str(row.get("code", ""))
        if not CODE.fullmatch(code):
            continue
        turnover = row.get("turnover_ntd")
        if isinstance(turnover, (int, float)) and not isinstance(turnover, bool) and math.isfinite(turnover) and turnover > 0:
            if code in result:
                raise ValueError("DUPLICATE_OFFICIAL_PRICE_CODE")
            result[code] = float(turnover)
    if not result:
        raise ValueError("OFFICIAL_REFERENCE_TURNOVER_UNAVAILABLE")
    return result

def analyze(records, session_dates, price_rows, price_date, *, asof, research=None):
    cut = _time(asof)
    pdate = _date(price_date)
    if pdate > cut.astimezone(TAIPEI).date():
        raise ValueError("FUTURE_REFERENCE_PRICE")
    market_turnover = _price_map(price_rows, price_date)
    sessions = sorted(set(_date(d).isoformat() for d in session_dates))
    if price_date not in sessions:
        raise ValueError("REFERENCE_PRICE_NOT_VERIFIED_SESSION")
    # Historical runs use exact disclosed session dates; do not pretend that
    # arbitrary adjacent calendar dates are consecutive exchange sessions.
    sessions = [d for d in sessions if d <= price_date]
    if len(sessions) != len(session_dates) or sessions[-1] != price_date:
        raise ValueError("ETF_SESSION_CALENDAR_INVALID")
    valid, excluded = defaultdict(dict), []
    for ix, raw in enumerate(records):
        try:
            row = _snapshot(raw, cut)
            key, d = row["etf_code"], row["effective_date"]
            if d not in sessions:
                raise ValueError("ETF_EFFECTIVE_SESSION_NOT_ARCHIVED")
            if d in valid[key]:
                raise ValueError("ETF_DUPLICATE_SESSION")
            valid[key][d] = row
        except (ValueError, TypeError, KeyError) as exc:
            excluded.append(dict(position=ix, etf_code=str(raw.get("etf_code", "")) if isinstance(raw, dict) else None,
                                 reason=str(exc)))
    horizons = {1: defaultdict(float), 5: defaultdict(float), 20: defaultdict(float)}
    per_etf = []
    for etf, data in sorted(valid.items()):
        latest = data.get(price_date)
        if not latest:
            per_etf.append(dict(etf_code=etf, status="CURRENT_SESSION_PCF_MISSING"))
            continue
        available = []
        for days in (1, 5, 20):
            if len(sessions) < days + 1:
                continue
            window = sessions[-(days + 1):]
            if not all(d in data for d in window):
                continue
            intervals = [_interval(data[a], data[b], market_turnover) for a, b in zip(window, window[1:])]
            by_stock = defaultdict(float)
            for item in intervals:
                for stock, flow in item["stock_flow_exposure_ntd"].items():
                    by_stock[stock] += flow
            for stock, flow in by_stock.items():
                horizons[days][stock] += flow
            available.append(days)
        per_etf.append(dict(etf_code=etf, status="RESEARCH_PROXY_ONLY" if available else "INSUFFICIENT_SESSION_HISTORY",
                            effective_date=price_date, horizons_available=available,
                            weight_basis=latest["weight_basis"], index_family=latest["index_family"],
                            source_url=latest["source_url"], raw_sha256=latest["raw_sha256"]))
    full_5 = sum(5 in x.get("horizons_available", []) for x in per_etf)
    full_20 = sum(20 in x.get("horizons_available", []) for x in per_etf)
    covered = sum(1 in x.get("horizons_available", []) for x in per_etf)
    stocks = sorted(set().union(*(set(horizons[k]) for k in (1, 5, 20))))
    ranking = []
    for stock in stocks:
        one = horizons[1].get(stock) if stock in horizons[1] else None
        five = horizons[5].get(stock) if stock in horizons[5] else None
        twenty = horizons[20].get(stock) if stock in horizons[20] else None
        one = round(one, 2) if one is not None else None
        five = round(five, 2) if five is not None else None
        twenty = round(twenty, 2) if twenty is not None else None
        # An estimate, not a stock purchase: flows may involve in-kind creation,
        # arbitrage inventory, other instruments and timing differences.
        ranking.append(dict(code=stock, estimated_1d_exposure_ntd=one,
                            estimated_5d_exposure_ntd=five,
                            estimated_20d_exposure_ntd=twenty,
                            one_day_exposure_to_market_turnover=round(one / market_turnover[stock], 4) if one is not None else None,
                            actual_institutional_net_buy_verified=False,
                            formal_grade_changed=False))
    ranking.sort(key=lambda r:(-(r["estimated_20d_exposure_ntd"] if r["estimated_20d_exposure_ntd"] is not None else
                                   r["estimated_5d_exposure_ntd"] if r["estimated_5d_exposure_ntd"] is not None else
                                   r["estimated_1d_exposure_ntd"] if r["estimated_1d_exposure_ntd"] is not None else 0),
                                r["code"]))
    status = ("BLOCKED_MISSING_VERIFIED_ETF_PCF" if not valid else
              "BLOCKED_MISSING_COMPARABLE_ETF_SESSIONS" if not covered else
              "PARTIAL_ETF_EXPOSURE_RESEARCH_NOT_TRADES" if not full_20 else
              "ETF_EXPOSURE_RESEARCH_NOT_TRADES")
    return dict(status=status, price_date=price_date, estimate_vintage=asof,
                etf_count_with_at_least_1d=covered, etf_count_with_full_5d=full_5,
                etf_count_with_full_20d=full_20, excluded_records=excluded,
                etf_coverage=per_etf, stock_flow_research=ranking, top20=ranking[:20],
                formal_Aplus_count_unchanged=(research or {}).get("formal_Aplus_count"),
                formal_Aplusplus_count_unchanged=(research or {}).get("formal_Aplusplus_count"),
                model_pe_or_eps_changed=False, stock_buy_execution_verified=False,
                source_evidence_independently_audited=False, limits=LIMITS)

def render(result):
    lines = ["# ETF申贖曝險研究：V8.9.5", "",
             f"狀態：{result['status']}；行情日：{result['price_date']}；估計形成：{result['estimate_vintage']}。", "",
             f"至少具有前後兩個有效交易日PCF的ETF：{result['etf_count_with_at_least_1d']}；具有完整5日：{result['etf_count_with_full_5d']}；完整20日：{result['etf_count_with_full_20d']}。", "",
             "**這是根據ETF份額變化與前期籃子權重推算的股票曝險，不是實際股票買賣超或2027股價預測。**", "",
             "|序|股票|1日曝險推估(百萬元)|5日(百萬元)|20日(百萬元)|1日曝險/單日成交額|",
             "|---:|---|---:|---:|---:|---:|"]
    def f(x, scale=1):
        return "待補" if x is None else f"{x / scale:+.2f}"
    for i, r in enumerate(result["top20"], 1):
        lines.append(f"|{i}|{r['code']}|{f(r['estimated_1d_exposure_ntd'],1e6)}|{f(r['estimated_5d_exposure_ntd'],1e6)}|{f(r['estimated_20d_exposure_ntd'],1e6)}|{f(r['one_day_exposure_to_market_turnover'])}|")
    if not result["top20"]:
        lines.append("|—|尚無可驗證的連續PCF|待補|待補|待補|待補|")
    lines += ["", "## 資料與信號限制", "", *("- " + msg for msg in result["limits"]), ""]
    return "\n".join(lines)

def run(root, asof):
    data_dir = Path(root)
    manifest_path = data_dir / "prices" / "latest_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    price_date = manifest["date"]
    raw_prices = (data_dir / "prices" / (price_date + ".json")).read_bytes()
    if hashlib.sha256(raw_prices).hexdigest() != manifest["normalized_sha256"]:
        raise ValueError("OFFICIAL_REFERENCE_PRICE_HASH_MISMATCH")
    prices = json.loads(raw_prices)
    session_dates = [p.stem for p in (data_dir / "prices").glob("????-??-??.json")]
    records = []
    for fp in sorted((data_dir / "etf" / "pcf").glob("????-??-??/*.json")):
        try:
            record = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            record = {"etf_code": fp.stem, "_error": f"MALFORMED_PCF_FILE:{exc}"}
        records.append(record)
    research_path = data_dir / "rankings" / "latest_research.json"
    research = json.loads(research_path.read_text(encoding="utf-8")) if research_path.exists() else {}
    report = analyze(records, session_dates, prices, price_date, asof=asof, research=research)
    path = data_dir / "rankings"
    path.mkdir(parents=True, exist_ok=True)
    (path / "v895_etf_accumulation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (path / "v895_etf_accumulation.md").write_text(render(report), encoding="utf-8")
    return report

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="tw-market-data")
    ap.add_argument("--asof", default=datetime.now(TAIPEI).isoformat())
    args = ap.parse_args()
    result = run(args.data_dir, args.asof)
    print(json.dumps(dict(status=result["status"], eligible_etfs=result["etf_count_with_at_least_1d"],
                          stocks=len(result["stock_flow_research"]), formal_grade_changes=0), ensure_ascii=False))
