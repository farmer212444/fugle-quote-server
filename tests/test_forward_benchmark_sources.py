"""Frozen picks keep source coverage; official ETF quotes never imply returns."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts.forward_benchmark_sources import refresh,verify_month,source_current
from scripts.history_archive import digest,verify_original,outstanding_benchmark_codes
from scripts.tw_history_backfill import parse,prioritized_candidates
from scripts.v893_tpex_daily_backfill import selected_codes,run as collect_tpex
from scripts import v8a8_forward_top30_0050 as challenge
from tests.test_tw_history_backfill import response
from tests.test_v893_tpex_daily_backfill import payload


class FrozenForwardSources(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.policy=json.loads((Path(__file__).parents[1]/'tw-market-data'/challenge.CONFIG).read_text())
        self.write(challenge.CONFIG,self.policy)
        self.selection=dict(schema=challenge.SCHEMA,month='2026-10',
            policy_sha256=challenge.digest(self.policy),
            archive_eligible_signal_at='2026-10-22T18:06:50+00:00',
            selection_committed_at_utc='2026-10-22T18:07:23+00:00',
            next_eligible_open_only_after='2026-10-22T18:07:23+00:00',
            research_top30=[dict(market='TPEX',code='6494'),dict(market='TWSE',code='1999')]+
                            [dict(market='TWSE',code=str(3000+i)) for i in range(28)])
        self.selection['selection_sha256']=challenge.digest(self.selection)
        self.lock=challenge.OUT+'/monthly/2026-10.json'
        self.write(self.lock,self.selection)
        # No frozen issuer or 0050 is present in today's quote universe.
        raw=b'[{"market":"TWSE","code":"6206","close":21}]'
        (self.root/'prices').mkdir()
        (self.root/'prices/2026-10-22.json').write_bytes(raw)
        self.write('prices/latest_manifest.json',dict(date='2026-10-22',normalized_sha256=digest(raw)))
        self.write('rankings/v891_gate_progress.json',dict(asof_price_date='2026-10-22',issuer_diagnostics=[]))
        self.now=dt.datetime(2099,1,1,tzinfo=dt.timezone.utc)

    def write(self,path,obj):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(obj))

    def raw_etf(self):
        doc=json.loads(response('2026-10',['2026-10-22']))
        doc['title']='115年10月 0050 元大台灣50 各日成交資訊'
        return json.dumps(doc).encode()

    def test_frozen_stocks_survive_both_rank_and_latest_quote_removal(self):
        raw=(self.root/'prices/2026-10-22.json').read_bytes()
        self.assertEqual(outstanding_benchmark_codes(self.root,'TPEX'),['6494'])
        self.assertEqual(selected_codes(self.root,'2026-10-22',raw)[0],['6494'])
        self.assertEqual(prioritized_candidates(raw,'2026-10-22',2,self.root),['1999','3000'])
        # Full TPEx collection must also tolerate no current quote for a pin.
        report=collect_tpex(1,1,lambda url:payload('2026-10-22'),self.root,
                            self.root/'raw',1,now=self.now)
        archive=json.loads((self.root/'prices/issuer_history/TPEX/6494.json').read_text())
        self.assertIn('2026-10-22',archive['by_day'])
        self.assertFalse(archive['issuer_PIT_history_verified'])

    def test_capture_preserves_original_bytes_locks_and_null_performance(self):
        before=(self.root/self.lock).read_bytes();raw=self.raw_etf()
        report=refresh(self.root,fetcher=lambda url:raw,now=self.now)
        self.assertEqual(report['verified_months'],['2026-10'])
        self.assertEqual(report['verified_sessions_through_reference'],1)
        self.assertIsNone(report['model_or_benchmark_return_pct'])
        doc=json.loads((self.root/'benchmarks/0050/months/2026-10.json').read_text())
        self.assertEqual(verify_original(self.root,doc['original_archive']),raw)
        self.assertEqual(verify_month(self.root,doc,'2026-10',self.now)[0]['code'],'0050')
        self.assertFalse(doc['total_return_verified'])
        self.assertFalse(doc['rows'][0]['fillability_verified'])
        doc['last_source_checked_at_utc']='2100-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'CHECK_CLOCK_INVALID'):
            verify_month(self.root,doc,'2026-10',self.now)
        again=refresh(self.root,fetcher=lambda url:self.fail('Verified source was refetched'),now=self.now)
        self.assertEqual(again['requests_attempted'],0)
        self.assertEqual((self.root/self.lock).read_bytes(),before)
        self.assertFalse((self.root/'prices/issuer_history/TWSE/0050.json').exists())

    def test_tampered_normalization_and_original_bytes_never_enter_coverage(self):
        refresh(self.root,fetcher=lambda url:self.raw_etf(),now=self.now)
        path=self.root/'benchmarks/0050/months/2026-10.json'
        doc=json.loads(path.read_text());doc['rows'][0]['close']=9999
        path.write_text(json.dumps(doc))
        report=refresh(self.root,0,now=self.now)
        self.assertEqual(report['verified_months'],[])
        self.assertIn('DIFFER_FROM_ORIGINAL',report['source_errors'][0]['reason'])
        (self.root/doc['original_archive']['archive_path']).write_bytes(b'bad gzip')
        report=refresh(self.root,0,now=self.now)
        self.assertEqual(report['missing_months'],['2026-10'])
        self.assertIsNone(report['model_or_benchmark_return_pct'])

    def test_outage_missing_open_and_short_month_are_never_replaced_with_fills(self):
        def unavailable(url):raise OSError('HTTP 307')
        report=refresh(self.root,fetcher=unavailable,now=self.now)
        self.assertEqual(report['status'],'QUOTE_SOURCE_COLLECTION_INCOMPLETE')
        self.assertEqual(report['verified_sessions_through_reference'],0)
        raw=json.loads(self.raw_etf());raw['data'][0][4]='--'
        records=parse(json.dumps(raw).encode(),'0050','2026-10')
        self.assertIsNone(records[0]['open'])
        self.assertFalse(records[0]['fillability_verified'])
        raw['title']='115年10月 10050 錯誤商品 各日成交資訊'
        with self.assertRaisesRegex(ValueError,'CODE_NOT_CONFIRMED'):
            parse(json.dumps(raw).encode(),'0050','2026-10')

    def test_policy_or_selection_tampering_blocks_collection(self):
        self.selection['research_top30'][0]['code']='9999'
        self.write(self.lock,self.selection)
        with self.assertRaisesRegex(ValueError,'TAMPERED'):
            refresh(self.root,0,now=self.now)

    def test_partial_month_must_be_refreshed_after_rollover(self):
        partial=dict(original_archive=dict(captured_at_utc='2026-10-30T01:00:00+00:00'),
                     rows=[dict(date='2026-10-29')])
        self.assertTrue(source_current(partial,'2026-10','2026-10-29'))
        self.assertFalse(source_current(partial,'2026-10','2026-10-30'))
        self.assertFalse(source_current(partial,'2026-10','2026-11-02'))
        # UTC Oct31 18:00 is already November in the exchange's timezone.
        partial['original_archive']['captured_at_utc']='2026-10-31T18:00:00+00:00'
        self.assertTrue(source_current(partial,'2026-10','2026-11-02'))
        # Repeated identical bytes retain their first immutable capture clock;
        # an actual subsequent HTTP check still finalizes the month.
        partial['original_archive']['captured_at_utc']='2026-10-30T01:00:00+00:00'
        partial['last_source_checked_at_utc']='2026-10-31T18:00:00+00:00'
        self.assertTrue(source_current(partial,'2026-10','2026-11-02'))


if __name__=='__main__':unittest.main()
