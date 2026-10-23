import unittest
from tw_model_v880 import VERSION

from scripts.v892_top20_quality_audit import validate, indexed, priority


def fixture():
    rows = [
        dict(code=str(1000+i),market="TWSE",rankable=True,
             base=dict(eps=3.0,pe=12.0,target_price=36.0),
             reference_close=20.0)
        for i in range(20)
    ]
    r = dict(model="V8.8.2",estimate_vintage="2026-10-20T08:52:00+08:00",
             asof_price_date="2026-10-16",financial_last_quarter="2026-Q2",
             model_code_sha256="a"*64,formal_Aplus_count=0,top30_provisional=rows)
    d = {k:dict(estimate_vintage=r["estimate_vintage"],
                asof_price_date=r["asof_price_date"],
                financial_last_quarter=r["financial_last_quarter"],
                formal_Aplus_count=0,source_model_code_sha256=r["model_code_sha256"])
         for k in ("cash","shares","risk")}
    return r,d


def example_record():
    return dict(code="1234",source_tier="ORIGINAL_CURRENT_ISSUER_NUMERICS",
        base_2027_pe=16.0,cb_unverified_issues=[],
        stress_double20_upside_pct=45.0,q3_revenue_yoy_pct=20.0,
        analysis={"operating_cashflow_ytd_k":100000,"2027_eps_over_ytd_runrate":1.2})


class Top20AuditTests(unittest.TestCase):
    def test_current_runtime_keeps_the_reviewed_scenario_contract(self):
        r,d=fixture();r['model']=VERSION
        self.assertEqual(len(validate(r,d)[0]),20)

    def test_unknown_model_still_requires_a_new_audit(self):
        r,d=fixture();r['model']='UNREVIEWED_FUTURE_MODEL'
        with self.assertRaisesRegex(ValueError,'MODEL_REQUIRES_NEW_AUDIT'):validate(r,d)

    def test_matching_vintage_validates_twenty_rows(self):
        r,d=fixture()
        top,instant,quarter,prior,fy,n=validate(r,d)
        self.assertEqual((len(top),quarter,prior,fy,n),
                         (20,"2026-Q2","2025-Q2","2025-Q4",2))

    def test_stale_cash_mismatched_shares_refused(self):
        r,d=fixture()
        d["cash"]["asof_price_date"]="2026-10-17"
        with self.assertRaisesRegex(ValueError,"AUDIT_VINTAGE_OR_MODEL_MISMATCH_cash"):
            validate(r,d)
        r,d=fixture()
        d["shares"]["source_model_code_sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"AUDIT_VINTAGE_OR_MODEL_MISMATCH_shares"):
            validate(r,d)

    def test_duplicate_security_and_insufficient_universe_refused(self):
        r,d=fixture()
        r["top30_provisional"][1]["code"]="1000"
        with self.assertRaisesRegex(ValueError,"DUPLICATE_TOP20"):
            validate(r,d)
        r,d=fixture()
        r["top30_provisional"].pop()
        with self.assertRaisesRegex(ValueError,"TOP20_SOURCE_INCOMPLETE"):
            validate(r,d)

    def test_mirror_issuer_codes_are_unique(self):
        self.assertEqual(list(indexed([{"code":"6206"}],"cash")),["6206"])
        with self.assertRaisesRegex(ValueError,"INVALID_OR_DUPLICATE"):
            indexed([{"code":"6206"},{"code":"6206"}],"cash")

    def test_positive_cash_limited_eps_and_20pct_stress_are_priority_not_cert(self):
        strength,reasons=priority(example_record())
        self.assertEqual(strength,11)
        self.assertEqual(reasons,[])

    def test_negative_ocf_and_unverified_cb_do_not_auto_fail_or_certify(self):
        row=example_record()
        row["analysis"]["operating_cashflow_ytd_k"]=-900000
        row["analysis"]["2027_eps_over_ytd_runrate"]=2.1
        row["base_2027_pe"]=24.0
        row["cb_unverified_issues"]=["54391"]
        row["q3_revenue_yoy_pct"]=-5.0
        strength,reasons=priority(row)
        self.assertLess(strength,11)
        self.assertIn("NEGATIVE_OR_ZERO_H1_OCF_REQUIRES_WORKING_CAPITAL_BRIDGE",reasons)
        self.assertIn("CB_LEGAL_TERMS_UNVERIFIED",reasons)
        self.assertNotIn("FORMAL_FAIL",reasons)

    def test_severe_margin_erosion_downgrades_even_high_upside(self):
        row=example_record()
        original,_=priority(row)
        row["analysis"]["gross_margin_delta_pp"]=-9.9
        row["analysis"]["operating_margin_delta_pp"]=-4.0
        reduced,issues=priority(row)
        self.assertEqual(reduced,original-3)
        self.assertIn("GROSS_MARGIN_DECLINED_AT_LEAST_3PP",issues)
        self.assertIn("OPERATING_MARGIN_DECLINED_AT_LEAST_2PP",issues)

    def test_very_aggressive_eps_and_high_pe_receive_extra_scrutiny(self):
        row=example_record()
        row["analysis"]["2027_eps_over_ytd_runrate"]=1.9
        row["base_2027_pe"]=26
        _,issues=priority(row)
        self.assertIn("FORWARD_EPS_AT_LEAST_1_7X_H1_ANNUALIZED_HIGH_BRIDGE_RISK",issues)
        self.assertIn("FORWARD_PE_25X_OR_HIGHER_REQUIRES_STRONGER_JUSTIFICATION",issues)

    def test_equity_watch_penalizes_rank_not_mutates_certification(self):
        row=example_record();row["code"]="8390"
        s,issues=priority(row)
        self.assertEqual(s,8)
        self.assertIn("EQUITY_ISSUANCE_NOT_CONFIRMED",issues)

    def test_material_governance_is_explicit_not_a_made_up_eps_or_pe_discount(self):
        row=example_record()
        before,_=priority(row)
        row['governance_review']={'blocks_recommendation':True}
        after,issues=priority(row)
        self.assertEqual(before,after)
        self.assertEqual(issues[0],'MATERIAL_GOVERNANCE_REVIEW_REQUIRED')


if __name__=="__main__":unittest.main()
