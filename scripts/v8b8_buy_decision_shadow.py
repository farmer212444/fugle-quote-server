#!/usr/bin/env python3
"""V8.10.8 independent entry decision readiness; no new formal A+ gates.

Values are research scenarios, not calibrated return expectations. A current
stock quote, a single momentum observation, or a source archive is insufficient
for a BUY, SELL, HOLD, or portfolio sizing instruction.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0,str(PROJECT))

from scripts.run_research_pipeline import atomic_json

SCHEMA="V8108_BUY_DECISION_SHADOW_V1"
FOCUS_CODES=("2330","2317")
NO_RETURN="PENDING_VERIFIED_BEAR_LOSS_AND_CALIBRATED_NET_RETURN"
NO_REVISION="PENDING_DATED_EPS_REVISIONS_AND_FILING_RECONCILIATION"
NO_ENTRY="PENDING_VERIFIED_PIT_MULTISESSION_ENTRY_SIGNAL"
NO_INSIDER="PENDING_VERIFIED_BUY_SELL_HOLDER_IDENTITY_AND_PIT"
NO_HOLDINGS="PENDING_ACTUAL_HOLDINGS_CORRELATIONS_AND_EXECUTION_CAPACITY"
NO_SALE="NOT_EVALUABLE_WITHOUT_VERIFIED_ACTUAL_POSITIONS"


def require(ok,reason):
    if not ok:raise ValueError("BUY_DECISION_"+reason)


def finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def _unique(rows,code_key="code"):
    require(isinstance(rows,list),"ISSUER_ROWS_MISSING")
    found={}
    for row in rows:
        require(isinstance(row,dict) and isinstance(row.get(code_key),str),"ISSUER_ID_INVALID")
        code=row[code_key]
        require(code not in found,"DUPLICATE_ISSUER_"+code)
        found[code]=row
    return found


def _quality(row):
    passed=row.get("model_13_gate_passed_count")
    pending=row.get("model_13_gate_pending_count")
    failed=row.get("model_13_gate_failed_count")
    require(all(type(v) is int and 0<=v<=13 for v in (passed,pending,failed))
            and passed+pending+failed==13,"INCOMPLETE_FORMAL_THIRTEEN_GATE_RECORD")
    require(row.get("high_confidence_buy_or_Aplus_certified") is False,
            "QUALITY_SOURCE_CLAIMS_AUTO_BUY")
    return dict(passed=passed,pending=pending,failed=failed,
                formal_quality_all_pass=passed==13,
                original_numerics_verified=row.get("original_current_numerics_checked") is True,
                red_flags=(list(row.get("operating_evidence_gaps") or [])
                           +list(row.get("pe_evidence_gaps") or [])
                           +list(row.get("capital_evidence_gaps") or [])),
                governance_blocked=row.get("recommendation_blocked") is True
                    or (row.get("governance_review") or {}).get("blocks_recommendation") is True,
                etf_convergence_watch=row.get("etf_warning_active") is True)


def _valuation(row):
    base=row.get("base_upside_pct")
    stressed=row.get("sensitivity_eps20_pe20_upside_pct")
    eps=row.get("base_2027_eps_scenario")
    pe=row.get("base_2027_pe_assumption")
    target=row.get("base_target_price_scenario")
    require(base is None or finite(base),"INVALID_BASE_UPSIDE")
    require(stressed is None or finite(stressed),"INVALID_STRESS_UPSIDE")
    require(eps is None or (finite(eps) and eps>0),"INVALID_EPS")
    require(pe is None or (finite(pe) and pe>0),"INVALID_PE")
    require(target is None or (finite(target) and target>0),"INVALID_BASE_TARGET")
    return dict(base_upside_pct=base,double20_stress_upside_pct=stressed,
                base_2027_eps_scenario=eps,base_2027_pe_assumption=pe,
                base_target_price_scenario=target,
                stressed_scenario_above_reference=(stressed>=0 if stressed is not None else None),
                stressed_scenario_is_not_bear_loss_probability=True,
                valuation_confidence=("PENDING_ORIGINAL_EPS_PE_AND_PEER_REVIEW"
                    if not row.get("original_current_numerics_checked") or
                    row.get("pe_evidence_gaps") or row.get("capital_evidence_gaps")
                    else "NUMERICS_LOCATED_BUT_FORECAST_VALIDATION_PENDING"))


def assess(quality_report,readiness,work_queue,config,drawdown=None):
    require(quality_report.get("schema")=="V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
            "QUALITY_INPUT_SCHEMA_MISMATCH")
    require(work_queue.get("schema")=="RESEARCH_EVIDENCE_WORK_QUEUE_V1",
            "WORK_QUEUE_SCHEMA_MISMATCH")
    require(config.get("schema")=="V810_RESEARCH_POLICY_NOT_A_TRADING_MANDATE",
            "RISK_POLICY_SCHEMA_MISMATCH")
    require(config.get("actual_holdings_assumed") is False,"ACTUAL_HOLDINGS_FALSE_ATTESTATION")
    require(config.get("benchmark_policy",{}).get("automatic_deployment") is False,
            "AUTOMATIC_DEPLOYMENT_NOT_PERMITTED")
    require(readiness.get("schema")=="EXPECTED_RETURN_READINESS_V1",
            "RETURN_INPUT_SCHEMA_MISMATCH")
    date=quality_report.get("asof_price_date")
    vintage=quality_report.get("estimate_vintage")
    require(isinstance(date,str) and isinstance(vintage,str),"SOURCE_VINTAGE_MISSING")
    dt.date.fromisoformat(date)
    dt.datetime.fromisoformat(vintage.replace("Z","+00:00"))
    require(work_queue.get("asof_price_date")==date
            and work_queue.get("estimate_vintage")==vintage,
            "WORK_QUEUE_VINTAGE_MISMATCH")
    require(readiness.get("research_price_date")==date
            and readiness.get("source_estimate_vintage")==vintage,
            "RETURN_VINTAGE_MISMATCH")
    require(quality_report.get("formal_Aplus_added")==0,
            "FORMAL_A_PLUS_COUNTER_CONFLICT")
    require(readiness.get("status")=="NOT_ESTIMABLE_WITH_CURRENT_EVIDENCE"
            and readiness.get("expected_net_return_top10") is None
            and readiness.get("calibrated_issuer_scenario_probabilities") is None,
            "EXPECTED_RETURN_FALSE_CERTIFICATION")
    require(readiness.get("base_price_upside_ranking_is_expected_return") is False,
            "BASE_RESEARCH_MISCLASSIFIED_AS_EXPECTED_RETURN")
    policy=config.get("risk_policy")
    require(isinstance(policy,dict),"MISSING_RISK_POLICY")
    required_limits=("max_stock_weight","max_sector_weight","max_common_risk_weight",
                     "max_portfolio_bear_loss","max_daily_participation",
                     "max_exit_sessions")
    require(all(finite(policy.get(k)) and policy[k]>0 for k in required_limits),
            "RISK_LIMITS_INVALID")
    quality_rows=quality_report.get("base_upside_order")
    quality_index=_unique(quality_rows)
    work_index=_unique(work_queue.get("issuer_jobs"))
    require(quality_report.get("issuer_count")==len(quality_index),
            "QUALITY_ISSUER_COUNT_MISMATCH")
    risk_index = {}
    if drawdown is not None:
        require(drawdown.get("schema")=="V8108_RECENT_DRAWDOWN_RESEARCH_SHADOW_V1"
                and drawdown.get("asof_price_date")==date
                and drawdown.get("estimate_vintage")==vintage,
                "DRAWDOWN_SOURCE_VINTAGE_OR_SCHEMA_MISMATCH")
        require(drawdown.get("formal_Aplus_added")==0
                and drawdown.get("trade_signals_issued")==0,
                "DRAWDOWN_FALSE_TRADE_OR_CERTIFICATION")
        risk_index = _unique(drawdown.get("outputs"))
        require(len(risk_index)==drawdown.get("issuer_count")
                and set(risk_index)==set(quality_index),
                "DRAWDOWN_ISSUER_UNIVERSE_MISMATCH")
    outputs=[]
    for row in quality_rows:
        code=row["code"]
        quality=_quality(row)
        valuation=_valuation(row)
        price_risk = risk_index.get(code, dict(
            status="PENDING_DRAWDOWN_SOURCE_UNAVAILABLE",risk_blocked=False,
            relative_weakness_watch=False))
        require(type(price_risk.get("risk_blocked")) is bool
                and type(price_risk.get("relative_weakness_watch",False)) is bool
                and type(price_risk.get("observed_deep_drawdown_watch")) in (bool,type(None)),
                "DRAWDOWN_INVALID_DECISION_FLAG")
        if quality["governance_blocked"]:
            state="PAUSE_GOVERNANCE_REVIEW"
        elif quality["failed"]:
            state="PAUSE_FORMAL_QUALITY_FAIL_REVIEW"
        elif price_risk["risk_blocked"]:
            state="PAUSE_RECENT_DRAWDOWN_REVIEW"
        elif price_risk.get("observed_deep_drawdown_watch") is True:
            state="WATCH_OBSERVED_DEEP_DRAWDOWN"
        elif price_risk["relative_weakness_watch"]:
            state="WATCH_MARKET_RELATIVE_WEAKNESS"
        elif quality["red_flags"] or quality["etf_convergence_watch"]:
            state="REVIEW_OPERATING_VALUATION_OR_CAPITAL_RISKS"
        else:
            state="WAIT_FOR_VERIFIED_ENTRY_AND_RISK_RETURN"
        outputs.append(dict(code=code,name=row.get("name"),source_lane="TOP20_SHADOW",
            source_base_rank=row.get("prior_base_rank"),
            valuation=valuation,quality=quality,price_risk=price_risk,
            earnings_revision=NO_REVISION,insider_buy_sell=NO_INSIDER,
            entry_timing=NO_ENTRY,asymmetric_risk_reward=NO_RETURN,
            actual_portfolio_capacity=NO_HOLDINGS,
            action_review_state=state,
            buy_decision="NOT_AUTHORIZED_UNVERIFIED",
            existing_position_hold_sell=NO_SALE,
            calibrated_probabilities=None,expected_net_return=None,
            downside_loss_bound=None,position_size_ntd=None,
            real_time_order_placed=False,formal_Aplus_created=False))
    shadow_codes={x["code"] for x in outputs}
    focus=[]
    for code in FOCUS_CODES:
        row=work_index.get(code)
        if row is None:
            focus.append(dict(code=code,status="NO_CURRENT_WORK_QUEUE_DIAGNOSTIC",
                              buy_decision="NOT_AUTHORIZED_UNVERIFIED"))
            continue
        passed=row.get("passed_gate_count")
        unresolved=row.get("unresolved_gate_count")
        require(type(passed) is int and type(unresolved) is int and passed>=0
                and unresolved>=0 and passed+unresolved==13,
                "FOCUS_GATE_COUNT_INVALID_"+code)
        require(row.get("formal_Aplus") is False,"FOCUS_UNEXPECTED_CERTIFICATE")
        focus.append(dict(code=code,name=row.get("name"),
            status="WORK_QUEUE_RESEARCH_FOCUS_NOT_A_TRADE",
            source_lane="FOCUS_ONLY" if code not in shadow_codes else "TOP20_AND_FOCUS",
            original_quarter_coverage=row.get("original_quarter_coverage"),
            research_upside_pct=row.get("research_upside_pct"),
            company_and_strategy_formal_pass_count=passed,
            unresolved_gate_count=unresolved,
            buy_decision="NOT_AUTHORIZED_UNVERIFIED",
            risk_reward_status=NO_RETURN,
            insider_buy_sell=NO_INSIDER,actual_portfolio_capacity=NO_HOLDINGS,
            position_size_ntd=None,formal_Aplus_created=False))
    return dict(schema=SCHEMA,model="V8.10.8",asof_price_date=date,
        estimate_vintage=vintage,issuer_count=len(outputs),
        source_top20_order_preserved=True,formal_13_gates_unchanged=True,
        provisional_drawdown_shadow_present=drawdown is not None,
        drawdown_research_does_not_create_fourteenth_formal_gate=True,
        formal_Aplus_added=0,issuer_buy_orders_created=0,
        insider_missing_is_not_zero_net_buy_sell=True,
        historical_PIT_and_probability_calibration_still_missing=True,
        actual_holdings_verified=False,
        cost_model_is_assumption_not_broker_fill=True,
        reference_risk_policy_only=dict((k,policy[k]) for k in required_limits),
        calibrated_expected_return_available=False,
        buy_ready_count=0,
        outputs=outputs,focus_diagnostics=focus,
        missing_data_requirements=dict(
           verified_earnings_revisions="PENDING_DATED_PRIOR_AND_CURRENT_EPS_FORECAST_VINTAGES",
           risk_reward="PENDING_INDEPENDENT_DOWNSIDE_AND_NET_RETURN_CALIBRATION",
           entry="PENDING_MULTISESSION_PIT_STRENGTH_AND_EXECUTION_DATA",
           insider="PENDING_OFFICIAL_BUY_SELL_HOLDER_IDENTITY_PIT",
           portfolio="PENDING_USER_VERIFIED_POSITIONS_AND_COST_BASIS",
           backtest="PENDING_NONLEAKING_WALK_FORWARD_AND_TRANSACTION_COSTS"),
        no_trade_instruction=True,automatic_deployment=False)


def markdown(report):
    lines=["# V8.10.8 買進決策四層查核（研究版，不是買賣建議）","",
      "估值版本："+report["estimate_vintage"]+"；股價日："+report["asof_price_date"],
      "本報告獨立於13項正式A+認證，不改估值、不校準假機率、不建立交易。",
      "目前無可信的機率加權期望報酬及完整買進條件；所有個股均未核發買進指令。","",
      "## 四層狀態",
      "1. 企業品質：既有13關僅讀取，PENDING不視為PASS。",
      "2. 估值與風險報酬：顯示原Base及雙降20%結果，但雙降不是經驗性下跌分布。",
      "3. 交易時機：需逐股歷史PIT動能、有效突破、交易價差與完整消息時點。",
      "4. 部位：既有上限僅為研究假設，無實際持股與成交紀錄時不計算買進張數。","",
      "## 雙軌重點股票","",
      "|公司|研究價差|正式已通過|原件封存|買進判定|",
      "|---|---:|---:|---|---|"]
    for row in report["focus_diagnostics"]:
        if row.get("status")!="WORK_QUEUE_RESEARCH_FOCUS_NOT_A_TRADE":
            lines.append("|"+row["code"]+"|待核|待核|待核|未授權|")
            continue
        c=row["original_quarter_coverage"]
        archived=(str(c["archived"])+"/"+str(c["required"]) if c is not None else "未知")
        val=row["research_upside_pct"]
        formatted=("%+.1f%%"%val if finite(val) else "未核")
        lines.append("|"+row["code"]+" "+str(row.get("name") or "")+"|"+formatted+
                     "|"+str(row["company_and_strategy_formal_pass_count"])+"/13|"+
                     archived+"|資料未完成，不產生買進指令|")
    lines+=["","## 原Top20估值順位（非可買順位）","",
      "|原排行|股票|Base價差|EPS與PE雙降20%|公司品質與治理|買進準備|",
      "|---:|---|---:|---:|---|---|"]
    for row in report["outputs"]:
        v=row["valuation"];q=row["quality"]
        base=("%+.1f%%"%v["base_upside_pct"] if v["base_upside_pct"] is not None else "待核")
        stress=("%+.1f%%"%v["double20_stress_upside_pct"]
                if v["double20_stress_upside_pct"] is not None else "待核")
        note=("重大治理事件" if q["governance_blocked"] else
              "正式FAIL待核" if q["failed"] else
              "營運／估值／股本待核" if q["red_flags"] else "正式證據待核")
        lines.append("|"+str(row["source_base_rank"])+"|"+row["code"]+" "+
                     str(row.get("name") or "")+"|"+base+"|"+stress+
                     "|"+note+"|不得發出買進指令|")
    lines+=["","## 近期急跌與相對弱勢研究（不構成買賣訊號）","",
      "|股票|近期風險狀態|決策分流|","|---|---|---|"]
    for item in report["outputs"]:
        lines.append("|"+item["code"]+" "+str(item.get("name") or "")+"|"+
                     item["price_risk"]["status"]+"|"+item["action_review_state"]+"|")
    lines+=["","未調整除權息、完整交易日歷及事前PIT未認證；缺件不可視為風險為零。",
            "","## 缺少的決策證據",""]
    for field,status in report["missing_data_requirements"].items():
        lines.append("- "+field+"："+status)
    lines+=["",
      "買進、持有、減碼、賣出四類操作在未取得實際部位和獨立校準資料前均不得自動觸發。",
      "任何正面Base價差或雙降20%情境都不是保證報酬或已驗證風險報酬比。",""]
    return "\n".join(lines)


def publish(data_root):
    root=Path(data_root)
    targets=dict(
        quality=root/"rankings/v8a5_quality_decision_lane.json",
        readiness=root/"rankings/latest_expected_return_readiness.json",
        work_queue=root/"rankings/latest_research_work_queue.json",
        config=root/"config/institutional_research.json")
    originals={k:p.read_bytes() for k,p in targets.items()}
    docs={k:json.loads(v) for k,v in originals.items()}
    drawdown_path=root/"rankings/latest_recent_drawdown_shadow.json"
    risk_bytes=drawdown_path.read_bytes() if drawdown_path.exists() else None
    drawdown=json.loads(risk_bytes) if risk_bytes is not None else None
    if drawdown is not None:
        require((drawdown.get("source_sha256") or {}).get("quality") ==
                hashlib.sha256(originals["quality"]).hexdigest(),
                "DRAWDOWN_QUALITY_BYTES_HASH_MISMATCH")
    report=assess(docs["quality"],docs["readiness"],docs["work_queue"],docs["config"],drawdown)
    report["source_sha256"]={k:hashlib.sha256(b).hexdigest() for k,b in originals.items()}
    if risk_bytes is not None:
        report["source_sha256"]["drawdown"]=hashlib.sha256(risk_bytes).hexdigest()
    path=root/"rankings"
    atomic_json(path/"latest_buy_decision_shadow.json",report)
    content=markdown(report)
    dest=path/"latest_buy_decision_shadow.md"
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=dest.name+".",dir=dest.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:out.write(content)
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",default="tw-market-data")
    args=parser.parse_args()
    report=publish(args.data_root)
    print(json.dumps(dict(issuer_count=report["issuer_count"],
                          focus=[x["code"] for x in report["focus_diagnostics"]],
                          buy_ready_count=report["buy_ready_count"],
                          formal_Aplus_added=0,orders_created=0),ensure_ascii=False))

if __name__=="__main__":
    main()
