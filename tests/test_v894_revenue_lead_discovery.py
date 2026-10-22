import unittest
from tw_model_v880 import VERSION
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
    def test_current_runtime_keeps_the_reviewed_discovery_contract(self):
        r=research();r['model']=VERSION
        self.assertEqual(build(r,[rev()])['source_model'],VERSION)

    def test_unknown_model_still_requires_review(self):
        r=research();r['model']='UNREVIEWED_FUTURE_MODEL'
        with self.assertRaisesRegex(ValueError,'MODEL_REQUIRES_REVIEW'):build(r,[rev()])

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

    def test_non_four_digit_identity_is_excluded_without_stopping_common_stocks(self):
        result=build(research(),[rev(code="912000"),rev()])
        self.assertEqual([x["code"] for x in result["ranking"]],["9802"])
        self.assertEqual(result["excluded_invalid_revenue"][0]["reason"],
                         "NON_COMMON_STOCK_CODE_REQUIRES_IDENTITY_MODEL")

    def test_one_invalid_metric_row_is_retained_as_excluded_and_others_continue(self):
        bad=rev(code="3718",monthly=0,prior=0)
        result=build(research(),[bad,rev()])
        self.assertEqual(result["issuer_count"],1)
        self.assertEqual(result["excluded_invalid_revenue_count"],1)
        self.assertEqual(result["excluded_invalid_revenue"][0]["code"],"3718")

    def test_lumpy_property_revenue_is_kept_for_manual_review_not_top20(self):
        property_row=rev(code="4113",my=3425111,ytd=471,monthly=1815362,prior=689457)
        property_row["industry"]="建材營造"
        result=build(research(),[property_row,rev()])
        self.assertEqual([x["code"] for x in result["top20"]],["9802"])
        self.assertEqual(result["manual_review_count"],1)
        self.assertIn("LUMPY_PROJECT_RECOGNITION_REQUIRES_ISSUER_BRIDGE",
                      result["manual_review"][0]["data_quality_flags"])

    def test_extreme_low_base_ratio_is_not_comparable_top20_growth(self):
        extreme=rev(code="1516",my=1473,ytd=48,monthly=11060,prior=9784)
        result=build(research(),[extreme,rev()])
        self.assertEqual([x["code"] for x in result["top20"]],["9802"])
        self.assertIn("EXTREME_GROWTH_RATIO_REQUIRES_BASE_EFFECT_REVIEW",
                      result["manual_review"][0]["data_quality_flags"])


if __name__=="__main__":unittest.main()
