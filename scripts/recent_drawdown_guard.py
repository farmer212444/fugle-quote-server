#!/usr/bin/env python3
"""Conservative as-of price drawdown shadow; never a predictive or trading gate.

This reads already archived close snapshots, refuses future rows, and does not
pretend sparse repository snapshots form a complete exchange trading calendar.
The overlay does not modify 2027 EPS/PE, formal A+ gates, or exit decisions.
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
from scripts.run_research_pipeline import atomic_json

SCHEMA = "V8108_RECENT_DRAWDOWN_RESEARCH_SHADOW_V1"
DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
MAX_OBS = 11

def ensure(condition, reason):
    if not condition:
        raise ValueError("DRAWDOWN_" + reason)

def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)

def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    ensure(result.tzinfo is not None, "NAIVE_TIME")
    return result

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def load_closes(root, asof):
    """Repository snapshots, not an attestation of full daily-session coverage."""
    series, receipts = {}, {}
    for path in sorted((root / "prices").glob("*.json")):
        if not DAY_FILE.fullmatch(path.name):
            continue
        day = path.stem
        if day > asof:
            continue
        rows = read_json(path)
        ensure(isinstance(rows, list), "PRICE_FILE_INVALID_" + day)
        seen = set()
        for row in rows:
            ensure(isinstance(row, dict) and row.get("date") == day,
                   "QUOTE_DATE_CONFLICT_" + day)
            code, market, close = row.get("code"), row.get("market"), row.get("close")
            ensure(isinstance(code, str) and code.isdigit()
                   and market in ("TWSE", "TPEX"), "QUOTE_ID_INVALID")
            key = (market, code)
            ensure(key not in seen, "DUPLICATE_QUOTE_" + day + "_" + code)
            seen.add(key)
            if not numeric(close) or close <= 0:
                continue
            series.setdefault(key, []).append((day, float(close)))
        receipts[day] = hashlib.sha256(path.read_bytes()).hexdigest()
    ensure(asof in receipts, "CURRENT_PRICE_SNAPSHOT_MISSING")
    return series, receipts

def load_benchmark(root, asof, vintage):
    """Use only independently dated source receipts that existed by vintage."""
    months = root / "benchmarks/TAIEX_TR/months"
    obs, receipts = {}, {}
    if not months.is_dir():
        return obs, receipts
    for path in sorted(months.glob("*.json")):
        # Source manifests for the total-return benchmark use YYYY-MM.json.
        if not re.fullmatch(r"\d{4}-\d{2}\.json", path.name):
            continue
        if path.stem > asof[:7]:
            continue
        ref = read_json(path)
        rel = ref.get("path")
        if not isinstance(rel, str) or not rel.startswith("benchmarks/TAIEX_TR/originals/") or ".." in Path(rel).parts:
            continue
        original = root / rel
        if not original.is_file():
            continue
        raw = original.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.get("sha256"):
            continue
        packet = json.loads(raw)
        if packet.get("month") != path.stem or packet.get("benchmark_id") != "TAIEX_TR":
            continue
        captured = packet.get("captured_at")
        if not isinstance(captured, str) or timestamp(captured) > vintage:
            continue
        receipts[path.stem] = hashlib.sha256(raw).hexdigest()
        for row in packet.get("rows", []):
            day, level = row.get("date"), row.get("level")
            if not isinstance(day, str) or day[:7] != path.stem or day > asof or not numeric(level) or level <= 0:
                continue
            ensure(day not in obs, "BENCHMARK_DUPLICATE_DATE_" + day)
            obs[day] = float(level)
    return obs, receipts

def build(root):
    root = Path(root)
    quality_path = root / "rankings/v8a5_quality_decision_lane.json"
    source = quality_path.read_bytes()
    quality = json.loads(source)
    ensure(quality.get("schema") == "V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
           "SOURCE_SCHEMA_MISMATCH")
    asof, vintage_label = quality.get("asof_price_date"), quality.get("estimate_vintage")
    ensure(isinstance(asof, str) and isinstance(vintage_label, str),
           "SOURCE_VINTAGE_MISSING")
    dt.date.fromisoformat(asof)
    vintage = timestamp(vintage_label)
    ensure(vintage.date() >= dt.date.fromisoformat(asof), "VINTAGE_PRECEDES_PRICE_DAY")
    close_time = dt.datetime.fromisoformat(asof + "T13:30:00+08:00")
    ensure(vintage >= close_time, "QUOTE_NOT_YET_PUBLISHED_AT_VINTAGE")
    rows = quality.get("base_upside_order")
    ensure(isinstance(rows, list) and quality.get("issuer_count") == len(rows),
           "ISSUER_COUNT_MISMATCH")
    ensure(quality.get("formal_Aplus_added") == 0, "FORMAL_CERTIFICATE_CONFLICT")
    snapshots, price_receipts = load_closes(root, asof)
    market_index, market_receipts = load_benchmark(root, asof, vintage)
    by_code = {}
    for key in snapshots:
        by_code.setdefault(key[1], []).append(key)
    outputs, seen_codes = [], set()
    for row in rows:
        code = row.get("code")
        ensure(isinstance(code, str) and code not in seen_codes, "ISSUER_DUPLICATE_OR_INVALID")
        seen_codes.add(code)
        identities = by_code.get(code, [])
        if len(identities) != 1 or snapshots[identities[0]][-1][0] != asof:
            outputs.append(dict(code=code,name=row.get("name"),
                status="PENDING_MISSING_OR_AMBIGUOUS_CURRENT_QUOTE",
                risk_blocked=False,observation_count=0,
                return_5observations_pct=None,return_10observations_pct=None,
                peak_to_current_10observations_pct=None,
                relative_to_taiex_tr_pct=None,
                complete_20_60_session_history_verified=False))
            continue
        observations = snapshots[identities[0]]
        sampled = observations[-MAX_OBS:]
        count = len(sampled)
        current = sampled[-1][1]
        ret5 = (current / sampled[-6][1] - 1) * 100 if count >= 6 else None
        ret10 = (current / sampled[-11][1] - 1) * 100 if count >= 11 else None
        from_peak = (current / max(p for _,p in sampled) - 1) * 100
        # A reproducible price-only relative proxy, NOT total-return alpha.
        relative = None
        if count >= 11:
            start, end = sampled[0][0], sampled[-1][0]
            if start in market_index and end in market_index:
                relative = (current / sampled[0][1] -
                            market_index[end] / market_index[start]) * 100
        # Floating arithmetic may produce -9.999999999999998 for an exact -10%.
        # Stabilize threshold decisions at micro-percentage-point precision.
        ret5 = round(ret5, 6) if ret5 is not None else None
        ret10 = round(ret10, 6) if ret10 is not None else None
        from_peak = round(from_peak, 6)
        relative = round(relative, 6) if relative is not None else None
        blocked = ((ret5 is not None and ret5 <= -15)
                   or (ret10 is not None and ret10 <= -20)
                   or (count >= 6 and from_peak <= -20))
        relative_weak = (ret10 is not None and ret10 <= -10
                         and relative is not None and relative <= -5)
        if blocked:
            state = "PAUSE_RECENT_SELL_OFF_REVIEW"
        elif relative_weak:
            state = "WATCH_MARKET_RELATIVE_WEAKNESS"
        elif ret5 is None or ret10 is None:
            state = "PENDING_INCOMPLETE_OBSERVATION_WINDOW"
        else:
            state = "NO_THRESHOLD_TRIGGER_IN_OBSERVED_SNAPSHOTS"
        outputs.append(dict(
            code=code,name=row.get("name"),status=state,risk_blocked=blocked,
            relative_weakness_watch=relative_weak,
            observation_count=count,current_unadjusted_close=current,
            return_5observations_pct=round(ret5,2) if ret5 is not None else None,
            return_10observations_pct=round(ret10,2) if ret10 is not None else None,
            peak_to_current_10observations_pct=round(from_peak,2),
            relative_to_taiex_tr_pct=round(relative,2) if relative is not None else None,
            complete_20_60_session_history_verified=False))
    return dict(schema=SCHEMA,model="V8.10.8",asof_price_date=asof,
        estimate_vintage=vintage_label,issuer_count=len(outputs),
        formal_Aplus_added=0,trade_signals_issued=0,
        full_exchange_session_calendar_verified=False,
        unadjusted_prices_and_company_actions_unverified=True,
        benchmark_is_total_return_stock_is_price_only=True,
        historical_capture_pit_not_verified=True,
        observed_snapshots_are_not_necessarily_consecutive_sessions=True,
        risk_policy_is_provisional_unvalidated=True,
        study_thresholds=dict(return_5observations_pause_pct=-15,
                              return_10observations_pause_pct=-20,
                              peak_to_current_pause_pct=-20,
                              relative_weakness_price_minus_taiex_tr_pct=-5),
        source_sha256=dict(quality=hashlib.sha256(source).hexdigest(),
                           price_snapshots=price_receipts,benchmark_months=market_receipts),
        outputs=outputs)

def markdown(report):
    lines = ["# V8.10.8 近期大跌風險研究影子層", "",
      "行情日期：" + report["asof_price_date"] + "；模型形成：" + report["estimate_vintage"],
      "這不是實證勝率、正式A+、下單或賣出指令；20/60日完整交易曆及除權息尚未認證。",
      "下列5、10期均指資料庫內實際保存的觀測筆數，**不等於連續5、10個交易日**。",
      "使用個股未還原收盤價對照加權報酬指數含息，僅為粗略相對弱勢線索。",
      "", "|股票|5筆變化|10筆變化|近期高點到目前|相對指數|狀態|",
      "|---|---:|---:|---:|---:|---|"]
    def fmt(n):
        return "待補" if n is None else "%+.1f%%" % n
    for r in report["outputs"]:
        lines.append("|"+r["code"]+" "+str(r.get("name") or "")+"|"+
          fmt(r["return_5observations_pct"])+"|"+
          fmt(r["return_10observations_pct"])+"|"+
          fmt(r["peak_to_current_10observations_pct"])+"|"+
          fmt(r["relative_to_taiex_tr_pct"])+"|"+r["status"]+"|")
    lines += ["", "門檻為尚未校準的暫定研究政策。缺少交易日、公司行動或PIT原件不得當作風險已解除。",
      "只讀風險與原有估值；沒有任何正式品質關卡、EPS、PE、排名或部位被更新。", ""]
    return "\n".join(lines)

def publish(root):
    root = Path(root)
    result = build(root)
    out = root / "rankings"
    atomic_json(out / "latest_recent_drawdown_shadow.json", result)
    (out / "latest_recent_drawdown_shadow.md").write_text(markdown(result), encoding="utf-8")
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="tw-market-data")
    args = parser.parse_args()
    result = publish(args.data_root)
    print(json.dumps(dict(date=result["asof_price_date"],
        issuers=result["issuer_count"],
        paused=sum(x["risk_blocked"] for x in result["outputs"]),
        formal_Aplus_added=0,orders=0), ensure_ascii=False))

if __name__ == "__main__":
    main()
