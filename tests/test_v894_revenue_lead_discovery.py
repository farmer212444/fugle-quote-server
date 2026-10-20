import unittest
from scripts.v894_revenue_lead_discovery import score_revenue, valuation_points, build


def rev(code="9802",my=72,ytd=12.97,monthly=1810000,prior=1500000):
    return dict(code=code,name="測試",market="TWSE",industry="運動休閒",report_month="11509",
                monthly_revenue_k=monthly,prior_month_revenue_k=prior,
                monthly_yoy_pct=my,ytd_yoy_pct=ytd)


def research():
    return dict(model="V8.8.2",model_code_sha256="a"*64,
                estimate_vintage="2026-10-20T16:00:00+08:00",asof_price_date="2026-10-19",
                revenue_month="2026-09",formal_Aplus_count=0,formal_Aplusplus_count=0,
                top30_provisional=[dict(code="9802",rankable=True,base=dict(price_upside_pct=17.8))])


class RevenueLeadTests(unittest.TestCase):
    def test_revenue_acceleration_scores_before_margin(self):
        row=score_revenue(rev())
        self.assertGreater(row["revenue_points"],60)
        self.assertIn("MULTI_MONTH_CONTINUITY_NOT_YET_OBSERVED",row["risk_flags"])

    def test_missing_continuity_never_receives_points(self):
        self.assertEqual(score_revenue(rev(),0)["continuity_points"],0)
        self.assertEqual(score_revenue(rev(),2)["continuity_points"],10)

    def test_revenue_decline_is_flagged_not_silently_promoted(self):
        row=score_revenue(rev(my=-15,ytd=8,monthly=600,prior=1000))
        self.assertIn("MONTH_ON_MONTH_REVENUE_DROP_AT_LEAST_30PCT",row["risk_flags"])
        self.assertIn("MONTHLY_YOY_DECELERATED_AT_LEAST_20PP_VS_YTD",row["risk_flags"])

    def test_valuation_is_capped_and_unknown_gets_zero(self):
        self.assertEqual(valuation_points(None),(0.0,"VALUATION_NOT_COMPARABLE"))
        self.assertEqual(valuation_points(dict(rankable=True,base=dict(price_upside_pct=80)))[0],20)

    def test_build_never_changes_formal_grades(self):
        result=build(research(),[rev()])
        self.assertEqual(result["formal_Aplus_count_unchanged"],0)
        self.assertFalse(result["ranking"][0]["formal_grade_changed"])

    def test_duplicate_or_invalid_code_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            build(research(),[rev(),rev()])

    def test_one_invalid_metric_row_is_retained_as_excluded_and_others_continue(self):
        bad=rev(code="3718",monthly=0,prior=0)
        result=build(research(),[bad,rev()])
        self.assertEqual(result["issuer_count"],1)
        self.assertEqual(result["excluded_invalid_revenue_count"],1)
        self.assertEqual(result["excluded_invalid_revenue"][0]["code"],"3718")


if __name__=="__main__":unittest.main()
