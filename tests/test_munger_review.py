import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.munger import GATES, build, render
from scripts.munger_quality_review import publish


ASOF="2026-10-24T17:28:16+08:00"
PRICE="2026-10-22"
MODEL="V8.10.8"


def fixture():
    def issuer(code, upside, *, blocked=False, stress=-9.8):
        stages={g:dict(decision="PENDING", formal_pass=False,
                       required_evidence="original source and issuer-specific review")
                for g in GATES}
        diag=dict(code=code, name="issuer "+code, market="TWSE",
                  research_upside_pct=upside, model_evaluated=True,
                  formally_passed_gates=[], formally_failed_gates=[],
                  still_pending_gates=list(GATES), gate_stage=stages,
                  formal_Aplus=False)
        detail=dict(code=code, market="TWSE", name="issuer "+code,
                    formal_Aplus=False, base_upside_pct=upside,
                    valuation_diagnostics=dict(
                        eps_pe_each_minus20_upside_pct=stress,
                        pe_is_matched_peer_certified=False,
                        forward_annual_profit_bridge_verified=False),
                    governance_review=dict(blocks_recommendation=blocked),
                    recommendation_blocked=blocked,
                    liquidity=dict(spread_and_exit_verified=False),
                    risk_profile=dict(status="REVIEWED_COMMON_RISK_AND_STRESS_PROFILE_MISSING"))
        return diag,detail

    a,detail_a=issuer("6206",40.9)
    b,detail_b=issuer("1714",110.0,blocked=True,stress=39)
    progress=dict(model=MODEL,estimate_vintage=ASOF,asof_price_date=PRICE,
                  decisions_from_hashed_effective_model_gates=True,
                  formally_certified_Aplus_in_report=0,tracked_issuer_count=3,
                  model_evaluated_issuer_count=2,not_evaluated_issuer_count=1,
                  issuer_diagnostics=[a,b])
    institutional=dict(model=MODEL,estimate_vintage=ASOF,asof_price_date=PRICE,
                       formal_Aplus_count=0,issuer_reviews=[detail_a,detail_b])
    return progress,institutional


class MungerInversionTests(unittest.TestCase):
    def test_read_only_and_no_certification_or_trade_signals(self):
        a,b=fixture();old_a=copy.deepcopy(a);old_b=copy.deepcopy(b)
        result=build(a,b)
        self.assertEqual((a,b),(old_a,old_b))
        self.assertEqual(result["evaluated_issuers"],2)
        self.assertEqual(result["not_evaluated_issuers"],1)
        self.assertEqual(result["new_certificates_issued"],0)
        self.assertTrue(result["official_13_gates_unchanged"])
        self.assertFalse(any(x["trade_signal"] for x in result["reviewed_issuers"]))
        fly=next(x for x in result["reviewed_issuers"] if x["code"]=="6206")
        self.assertEqual(fly["status"],"HIGH_UPSIDE_RESEARCH_ONLY_UNCERTIFIED")
        self.assertIn("EPS_AND_PE_MINUS20_IMPLIES_NEGATIVE_PRICE_UPSIDE",fly["research_red_flags"])
        self.assertEqual(len(fly["evidence_to_disprove_thesis"]),3)
        self.assertEqual(fly["passed_gate_count"],0)
        block=next(x for x in result["reviewed_issuers"] if x["code"]=="1714")
        self.assertEqual(block["status"],"GOVERNANCE_REVIEW_BLOCK")
        self.assertIn("1714",render(result))
        self.assertIn("6206",render(result))
        self.assertIn("非買進名單",render(result))

    def test_pit_and_gate_source_alignment_cannot_be_bypassed(self):
        a,b=fixture()
        a["estimate_vintage"]="2026-10-23"
        with self.assertRaisesRegex(ValueError,"ESTIMATE_VINTAGE"):build(a,b)
        a,b=fixture()
        a["decisions_from_hashed_effective_model_gates"]=False
        with self.assertRaisesRegex(ValueError,"PROVENANCE"):build(a,b)
        a,b=fixture()
        a["issuer_diagnostics"][0]["still_pending_gates"].remove("forecast_bridge")
        with self.assertRaisesRegex(ValueError,"THIRTEEN_GATES"):build(a,b)
        a,b=fixture()
        a["issuer_diagnostics"][0]["gate_stage"]["cash_and_working_capital"]["formal_pass"]=True
        with self.assertRaisesRegex(ValueError,"DECISION_MISMATCH"):build(a,b)

    def test_unverified_formal_plus_rejected(self):
        a,b=fixture()
        a["issuer_diagnostics"][0]["formal_Aplus"]=True
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_FORMAL"):build(a,b)

    def test_focus_issuer_and_coverage_must_match(self):
        a,b=fixture()
        a["model_evaluated_issuer_count"]=3
        with self.assertRaisesRegex(ValueError,"COUNT_MISMATCH"):build(a,b)
        a,b=fixture()
        b["issuer_reviews"].append(dict(code="8888",market="TWSE"))
        with self.assertRaisesRegex(ValueError,"FOCUS_ISSUER"):build(a,b)

    def test_pub_writes_hashes_and_rejects_wrong_version_without_mutation(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            rankings=root/"tw-market-data/rankings";rankings.mkdir(parents=True)
            a,b=fixture()
            progress=json.dumps(a,ensure_ascii=False).encode()
            institutional=json.dumps(b,ensure_ascii=False).encode()
            (rankings/"v891_gate_progress.json").write_bytes(progress)
            (rankings/"latest_institutional.json").write_bytes(institutional)
            (root/"VERSION").write_text(MODEL+"\n")
            report=publish(root)
            self.assertEqual(report["input_sha256"]["v891_gate_progress.json"],hashlib.sha256(progress).hexdigest())
            self.assertEqual(json.loads((rankings/"latest_munger_review.json").read_text())["new_certificates_issued"],0)
            self.assertIn("非買進名單",(rankings/"latest_munger_review.md").read_text())
            (root/"VERSION").write_text("V8.11.0")
            with self.assertRaisesRegex(ValueError,"VERSION_MISMATCH"):publish(root)


if __name__=="__main__":
    unittest.main()
