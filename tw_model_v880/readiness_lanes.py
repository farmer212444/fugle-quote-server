"""Independent, evidence-preserving lanes for valuation, issuer quality and strategy.

This is a research presentation and triage model only.  It does not award any
gate PASS, issue certificates, calibrate scenario probabilities, or trade.
"""
import math
from .evidence import GATES, POLICY

STRATEGY_GATE = "out_of_sample_validation"
COMPANY_GATES = tuple(g for g in GATES if g != STRATEGY_GATE)
DECISIONS = frozenset(("PASS", "FAIL", "PENDING", "NOT_EVALUATED"))


def classify_issuer(row):
    ledger = row["gate_stage"]
    if set(ledger) != set(GATES):
        raise ValueError("READINESS_INCOMPLETE_13_GATE_LEDGER")
    decisions = {}
    for gate in GATES:
        item = ledger[gate]
        state = item["decision"]
        if state not in DECISIONS or item.get("formal_pass") is not (state == "PASS"):
            raise ValueError("READINESS_INVALID_FORMAL_GATE_DECISION")
        decisions[gate] = state

    upside = row.get("research_upside_pct")
    price_valid = type(upside) in (float, int) and math.isfinite(upside)
    if price_valid:
        if upside >= POLICY["Aplus_price_upside_pct"]:
            price_lane = "A_PLUS_PRICE_CANDIDATE_UNVERIFIED"
        elif upside >= POLICY["discovery_price_upside_pct"]:
            price_lane = "A_DISCOVERY_PRICE_CANDIDATE_UNVERIFIED"
        else:
            price_lane = "PRICE_HURDLE_NOT_MET"
    else:
        price_lane = "RESEARCH_PRICE_UNAVAILABLE"
    company = [decisions[g] for g in COMPANY_GATES]
    counts = {k: company.count(k) for k in DECISIONS}
    if counts["FAIL"]:
        quality_lane = "DOCUMENTED_QUALITY_FAIL"
    elif counts["NOT_EVALUATED"]:
        quality_lane = "QUALITY_INPUT_INCOMPLETE"
    elif counts["PENDING"]:
        quality_lane = "QUALITY_REVIEW_PENDING"
    else:
        quality_lane = "COMPANY_QUALITY_12_OF_12_FORMAL_PASS"
    oos = decisions[STRATEGY_GATE]
    strategy_lane = {
        "PASS": "STRATEGY_PIT_OOS_FORMAL_PASS",
        "FAIL": "STRATEGY_PIT_OOS_FORMAL_FAIL",
        "PENDING": "STRATEGY_PIT_OOS_PENDING",
        "NOT_EVALUATED": "STRATEGY_PIT_OOS_NOT_EVALUATED",
    }[oos]
    formal = row.get("formal_Aplus")
    if type(formal) is not bool:
        raise ValueError("READINESS_FORMAL_APLUS_FLAG_REQUIRED")
    eligible = (price_valid and upside >= POLICY["Aplus_price_upside_pct"]
                and all(d == "PASS" for d in decisions.values()))
    if formal and not eligible:
        raise ValueError("READINESS_FALSE_FORMAL_APLUS")
    # A positive research gap is not a backtested expected return.
    dual_20 = round(((1 + upside / 100) * 0.8 * 0.8 - 1) * 100, 2) if price_valid else None
    return dict(
        code=row["code"],market=row["market"],name=row.get("name"),
        valuation_period=row.get("financial_period"),
        reviewed_period=row.get("reviewed_financial_period"),
        research_upside_pct=upside if price_valid else None,
        price_lane=price_lane,
        company_quality_lane=quality_lane,
        company_gates_passed=counts["PASS"],
        company_gates_failed=counts["FAIL"],
        company_gates_pending=counts["PENDING"],
        company_gates_not_evaluated=counts["NOT_EVALUATED"],
        company_gates_total=len(COMPANY_GATES),
        strategy_validation_lane=strategy_lane,
        formal_Aplus=formal,
        dual_20pct_eps_pe_stress_upside_pct=dual_20,
        dual_20pct_stress_is_mechanical_not_probability_calibrated=True,
        no_trade_signal=True,
        # Gate statuses are authoritative from the certification engine;
        # this module cannot change or infer them.
        gate_decisions_unchanged=True,
        evidence_provenance_is_not_formal_review=True,
    )


