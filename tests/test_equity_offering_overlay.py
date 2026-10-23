"""Tests: no PIT look-ahead and no false certified equity valuation."""
import json
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.offering import equity_offering_overlay


class OfferingOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        p=root/'evidence/v880/equity_offerings/8390.json'
        p.parent.mkdir(parents=True)
        self.event=dict(code='8390',status='ANNOUNCED_NOT_YET_ISSUED',
                        announced_at='2026-10-22T17:09:16+08:00',
                        first_observed_at='2026-10-23T16:22:00+08:00',
                        planned_subscription_record_date='2026-11-17',
                        planned_new_common_shares=8_000_000,
                        reference_existing_common_shares=96_116_128,
                        issuance_price_twd=None,
                        source_url='https://example.invalid/filing')
        self.path=p
        self.path.write_text(json.dumps(self.event))
        self.root=root
        self.base={'shares':96_116_128,'parent_profit_k':1_329_633.0662181797,'eps':13.8336103824,'pe':13.22,'target_price':182.88}

    def tearDown(self):
        self.temp.cleanup()

    def check(self,asof='2026-10-23T16:30:00+08:00',master=96_116_128):
        return equity_offering_overlay(self.root,'8390',asof,'2027-12-31',self.base,master)

    def test_unissued_sensitivity_does_not_mutate_base(self):
        before=self.base.copy()
        r=self.check()
        self.assertEqual(r['planned_new_common_shares'],8_000_000)
        self.assertAlmostEqual(r['issuance_eps_sensitivity'],1_329_633.0662181797*1000/104_116_128)
        self.assertFalse(r['rank_using_mechanical_sensitivity'])
        self.assertTrue(r['price_upside_from_pre_ex_rights_close_not_comparable'])
        self.assertFalse(r['certified'])
        self.assertEqual(self.base,before)

    def test_historical_pit_does_not_know_future_discovery(self):
        self.assertIsNone(self.check('2026-10-22T23:59:59+08:00'))
        self.assertIsNone(self.check('2026-10-23T16:21:59+08:00'))

    def test_existing_share_count_change_requires_reconciliation(self):
        r=self.check(master=104_116_128)
        self.assertEqual(r['status'],'OFFERING_MASTER_SHARE_COUNT_CHANGED_RECONCILE_FIRST')
        self.assertNotIn('issuance_eps_sensitivity',r)

    def test_unknown_or_mismatched_code_no_fabricated_event(self):
        self.assertIsNone(equity_offering_overlay(self.root,'1785','2026-10-23T16:30:00+08:00','2027-12-31',self.base,96_116_128))
        self.event['code']='OTHER'
        self.path.write_text(json.dumps(self.event))
        with self.assertRaisesRegex(ValueError,'OFFERING_ISSUER_IDENTITY_MISMATCH'):
            self.check()


if __name__=='__main__':
    unittest.main()
