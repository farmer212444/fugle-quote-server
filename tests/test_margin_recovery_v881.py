import unittest
from tw_model_v880.margin_recovery import assess_margin_recovery

def row(gm):
    return dict(revenue_ytd_k=100000, gross_profit_ytd_k=100000*gm)

class ConditionalMarginRecoveryTests(unittest.TestCase):
    def h(self,older=.1908,recent=.1829):
        return {'2024-Q4':row(older),'2025-Q4':row(recent)}
    def assess(self,h=None,industry='運動休閒',monthly=72,ytd=13,raw=.152883,current=.1472):
        return assess_margin_recovery(h if h is not None else self.h(),'2026-Q2',raw,current,monthly,ytd,industry)
    def test_9802_like_history_has_conditional_base_but_not_certification(self):
        r=self.assess()
        self.assertTrue(r['applied'])
        self.assertAlmostEqual(r['provisional_base_gm'],.17835825,places=6)
        self.assertEqual(r['recovery_fraction'],.75)
        self.assertFalse(r['causal_factory_evidence_verified'])
        self.assertFalse(r['holdout_validation_complete'])
    def test_no_older_fiscal_year_never_backfills_future_data(self):
        self.assertFalse(self.assess({'2025-Q4':row(.183)})['applied'])
    def test_unstable_years_do_not_promote_normalization(self):
        r=self.assess(self.h(.30,.18))
        self.assertFalse(r['applied'])
        self.assertEqual(r['status'],'UNSTABLE_TWO_YEAR_REFERENCE_REQUIRES_COMPANY_REVIEW')
    def test_weak_revenue_signals_leave_original_base(self):
        r=self.assess(monthly=-5,ytd=-1)
        self.assertTrue(r['candidate'])
        self.assertFalse(r['applied'])
        self.assertEqual(r['provisional_base_gm'],r['unadjusted_base_gm'])
    def test_nonmanufacturing_specialist_requires_issuer_bridge(self):
        r=self.assess(industry='生技醫療業')
        self.assertFalse(r['applied'])
        self.assertEqual(r['status'],'SECTOR_SPECIALIST_OPERATING_DRIVERS_REQUIRED')
    def test_extreme_base_effect_requires_manual_review(self):
        r=self.assess(monthly=900)
        self.assertFalse(r['applied'])
    def test_no_raise_if_already_fairly_normalized(self):
        r=self.assess(raw=.185)
        self.assertFalse(r['applied'])
    def test_moderate_revenue_only_gets_half_gap(self):
        r=self.assess(monthly=12,ytd=5)
        self.assertTrue(r['applied'])
        self.assertAlmostEqual(r['recovery_fraction'],.5)
    def test_target_is_capped_below_historical_average(self):
        r=self.assess(raw=.01,current=.01)
        self.assertLessEqual(r['provisional_base_gm'],r['normalized_gm'])
        self.assertLessEqual(r['base_uplift_pp'],3.5+1e-10)

if __name__ == '__main__':unittest.main()
