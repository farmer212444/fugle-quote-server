"""Regression controls for the separate four-lane entry decision shadow."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.v8b8_buy_decision_shadow import assess,markdown,publish

DATE="2026-11-06"
VINTAGE="2026-11-09T06:36:16+08:00"

def fixture():
    def issuer(code,rank):
        return dict(code=code,name="測試"+code,prior_base_rank=rank,
            base_upside_pct=95.0 if code=="2317" else 58.1,
            sensitivity_eps20_pe20_upside_pct=24.7,
            base_2027_eps_scenario=10.0,
            base_2027_pe_assumption=20.0,
            base_target_price_scenario=200.0,
            original_current_numerics_checked=False,
            operating_evidence_gaps=[],capital_evidence_gaps=[],pe_evidence_gaps=[],
            model_13_gate_passed_count=0,model_13_gate_pending_count=13,
            model_13_gate_failed_count=0,
            high_confidence_buy_or_Aplus_certified=False,
            recommendation_blocked=False,
            governance_review=dict(blocks_recommendation=False),
            etf_warning_active=False)
    rows=[issuer("6741",1),issuer("2376",2)]
    quality=dict(schema="V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
                 asof_price_date=DATE,estimate_vintage=VINTAGE,
                 issuer_count=len(rows),formal_Aplus_added=0,base_upside_order=rows)
    readiness=dict(schema="EXPECTED_RETURN_READINESS_V1",
                   research_price_date=DATE,source_estimate_vintage=VINTAGE,
                   status="NOT_ESTIMABLE_WITH_CURRENT_EVIDENCE",
                   expected_net_return_top10=None,
                   calibrated_issuer_scenario_probabilities=None,
                   base_price_upside_ranking_is_expected_return=False)
    work=dict(schema="RESEARCH_EVIDENCE_WORK_QUEUE_V1",
              asof_price_date=DATE,estimate_vintage=VINTAGE,
              issuer_jobs=[dict(code="2317",name="鴻海",
                                passed_gate_count=0,unresolved_gate_count=13,
                                original_quarter_coverage=dict(archived=8,required=8,missing_quarters=[]),
                                research_upside_pct=95.0,formal_Aplus=False),
                           dict(code="2330",name="台積電",
                                passed_gate_count=0,unresolved_gate_count=13,
                                original_quarter_coverage=dict(archived=4,required=8,missing_quarters=["2026-Q2"]),
                                research_upside_pct=58.1,formal_Aplus=False)])
    policy=dict(schema="V810_RESEARCH_POLICY_NOT_A_TRADING_MANDATE",
                actual_holdings_assumed=False,
                benchmark_policy=dict(automatic_deployment=False),
                risk_policy=dict(max_stock_weight=.1,max_sector_weight=.25,
                                 max_common_risk_weight=.35,max_portfolio_bear_loss=.1,
                                 max_daily_participation=.05,max_exit_sessions=5))
    return quality,readiness,work,policy


class BuyShadowTests(unittest.TestCase):
    def test_risk_four_layers_require_independent_evidence(self):
        original=fixture()
        snapshot=copy.deepcopy(original)
        result=assess(*original)
        self.assertEqual(original,snapshot)
        self.assertEqual(result["issuer_count"],2)
        self.assertEqual([x["code"] for x in result["outputs"]],["6741","2376"])
        self.assertFalse(result["calibrated_expected_return_available"])
        self.assertEqual(result["buy_ready_count"],0)
        self.assertEqual(result["issuer_buy_orders_created"],0)
        self.assertEqual(result["formal_Aplus_added"],0)
        self.assertTrue(result["formal_13_gates_unchanged"])
        self.assertFalse(result["automatic_deployment"])
        self.assertTrue(result["insider_missing_is_not_zero_net_buy_sell"])
        for row in result["outputs"]:
            self.assertEqual(row["buy_decision"],"NOT_AUTHORIZED_UNVERIFIED")
            self.assertIsNone(row["calibrated_probabilities"])
            self.assertIsNone(row["expected_net_return"])
            self.assertIsNone(row["downside_loss_bound"])
            self.assertIsNone(row["position_size_ntd"])
            self.assertIn("PENDING",row["insider_buy_sell"])
            self.assertIn("PENDING",row["entry_timing"])
        self.assertEqual([x["code"] for x in result["focus_diagnostics"]],["2330","2317"])
        self.assertTrue(all(x["source_lane"]=="FOCUS_ONLY" for x in result["focus_diagnostics"]))
        self.assertIn("8/8",markdown(result))
        self.assertIn("原Top20估值順位",markdown(result))

    def test_positive_stress_is_not_positive_bear_case_or_buy(self):
        q,r,w,p=fixture()
        q["base_upside_order"][0]["base_upside_pct"]=146.33
        q["base_upside_order"][0]["sensitivity_eps20_pe20_upside_pct"]=57.65
        out=assess(q,r,w,p)["outputs"][0]
        self.assertTrue(out["valuation"]["stressed_scenario_above_reference"])
        self.assertTrue(out["valuation"]["stressed_scenario_is_not_bear_loss_probability"])
        self.assertIsNone(out["downside_loss_bound"])
        self.assertEqual(out["buy_decision"],"NOT_AUTHORIZED_UNVERIFIED")

    def test_governance_and_quality_fail_override_research_upside(self):
        q,r,w,p=fixture()
        q["base_upside_order"][0]["governance_review"]["blocks_recommendation"]=True
        q["base_upside_order"][1]["model_13_gate_failed_count"]=1
        q["base_upside_order"][1]["model_13_gate_pending_count"]=12
        rows=assess(q,r,w,p)["outputs"]
        self.assertEqual(rows[0]["action_review_state"],"PAUSE_GOVERNANCE_REVIEW")
        self.assertEqual(rows[1]["action_review_state"],"PAUSE_FORMAL_QUALITY_FAIL_REVIEW")
        self.assertTrue(all(x["buy_decision"]=="NOT_AUTHORIZED_UNVERIFIED" for x in rows))

    def test_stale_snapshots_rejected_instead_of_spliced(self):
        for modified in ("quality","readiness","work"):
            q,r,w,p=fixture()
            if modified=="quality":q["asof_price_date"]="2026-11-05"
            if modified=="readiness":r["source_estimate_vintage"]="2026-11-08T00:00:00+08:00"
            if modified=="work":w["asof_price_date"]="2026-11-05"
            with self.subTest(changed=modified),self.assertRaisesRegex(ValueError,"VINTAGE_MISMATCH"):
                assess(q,r,w,p)

    def test_no_formal_gate_count_forgery_or_duplicate_rows(self):
        q,r,w,p=fixture()
        q["base_upside_order"][0]["model_13_gate_pending_count"]=12
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_FORMAL"):
            assess(q,r,w,p)
        q,r,w,p=fixture()
        q["base_upside_order"][1]["code"]="6741"
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            assess(q,r,w,p)

    def test_calibrated_expected_return_cannot_be_declared_from_fake_data(self):
        q,r,w,p=fixture()
        r["expected_net_return_top10"]=[dict(code="6741",value=0.6)]
        with self.assertRaisesRegex(ValueError,"FALSE_CERTIFICATION"):
            assess(q,r,w,p)

    def test_risk_limits_are_assumptions_not_customer_positions(self):
        q,r,w,p=fixture()
        p["actual_holdings_assumed"]=True
        with self.assertRaisesRegex(ValueError,"ACTUAL_HOLDINGS_FALSE"):
            assess(q,r,w,p)
        q,r,w,p=fixture()
        p["risk_policy"]["max_stock_weight"]=float("nan")
        with self.assertRaisesRegex(ValueError,"RISK_LIMITS_INVALID"):
            assess(q,r,w,p)

    def test_publish_is_pure_of_existing_source_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            q,r,w,p=fixture()
            paths=dict(quality="rankings/v8a5_quality_decision_lane.json",
                       readiness="rankings/latest_expected_return_readiness.json",
                       work_queue="rankings/latest_research_work_queue.json",
                       config="config/institutional_research.json")
            before={}
            for k,doc in zip(paths,(q,r,w,p)):
                path=root/paths[k]
                path.parent.mkdir(parents=True,exist_ok=True)
                b=json.dumps(doc,ensure_ascii=False).encode()
                path.write_bytes(b);before[k]=b
            result=publish(root)
            self.assertEqual(result["buy_ready_count"],0)
            for k,path in paths.items():
                self.assertEqual((root/path).read_bytes(),before[k])
            archived=json.loads((root/"rankings/latest_buy_decision_shadow.json").read_text())
            self.assertEqual(set(archived["source_sha256"]),set(paths))
            self.assertIn("2317", (root/"rankings/latest_buy_decision_shadow.md").read_text())
            self.assertEqual(archived["formal_Aplus_added"],0)

    def test_drawdown_risk_precedes_upside_and_does_not_promote_a_plus(self):
        q,r,w,p=fixture()
        risk=dict(schema="V8108_RECENT_DRAWDOWN_RESEARCH_SHADOW_V1",
                  asof_price_date=DATE,estimate_vintage=VINTAGE,
                  issuer_count=2,formal_Aplus_added=0,trade_signals_issued=0,
                  outputs=[dict(code="6741",risk_blocked=True,
                                relative_weakness_watch=False,
                                status="PAUSE_RECENT_SELL_OFF_REVIEW"),
                           dict(code="2376",risk_blocked=False,
                                relative_weakness_watch=True,
                                status="WATCH_MARKET_RELATIVE_WEAKNESS")])
        report=assess(q,r,w,p,risk)
        self.assertEqual(report["outputs"][0]["action_review_state"],
                         "PAUSE_RECENT_DRAWDOWN_REVIEW")
        self.assertEqual(report["outputs"][1]["action_review_state"],
                         "WATCH_MARKET_RELATIVE_WEAKNESS")
        self.assertEqual(report["formal_Aplus_added"],0)
        self.assertEqual(report["buy_ready_count"],0)
        self.assertEqual(report["issuer_buy_orders_created"],0)
        self.assertTrue(report["provisional_drawdown_shadow_present"])
        self.assertIn("近期急跌",markdown(report))

    def test_historic_peak_trough_watch_is_not_a_pause_or_trade(self):
        q,r,w,p=fixture()
        risk=dict(schema="V8108_RECENT_DRAWDOWN_RESEARCH_SHADOW_V1",
                  asof_price_date=DATE,estimate_vintage=VINTAGE,
                  issuer_count=2,formal_Aplus_added=0,trade_signals_issued=0,
                  outputs=[dict(code="6741",risk_blocked=False,
                                relative_weakness_watch=False,
                                observed_deep_drawdown_watch=True,
                                status="WATCH_OBSERVED_DEEP_DRAWDOWN"),
                           dict(code="2376",risk_blocked=False,
                                relative_weakness_watch=False,
                                observed_deep_drawdown_watch=None,
                                status="PENDING_INCOMPLETE_OBSERVATION_WINDOW")])
        report=assess(q,r,w,p,risk)
        self.assertEqual(report["outputs"][0]["action_review_state"],
                         "WATCH_OBSERVED_DEEP_DRAWDOWN")
        self.assertEqual(report["buy_ready_count"],0)
        self.assertEqual(report["issuer_buy_orders_created"],0)
        self.assertEqual(report["formal_Aplus_added"],0)

    def test_drawdown_must_match_same_source_vintage_and_issuer_universe(self):
        q,r,w,p=fixture()
        risk=dict(schema="V8108_RECENT_DRAWDOWN_RESEARCH_SHADOW_V1",
                  asof_price_date=DATE,estimate_vintage="2026-11-08T18:00:00+08:00",
                  issuer_count=1,formal_Aplus_added=0,trade_signals_issued=0,
                  outputs=[dict(code="6741",risk_blocked=True,
                                status="PAUSE_RECENT_SELL_OFF_REVIEW")])
        with self.assertRaisesRegex(ValueError,"DRAWDOWN_SOURCE_VINTAGE"):
            assess(q,r,w,p,risk)
        risk["estimate_vintage"]=VINTAGE
        with self.assertRaisesRegex(ValueError,"DRAWDOWN_ISSUER_UNIVERSE"):
            assess(q,r,w,p,risk)
        risk["issuer_count"]=2
        risk["outputs"].append(dict(code="2376",risk_blocked=False,
                                    status="NO_THRESHOLD_TRIGGER"))
        risk["trade_signals_issued"]=1
        with self.assertRaisesRegex(ValueError,"DRAWDOWN_FALSE_TRADE"):
            assess(q,r,w,p,risk)

    def test_direct_cli_supports_help_from_nonproject_cwd(self):
        import scripts.v8b8_buy_decision_shadow as cli
        env=dict(os.environ);env.pop("PYTHONPATH",None)
        with tempfile.TemporaryDirectory() as cwd:
            p=subprocess.run([sys.executable,str(Path(cli.__file__).resolve()),"--help"],
                             cwd=cwd,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("--data-root",p.stdout)

if __name__=="__main__":
    unittest.main()
