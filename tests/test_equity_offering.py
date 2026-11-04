import copy
import json
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.offering import equity_offering_overlay


class OfferingPricingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'evidence/v880/equity_offerings/8390.json'
        self.path.parent.mkdir(parents=True)
        self.base = dict(parent_profit_k=1100000, shares=110000000, pe=15)
        self.event = dict(
            code='8390', status='ANNOUNCED_NOT_YET_ISSUED',
            announced_at='2026-10-22T17:09:16+08:00',
            first_observed_at='2026-10-23T16:22:00+08:00',
            planned_subscription_record_date='2026-11-17',
            planned_new_common_shares=8000000,
            reference_existing_common_shares=100000000,
            issuance_price_twd=None, source_url='https://issuer.example/plan',
            pricing_updates=[dict(announced_on='2026-11-04',
                first_observed_at='2026-11-04T23:24:47+08:00',
                issuance_price_twd=62, source_url='https://issuer.example/price')])

    def run_overlay(self, asof='2026-11-04T23:25:00+08:00'):
        self.path.write_text(json.dumps(self.event))
        return equity_offering_overlay(self.root, '8390', asof, '2027-12-31',
                                       self.base, 100000000)

    def test_price_is_not_admitted_before_independent_discovery(self):
        result = self.run_overlay('2026-11-04T23:24:46+08:00')
        self.assertIsNone(result['issuance_price_twd'])
        self.assertIsNone(result['expected_proceeds_twd'])
        self.assertIsNone(result['pricing_first_observed_at'])

    def test_price_proceeds_and_dilution_keep_separate_meanings(self):
        original = copy.deepcopy(self.base)
        result = self.run_overlay()
        self.assertEqual(result['issuance_price_twd'], 62)
        self.assertEqual(result['expected_proceeds_twd'], 496000000)
        self.assertEqual(result['proceeds_basis'], 'ANNOUNCED_GROSS_NOT_RECEIVED_NOT_NET_OF_COSTS')
        self.assertAlmostEqual(result['issuance_eps_sensitivity'], 1100000000/118000000)
        self.assertFalse(result['is_new_stock_already_outstanding'])
        self.assertFalse(result['rank_using_mechanical_sensitivity'])
        self.assertFalse(result['certified'])
        self.assertEqual(self.base, original)

    def test_original_event_discovery_is_still_required(self):
        self.assertIsNone(self.run_overlay('2026-10-23T16:21:59+08:00'))

    def test_unordered_or_impossible_update_clocks_are_rejected(self):
        update = self.event['pricing_updates'][0]
        self.event['pricing_updates'].append(copy.deepcopy(update))
        with self.assertRaisesRegex(ValueError, 'NOT_ORDERED'):
            self.run_overlay()
        self.event['pricing_updates'] = [update]
        update['first_observed_at'] = '2026-11-03T23:24:47+08:00'
        with self.assertRaisesRegex(ValueError, 'BEFORE_PUBLICATION'):
            self.run_overlay()

    def test_invalid_admitted_prices_or_sources_are_rejected(self):
        original = copy.deepcopy(self.event['pricing_updates'][0])
        for update in ({'issuance_price_twd': 0}, {'issuance_price_twd': -1},
                       {'issuance_price_twd': True}, {'issuance_price_twd': 'NaN'},
                       {'source_url': 'http://issuer.example/price'}):
            self.event['pricing_updates'] = [{**original, **update}]
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'UPDATE_INVALID'):
                self.run_overlay()


if __name__ == '__main__':
    unittest.main()
