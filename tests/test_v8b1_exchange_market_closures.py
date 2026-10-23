"""Exchange closure evidence: 2026/10/23 typhoon and 10/26 statutory holiday.

A post-announcement fact cannot be applied to a historical earlier as-of,
and a confirmed closed weekday is not a substitute for an exchange price.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.freshness import (
    load_dated_exchange_closures,assess_price_freshness
)

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'


class MarketClosurePITTests(unittest.TestCase):
    def records(self):
        return load_dated_exchange_closures(ROOT)

    def test_bounded_published_oct23_typhoon_does_not_flag_missing_price(self):
        x=assess_price_freshness('2026-10-24T07:04:00+08:00',
                                 '2026-10-22',self.records())
        self.assertEqual(x['known_confirmed_closed_weekdays'],['2026-10-23'])
        self.assertEqual(x['potentially_missing_weekdays'],[])
        self.assertEqual(x['status'],
                         'KNOWN_CLOSURES_ELIMINATE_WEEKDAY_GAP_NOT_TRADING_CERTIFIED')
        self.assertFalse(x['equity_source_may_be_stale'])
        self.assertFalse(x['quote_is_confirmed_latest_session'])
        self.assertFalse(x['market_holiday_calendar_certified'])
        self.assertFalse(x['quotes_imputed_or_backfilled'])

    def test_future_holiday_oct26_and_next_expected_oct27(self):
        records=self.records()
        before=assess_price_freshness('2026-10-27T10:30:00+08:00',
                                      '2026-10-22',records)
        self.assertEqual(before['known_confirmed_closed_weekdays'],
                         ['2026-10-23','2026-10-26'])
        self.assertEqual(before['potentially_missing_weekdays'],[])
        after=assess_price_freshness('2026-10-27T17:10:00+08:00',
                                     '2026-10-22',records)
        self.assertEqual(after['potentially_missing_weekdays'],['2026-10-27'])
        self.assertTrue(after['equity_source_may_be_stale'])

    def test_only_published_before_asof_may_suppress_gap(self):
        records=self.records()
        synthetic=copy.deepcopy(records)
        synthetic[0]['observed_public_at']='2026-10-23T18:00:00+08:00'
        old=assess_price_freshness('2026-10-23T17:00:00+08:00',
                                   '2026-10-22',synthetic)
        self.assertEqual(old['potentially_missing_weekdays'],['2026-10-23'])
        updated=assess_price_freshness('2026-10-23T19:00:00+08:00',
                                       '2026-10-22',synthetic)
        self.assertEqual(updated['potentially_missing_weekdays'],[])
        self.assertEqual(updated['known_confirmed_closed_weekdays'],['2026-10-23'])

    def test_undocumented_weekday_still_raises_staleness_warning(self):
        data=self.records()
        result=assess_price_freshness('2026-10-28T17:00:00+08:00',
                                      '2026-10-22',data)
        self.assertEqual(result['potentially_missing_weekdays'],
                         ['2026-10-27','2026-10-28'])
        self.assertTrue(result['equity_source_may_be_stale'])

    def test_invalid_or_forged_closure_records_rejected(self):
        template=json.loads((ROOT/'config/daily_price_closures_v1.json').read_text())
        for field,value in [
            ('complete_annual_calendar',True),
            ('scope','SOME_OTHER_EXCHANGE')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'config').mkdir()
                record=copy.deepcopy(template)
                record[field]=value
                (root/'config/daily_price_closures_v1.json').write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    load_dated_exchange_closures(root)
        for change in [
            ('source_url','https://example.com/typhoon'),
            ('markets',['TWSE']),
            ('observed_public_at','2026-10-24T12:00:00+08:00'),
            ('date','2026-10-26')]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'config').mkdir()
                record=copy.deepcopy(template)
                record['closing_sessions'][0][change[0]]=change[1]
                (root/'config/daily_price_closures_v1.json').write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    load_dated_exchange_closures(root)

    def test_no_evidence_defaults_to_existing_weekday_heuristic(self):
        x=assess_price_freshness('2026-10-24T07:04:00+08:00','2026-10-22')
        self.assertEqual(x['potentially_missing_weekdays'],['2026-10-23'])
        self.assertTrue(x['equity_source_may_be_stale'])


if __name__=='__main__':
    unittest.main()
