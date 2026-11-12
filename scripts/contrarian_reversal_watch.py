#!/usr/bin/env python3
"""Contrarian valuation WATCH research: scenario dispersion is not calibrated return."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_9802 = "tw-market-data/rankings/latest_footwear_review.json"
SOURCE_6206 = "tw-market-data/rankings/v888_6206_independent_valuation.json"
OUTPUT = "tw-market-data/rankings/latest_contrarian_reversal_watch"


def finite_positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def valid_date(value):
    return dt.date.fromisoformat(value)


def upside(price, current):
    if not finite_positive(price) or not finite_positive(current):
        raise ValueError("CONTRARIAN_BAD_PRICE")
    return round(100 * (price / current - 1), 2)


def scenario_row(code, name, price, price_date, cases, *, asof, origin, overhang=None, source=None):
    if not (len(str(code)) == 4 and str(code).isdigit()):
        raise ValueError("CONTRARIAN_ISSUER_INVALID")
    asof_date, recorded_date = valid_date(asof), valid_date(price_date)
    if recorded_date > asof_date:
        raise ValueError("CONTRARIAN_FUTURE_PRICE")
    if not finite_positive(price):
        raise ValueError("CONTRARIAN_BAD_PRICE")
    prices = {}
    for key in ("bear", "base", "bull"):
        case = cases[key]
        p = case.get("target_price")
        if not finite_positive(p):
            raise ValueError("CONTRARIAN_MISSING_SCENARIO")
        prices[key] = round(p, 4)
    if not prices["bear"] <= prices["base"] <= prices["bull"]:
        raise ValueError("CONTRARIAN_SCENARIO_ORDER")
    gaps = {key: upside(p, price) for key, p in prices.items()}
    if gaps["base"] >= 20 and gaps["bear"] >= -30:
        lane = "BASE_DISCOUNT_WITH_LIMITED_SCENARIO_DOWNSIDE"
    elif gaps["bull"] >= 35 and -20 <= gaps["base"] < 20:
        lane = "UNCONFIRMED_RECOVERY_OPTION"
    else:
        lane = "REQUIRES_REVALUATION"
    # This is a priority queue, not an expected-return rank or statistical score.
    pe = cases["base"].get("pe")
    if not finite_positive(pe):
        pe = (cases["base"].get("input_assumptions") or {}).get("pe")
    implied_eps = round(price / pe, 3) if finite_positive(pe) else None
    if overhang is not None and valid_date(overhang["published_on"]) > asof_date:
        raise ValueError("CONTRARIAN_FUTURE_OVERHANG")
    return {
        "code": str(code), "name": name, "reference_close": price, "price_date": price_date,
        "source_report": origin, "source_kind": source, "research_lane": lane,
        "scenario_prices": prices, "scenario_price_changes_pct": gaps,
        "base_eps": round(cases["base"]["eps"], 3) if finite_positive(cases["base"].get("eps")) else None,
        "base_pe": pe, "price_divided_by_base_pe_eps_proxy": implied_eps,
        "proxy_is_not_market_consensus": True,
        "overhang": overhang, "overhang_is_not_historical_pit_evidence": overhang is not None,
        "market_consensus_eps": None, "earnings_expectation_gap_confirmed": False,
        "scenario_probabilities": None, "expected_return_pct": None,
        "formal_Aplus": False, "recommendation": None, "trade_instruction": None,
        "missing_for_action": ["DATED_INDEPENDENT_MARKET_EXPECTATION",
                              "CATALYST_COST_AND_MARGIN_BRIDGE",
                              "DILUTION_AND_LIQUIDITY_VERIFICATION",
                              "PIT_OUT_OF_SAMPLE_VALIDATION"],
    }


def build_report(footwear, flytech, *, asof, overhang=None):
    valid_date(asof)
    if footwear.get("schema") != "V8106_FOOTWEAR_REVIEW_V1":
        raise ValueError("CONTRARIAN_FOOTWEAR_SCHEMA")
    if "scenarios" not in flytech or flytech.get("issuer") != "6206":
        raise ValueError("CONTRARIAN_FLYTECH_SCHEMA")
    fw_date = footwear["asof_price_date"]
    fly_date = flytech["official_reference_price"]["date"]
    if fw_date != fly_date:
        raise ValueError("CONTRARIAN_MIXED_PRICE_DATES")
    if valid_date(fw_date) > valid_date(asof):
        raise ValueError("CONTRARIAN_FUTURE_REPORT")
    # Research was assembled after the official daily close; never backfill it.
    vintage = dt.datetime.fromisoformat(footwear["estimate_vintage"])
    if vintage.tzinfo is None or vintage.date() > valid_date(asof):
        raise ValueError("CONTRARIAN_FUTURE_RESEARCH_VINTAGE")
    overhang = overhang or {}
    if not isinstance(overhang, dict):
        raise ValueError("CONTRARIAN_OVERHANG_SCHEMA")
    rows = []
    seen = set()
    for comp in footwear["companies"]:
        code = str(comp["code"])
        if code in seen:
            raise ValueError("CONTRARIAN_DUPLICATE_ISSUER")
        seen.add(code)
        if comp["price_date"] != fw_date:
            raise ValueError("CONTRARIAN_MIXED_PRICE_DATES")
        cases = {k.lower(): v for k, v in comp["research_cases"].items()}
        rows.append(scenario_row(code, comp["name"], comp["reference_close"], comp["price_date"],
                                 cases, asof=asof, origin=SOURCE_9802,
                                 source=comp.get("production_earnings_source_kind"),
                                 overhang=overhang.get(code)))
    current = flytech["official_reference_price"]
    cases = {k: v for k, v in flytech["scenarios"].items()}
    if "6206" in seen:
        raise ValueError("CONTRARIAN_DUPLICATE_ISSUER")
    rows.append(scenario_row("6206", "飛捷", current["close"], current["date"], cases,
                             asof=asof, origin=SOURCE_6206,
                             source="2026H1_ISSUER_IR_REVIEWED", overhang=overhang.get("6206")))
    # Do not silently ignore a custom overhang for an issuer absent from source reports.
    if set(overhang) - {r["code"] for r in rows}:
        raise ValueError("CONTRARIAN_UNMATCHED_OVERHANG")
    order = {"BASE_DISCOUNT_WITH_LIMITED_SCENARIO_DOWNSIDE": 0,
             "UNCONFIRMED_RECOVERY_OPTION": 1, "REQUIRES_REVALUATION": 2}
    rows.sort(key=lambda r: (order[r["research_lane"]], -r["scenario_price_changes_pct"]["base"],
                             -r["scenario_price_changes_pct"]["bull"], r["code"]))
    return {
        "schema": "CONTRARIAN_REVERSAL_WATCH_V1", "asof": asof,
        "price_date": fw_date, "research_target": footwear["target_date"],
        "observed_issuers": len(rows), "complete_market_scan": False,
        "input_universe": "5 FOOTWEAR RESEARCH CASES + 6206 INDEPENDENT CASE",
        "price_snapshot_stale": (valid_date(asof) - valid_date(fw_date)).days > 1,
        "rank_is_research_queue_not_top10": True,
        "ranking_method": "BASE_20PCT_UP_AND_BEAR_NO_WORSE_MINUS30PCT_FIRST; THEN_BULL_OPTION; SORT_BASE_GAP",
        "market_expectations_verification": "MISSING_INDEPENDENT_PRIOR_VINTAGE",
        "expected_returns_calibrated": False, "formal_quality_gates_modified": False,
        "trade_signals_issued": 0, "model_forecasts_overwritten": False,
        "source_reports": [SOURCE_9802, SOURCE_6206],
        "rows": rows,
    }


def markdown(report):
    out = [
        "# B 軌｜逆向低估與反轉研究候選（非正式買進榜）",
        "",
        f"報告日期：{report['asof']}；共同參考收盤：{report['price_date']}；評估終點：{report['research_target']}。",
        "**範圍僅有 5 家製鞋股與 6206，並非全市場 TOP10。** "
        "情境價不含股利、交易成本；權重未經驗證，不提供機率加權期望報酬。",
        "市場共識與獲利預期差尚未查證；基準 PE 反推 EPS 僅是價格敏感度，不是市場預測。",
        "",
        "|觀察序|股票|參考價|Bear|Base|Bull|Base價差|Bear價差|類型|",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, row in enumerate(report["rows"], 1):
        p, g = row["scenario_prices"], row["scenario_price_changes_pct"]
        out.append(f"|{i}|{row['code']} {row['name']}|{row['reference_close']:.2f}|"
                   f"{p['bear']:.2f}|{p['base']:.2f}|{p['bull']:.2f}|"
                   f"{g['base']:+.1f}%|{g['bear']:+.1f}%|{row['research_lane']}|")
    out.extend(["", "待查：對應日期的市場預期、成本/毛利變化、稀釋與流動性、樣本外檢驗。",
                "所有個股維持 RESEARCH_ONLY；原正式 A+、EPS、PE、交易政策均不變。"])
    if report["price_snapshot_stale"]:
        out.append("**注意：共同報價距報告日超過 1 天，不能拿來當即時進場價。**")
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat())
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out-prefix")
    args = parser.parse_args()
    root = Path(args.root)
    footwear = json.loads((root / SOURCE_9802).read_text(encoding="utf-8"))
    flytech = json.loads((root / SOURCE_6206).read_text(encoding="utf-8"))
    config = root / "tw-market-data/config/contrarian_overhang_v1.json"
    overhang = json.loads(config.read_text(encoding="utf-8")) if config.is_file() else {}
    report = build_report(footwear, flytech, asof=args.asof, overhang=overhang)
    prefix = Path(args.out_prefix) if args.out_prefix else root / OUTPUT
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prefix.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(f"Contrarian watch: {len(report['rows'])} candidates; {prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