def summarize_lanes(lanes):
    counts = {}
    for lane in lanes:
        for field in ("price_lane", "company_quality_lane", "strategy_validation_lane"):
            key = lane[field]
            counts[key] = counts.get(key, 0) + 1
    return dict(
        total_diagnosed_issuers=len(lanes),
        price_research_candidates=sum(x["price_lane"] == "A_PLUS_PRICE_CANDIDATE_UNVERIFIED"
                                      for x in lanes),
        company_quality_12_gate_passed=sum(
            x["company_quality_lane"] == "COMPANY_QUALITY_12_OF_12_FORMAL_PASS" for x in lanes),
        strategy_pit_oos_formal_passed=sum(
            x["strategy_validation_lane"] == "STRATEGY_PIT_OOS_FORMAL_PASS" for x in lanes),
        formal_aplus_count=sum(x["formal_Aplus"] for x in lanes),
        lane_counts=counts,
        no_new_certificates=True,
        no_fabricated_historical_returns=True,
    )


def render_readiness_report(report):
    stats = report["counts"]
    rows = report["issuers"]
    lines = [
        "# 台股研究與正式A+分離之決策分層",
        "",
        f"模型：{report['model']}；估值：{report['estimate_vintage']}；收盤：{report['asof_price_date']}。",
        "",
        "這是依原始13項證據帳本產生的研究決策分層，不是變更認證門檻。",
        "A+價格研究候選不是正式A+，雙降20%是機械壓測而非期望報酬。",
        "",
        f"已診斷 {stats['total_diagnosed_issuers']} 家；A+價格候選 "
        f"{stats['price_research_candidates']} 家；公司12項全正式通過 "
        f"{stats['company_quality_12_gate_passed']} 家；策略樣本外正式通過 "
        f"{stats['strategy_pit_oos_formal_passed']} 家；正式A+ "
        f"{stats['formal_aplus_count']} 家。",
        "",
        "## 分層說明",
        "",
        "|層級|意義|",
        "|---|---|",
        "|價格研究|以模型預估價差分類，尚無校準機率|",
        "|公司品質12關|只採正式證據PASS／FAIL／PENDING／NOT_EVALUATED，不由名氣推定|",
        "|策略第13關|PIT、交易成本及Walk-Forward另列，不與公司品質混淆|",
        "|正式A+|沿用原引擎13項全部PASS且Base價差≥30%，本報表不能核發|",
        "",
        "## 台積電驗收樣本",
        "",
    ]
    tsmc = next((r for r in rows if r["code"] == "2330"), None)
    if tsmc:
        lines += ["|項目|判定|", "|---|---|",
                  f"|價差研究|{tsmc['research_upside_pct']:+.1f}%：{tsmc['price_lane']}|"
                  if tsmc["research_upside_pct"] is not None else "|價差研究|無可用研究估值|",
                  f"|公司品質|正式PASS {tsmc['company_gates_passed']}/12；"
                  f"待核 {tsmc['company_gates_pending']}；"
                  f"未進入判定 {tsmc['company_gates_not_evaluated']}；"
                  f"明確FAIL {tsmc['company_gates_failed']}|",
                  f"|策略回測|{tsmc['strategy_validation_lane']}|",
                  f"|EPS與PE各降20%情境|"
                  + (f"{tsmc['dual_20pct_eps_pe_stress_upside_pct']:+.2f}%（機械壓測）"
                     if tsmc["dual_20pct_eps_pe_stress_upside_pct"] is not None else "無可用數字") + "|",
                  f"|正式A+|{'通過' if tsmc['formal_Aplus'] else '未完成認證'}|",
                  ""]
    else:
        lines += ["本次證據帳本未涵蓋2330，不能臆測其狀態。", ""]
    candidates = [x for x in rows if x["price_lane"] ==
                  "A_PLUS_PRICE_CANDIDATE_UNVERIFIED"]
    candidates.sort(key=lambda x: (-x["research_upside_pct"], x["code"]))
    lines += ["## A+價格研究候選（前20，未正式認證）", "",
              "|公司|模型價差|雙降20%情境|公司品質|策略回測|",
              "|---|---:|---:|---|---|"]
    for x in candidates[:20]:
        lines.append(f"|{x['code']} {x['name'] or ''}|{x['research_upside_pct']:+.1f}%|"
                     f"{x['dual_20pct_eps_pe_stress_upside_pct']:+.2f}%|"
                     f"{x['company_quality_lane']}|{x['strategy_validation_lane']}|")
    lines += ["", "未經公司別原件核閱或策略樣本外校準，不得由本表直接發出重押、期望報酬或交易訊號。", ""]
    return "\n".join(lines)
