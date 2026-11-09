#!/usr/bin/env python3
"""Marketwide 5/10/20/60 reference-session price-risk and coverage audit.

No A+ promotion, orders, history PIT certification, corporate-action adjustment,
or calibrated drawdown protection is implied by this retrospective research.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from scripts.recent_drawdown_guard import (load_benchmark, load_closes,
                                           timestamp, ensure)
from scripts.run_research_pipeline import atomic_json

SCHEMA = "V8108_MARKETWIDE_DRAWDOWN_COVERAGE_V1"
WINDOWS = (5, 10, 20, 60)

def valid_close(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0

def history_closes(root, asof, current_keys):
    """Read available issuer-history files, never assert they cover the market."""
    histories = {}
    issues = {}
    receipts = {}
    for market in ("TWSE", "TPEX"):
        folder = root / "prices/issuer_history" / market
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            code = path.stem
            key = (market, code)
            if key not in current_keys:
                continue
            raw = path.read_bytes()
            receipts[market + ":" + code] = hashlib.sha256(raw).hexdigest()
            try:
                packet = json.loads(raw)
                ensure(packet.get("issuer") == code and packet.get("market") == market,
                       "HISTORY_IDENTITY_MISMATCH")
                # Reject a historical packet anchored after the evaluation date.
                origin_asof = packet.get("price_reference_asof")
                ensure(isinstance(origin_asof, str) and origin_asof <= asof,
                       "HISTORY_FUTURE_REFERENCE")
                ensure(packet.get("share_adjusted_history") is not True,
                       "HISTORY_MIXED_ADJUSTED_PRICES")
                rows = packet.get("sessions")
                ensure(isinstance(rows, list), "HISTORY_SESSIONS_MISSING")
                seen = {}
                for row in rows:
                    day, close = row.get("date"), row.get("close")
                    ensure(isinstance(day, str), "HISTORY_DAY_INVALID")
                    dt.date.fromisoformat(day)
                    if day > asof:
                        # A reference packet can have future rows; never use them.
                        continue
                    if row.get("code", code) != code or row.get("market", market) != market:
                        raise ValueError("HISTORY_ROW_IDENTITY_MISMATCH")
                    if not valid_close(close):
                        continue
                    value = float(close)
                    if day in seen and seen[day] != value:
                        raise ValueError("HISTORY_DUPLICATE_PRICE_CONFLICT")
                    seen[day] = value
                histories[key] = seen
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                issues[key] = str(exc)[:180]
    return histories, issues, receipts

def reference_windows(benchmark_levels, asof):
    dates = sorted(d for d in benchmark_levels if d <= asof)
    if not dates or dates[-1] != asof:
        return None
    return dates

def calc(stock, benchmark, days, n):
    """Require all n+1 identical reference session dates, not n sparse points."""
    if len(days) < n + 1:
        return None
    dates = days[-n-1:]
    if any(d not in stock or d not in benchmark for d in dates):
        return None
    a, b = stock[dates[0]], stock[dates[-1]]
    bm_a, bm_b = benchmark[dates[0]], benchmark[dates[-1]]
    if not all(valid_close(v) for v in (a, b, bm_a, bm_b)):
        return None
    prices = [stock[d] for d in dates]
    ret = round(100 * (b/a - 1), 6)
    relative = round(100 * ((b/a) - (bm_b/bm_a)), 6)
    peak = round(100 * (b/max(prices) - 1), 6)
    return dict(return_pct=ret, peak_to_current_pct=peak,
                price_minus_taiex_tr_pp=relative,
                start=dates[0], end=dates[-1], reference_sessions=n+1)

def classify(windows, action_pending):
    short = windows.get("5")
    medium = windows.get("10")
    if ((short and short["return_pct"] <= -15) or
        (medium and (medium["return_pct"] <= -20 or
                     medium["peak_to_current_pct"] <= -20))):
        return "PAUSE_SHARP_DRAWDOWN_RESEARCH"
    if medium and medium["return_pct"] <= -10 and medium["price_minus_taiex_tr_pp"] <= -5:
        return "WATCH_RELATIVE_WEAKNESS"
    if action_pending:
        return "PENDING_PRICE_HISTORY_OR_COMPANY_ACTIONS"
    return "NO_PROVISIONAL_PRICE_THRESHOLD_HIT_NOT_CERTIFIED_SAFE"

def build(root):
    root = Path(root)
    quality_path = root / "rankings/v8a5_quality_decision_lane.json"
    raw_quality = quality_path.read_bytes()
    quality = json.loads(raw_quality)
    ensure(quality.get("schema") == "V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
           "SOURCE_QUALITY_SCHEMA")
    asof = quality.get("asof_price_date")
    vintage_label = quality.get("estimate_vintage")
    ensure(isinstance(asof, str) and isinstance(vintage_label, str),
           "SOURCE_QUALITY_CLOCK")
    dt.date.fromisoformat(asof)
    vintage = timestamp(vintage_label)
    ensure(vintage >= dt.datetime.fromisoformat(asof+"T13:30:00+08:00"),
           "PRICE_NOT_YET_CLOSED")
    ensure(quality.get("formal_Aplus_added") == 0, "FORMAL_A_PLUS_NOT_ZERO")
    snap, snap_receipts = load_closes(root, asof)
    # Marketwide mother set comes from the ACTUAL asof price snapshot, not
    # from a ranked subset or the existence of optional history.
    current = {k:values[-1][1] for k,values in snap.items()
               if values and values[-1][0] == asof}
    history, history_issues, history_receipts = history_closes(root, asof, set(current))
    benchmark, benchmark_receipts = load_benchmark(root, asof, vintage)
    days = reference_windows(benchmark, asof)
    index = {}
    for row in quality.get("base_upside_order", []):
        code = row.get("code")
        if isinstance(code, str) and code not in index:
            index[code] = dict(research_base_upside_pct=row.get("base_upside_pct"),
                               research_name=row.get("name"))
    all_rows = []
    for market,code in sorted(current):
        key=(market,code)
        snapshot_dates = dict(snap[key])
        merged = dict(history.get(key, {}))
        conflicting = any(d in merged and merged[d] != p
                          for d,p in snapshot_dates.items())
        if conflicting:
            # A disagreement is not a corporate action adjustment to guess.
            merged = snapshot_dates
        else:
            merged.update(snapshot_dates)
        windows = {}
        for n in WINDOWS:
            windows[str(n)] = (calc(merged,benchmark,days,n)
                               if days is not None and not conflicting else None)
        complete = {str(n): windows[str(n)] is not None for n in WINDOWS}
        n_sessions = (len(days) if days is not None else 0)
        gaps = {str(n): (max(0,n+1-min(n+1,n_sessions)) +
                            (sum(d not in merged for d in days[-(n+1):])
                             if days is not None and n_sessions >= n+1 else 0))
                for n in WINDOWS}
        if conflicting:
            status="PENDING_CONFLICTING_HISTORY_VERSUS_DAILY"
        elif key in history_issues:
            status="PENDING_INVALID_HISTORY_PACKET"
        elif days is None:
            status="PENDING_VERIFIED_BENCHMARK_ASOF"
        else:
            status=classify(windows,not all(complete.values()))
        w5,w10=windows["5"],windows["10"]
        flag = status == "PAUSE_SHARP_DRAWDOWN_RESEARCH"
        row=dict(code=code,market=market,
                 name=index.get(code,{}).get("research_name"),
                 latest_close=current[key],
                 status=status,provisional_pause=flag,
                 risk_evidence_is_not_formal_trade_permission=True,
                 has_issuer_history_file=key in history,
                 history_issue=history_issues.get(key),
                 price_conflict=conflicting,
                 current_company_actions_verified=False,
                 historical_PIT_at_entry_verified=False,
                 reference_calendar_is_not_individual_trading_calendar=True,
                 session_coverage=complete,missing_reference_sessions=gaps,
                 windows=windows)
        row.update(index.get(code,{}))
        all_rows.append(row)
    counts=collections.Counter(r["status"] for r in all_rows)
    markets=collections.Counter(r["market"] for r in all_rows)
    coverage={str(n):sum(r["session_coverage"][str(n)] for r in all_rows)
              for n in WINDOWS}
    return dict(schema=SCHEMA,model="V8.10.8",
        price_date=asof,estimate_vintage=vintage_label,
        marketwide_current_quotes=len(all_rows),
        by_market=dict(markets),issuer_history_available=len(history),
        reference_calendar_sessions=len(days or []),
        reference_calendar_taiex_tr_not_issuer_exchange_calendar=True,
        full_exchange_session_calendar_verified=False,
        corporate_actions_and_total_returns_verified=False,
        historical_issuer_capture_point_in_time_verified=False,
        company_action_risk_unresolved_for_all=True,
        guaranteed_execution_or_exit_verified=False,
        formal_Aplus_added=0,trade_signals_created=0,
        calibrated_oos_strategy_improvement=False,
        full_market_rank_is_not_2027_return_rank=True,
        provisional_rules_used="5d<=-15pct_or_10d<=-20pct_or_10d_peak_to_close<=-20pct;relative10d<=-10pct_and_lags_index>=5pp",
        coverage_counts=coverage,status_counts=dict(counts),
        source_sha256=dict(quality=hashlib.sha256(raw_quality).hexdigest(),
                           dated_prices=snap_receipts,
                           issuer_history=history_receipts,
                           benchmark_months=benchmark_receipts),
        issuers=all_rows)

def markdown(report):
    lines=["# V8.10.8 全市場急跌／20／60交易日覆蓋研究",
      "", "價格："+report["price_date"]+"；估值形成："+report["estimate_vintage"],
      "此為未經除權息調整之價格研究，不能推定完整 PIT 回測、下單可行性或 A+。",
      "", "|指標|數量|","|---|---:|",
      "|本日有收盤價公司筆數|"+str(report["marketwide_current_quotes"])+"|",
      "|有個股歷史資料檔|"+str(report["issuer_history_available"])+"|"]
    for n,count in report["coverage_counts"].items():
        lines.append("|完整 "+n+" 個基準交易日區間的價差可計算|"+str(count)+"|")
    lines+=["","## 本次急跌警報（暫定、未校準）",
            "","|股票|5日變動|10日變動|20日變動|60日變動|警報|",
            "|---|---:|---:|---:|---:|---|"]
    def fmt(row,n):
        data=row["windows"][str(n)]
        return "待補" if data is None else "%+.1f%%" % data["return_pct"]
    flagged=[r for r in report["issuers"] if
             r["status"] in ("PAUSE_SHARP_DRAWDOWN_RESEARCH","WATCH_RELATIVE_WEAKNESS")]
    flagged.sort(key=lambda r:(0 if r["provisional_pause"] else 1,
                r["windows"]["10"]["return_pct"] if r["windows"]["10"] else 0))
    for r in flagged[:35]:
        lines.append("|"+r["code"]+" "+str(r.get("name") or "")+"|"+
                     "|".join(fmt(r,n) for n in WINDOWS)+"|"+r["status"]+"|")
    lines+=["","此表前35筆為警報樣本，完整上市櫃母體與所有未查原因請見同名 JSON。",
      "PIT、20／60日來源完整率、上市櫃個股個別停牌、除權息、成交與滑價未完成正式核證。",
      "不使用事後資料認定事前有訊號；模型 EPS／PE、13項認證與任何交易委託均未變更。",""]
    return "\n".join(lines)

def publish(root):
    result=build(root)
    out=Path(root)/"rankings"
    atomic_json(out/"latest_marketwide_drawdown_coverage.json",result)
    (out/"latest_marketwide_drawdown_coverage.md").write_text(
        markdown(result),encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-root",default="tw-market-data")
    args=p.parse_args()
    doc=publish(args.data_root)
    print(json.dumps(dict(total=doc["marketwide_current_quotes"],
              coverage=doc["coverage_counts"],
              paused=doc["status_counts"].get("PAUSE_SHARP_DRAWDOWN_RESEARCH",0),
              official_Aplus=0,trades=0),ensure_ascii=False))

if __name__=="__main__":
    main()
