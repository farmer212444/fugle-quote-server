"""Regression for the missing TPEx daily-history input, using synthetic originals."""
import copy
import datetime as dt
import hashlib
import json
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.history_archive import archive_original,verify_original
from scripts.institutional_review import DailyTurnoverSnapshot,liquidity_history
from scripts.return_model_search import feature_rows
from scripts.v893_tpex_daily_backfill import daily_url,parse_daily
from tests.test_v893_tpex_daily_backfill import payload


class TpexResearchLiquidity(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.asof=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=1)).isoformat()
        self.day='2026-10-22'
        self.histories={code:{} for code in ('6494','5439')}
        days=[];day=dt.date.fromisoformat(self.day)
        while len(days)<20:
            if day.weekday()<5:days.append(day.isoformat())
            day-=dt.timedelta(days=1)
        for i,day in enumerate(days):
            obj=json.loads(payload(day))
            obj['tables'][0]['data'][0][9]=str(30_000_000+i*100_000)
            obj['tables'][0]['data'][1][9]=str(45_000_000+i*100_000)
            raw=json.dumps(obj).encode();parsed=parse_daily(raw,day)
            original=archive_original(self.root,'TPEX',day,daily_url(day),raw,parsed)
            for code in self.histories:
                self.histories[code][day]=dict(date=day,source_url=original['source_url'],
                    original_response_sha256=original['original_response_sha256'],
                    captured_at_utc=original['captured_at_utc'],original_archive=original,row=parsed[code])
        self.flush_history()
        self.daily=[self.histories[code][self.day]['row'] for code in self.histories]
        self.flush_daily()

    def flush_history(self):
        folder=self.root/'prices/issuer_history/TPEX';folder.mkdir(parents=True,exist_ok=True)
        for code,days in self.histories.items():
            (folder/(code+'.json')).write_text(json.dumps(dict(schema='V893_OFFICIAL_TPEX_DAILY',
                issuer=code,market='TPEX',price_reference_asof=self.day,by_day=days)))

    def flush_daily(self):
        raw=json.dumps(self.daily).encode();(self.root/'prices'/(self.day+'.json')).write_bytes(raw)
        (self.root/'prices/latest_manifest.json').write_text(json.dumps(dict(
            date=self.day,normalized_sha256=hashlib.sha256(raw).hexdigest())))

    def row(self,code='6494'):
        return dict(code=code,market='TPEX',price_date=self.day)

    def test_20_archived_days_restore_both_issuer_medians_without_certifying_trades(self):
        snapshot=DailyTurnoverSnapshot(self.root,self.asof,self.day)
        with patch('scripts.history_archive.verify_original',wraps=verify_original) as verify:
            for code in self.histories:
                result=liquidity_history(self.root,self.row(code),self.asof,snapshot)
                expected=statistics.median(r['row']['turnover_ntd'] for r in self.histories[code].values())
                self.assertEqual(result['median20_turnover_ntd'],expected)
                self.assertEqual(result['sessions'],20)
                self.assertEqual(result['last_date'],self.day)
                self.assertFalse(result['spread_and_exit_verified'])
            self.assertEqual(verify.call_count,20)

    def test_future_capture_is_not_a_historical_input(self):
        cutoff='2026-10-23T00:00:00+08:00'
        result=liquidity_history(self.root,self.row(),cutoff)
        self.assertEqual(result['sessions'],1)
        self.assertIsNone(result['median20_turnover_ntd'])

    def test_future_session_is_ignored_even_if_captured_early(self):
        self.histories['6494']['2026-10-23']=copy.deepcopy(self.histories['6494'][self.day])
        self.flush_history()
        self.assertEqual(liquidity_history(self.root,self.row(),self.asof)['sessions'],20)

    def test_changed_issuer_row_or_original_identity_rejected(self):
        for kind in ('amount','date','market','issuer','receipt'):
            with self.subTest(kind=kind):
                original=copy.deepcopy(self.histories['6494'][self.day])
                item=self.histories['6494'][self.day]
                if kind=='amount':item['row']['turnover_ntd']+=1
                elif kind=='date':item['date']='2026-10-21'
                elif kind=='market':item['row']['market']='TWSE'
                elif kind=='issuer':item['row']['code']='5439'
                else:item['original_archive']['identity']='2026-10-21'
                self.flush_history()
                with self.assertRaisesRegex(ValueError,'TPEX_LIQUIDITY'):
                    liquidity_history(self.root,self.row(),self.asof)
                self.histories['6494'][self.day]=original

    def test_next_report_rereads_corrupt_original(self):
        self.assertIsNotNone(liquidity_history(self.root,self.row(),self.asof)['median20_turnover_ntd'])
        reference=self.histories['6494'][self.day]['original_archive']
        (self.root/reference['archive_path']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'HISTORY_ORIGINAL_COMPRESSION_CORRUPT'):
            liquidity_history(self.root,self.row(),self.asof)

    def test_daily_and_original_turnover_conflict_is_not_averaged_away(self):
        self.daily[0]=dict(self.daily[0],turnover_ntd=1);self.flush_daily()
        with self.assertRaisesRegex(ValueError,'CONFLICTING_MARKET_AND_ISSUER'):
            liquidity_history(self.root,self.row(),self.asof)

    def test_return_features_consume_tpex_history_and_preserve_governance_block(self):
        folder=self.root/'fundamentals/2026-Q2';folder.mkdir(parents=True)
        (folder/'TPEX_income.json').write_text(json.dumps(dict(period='2026-Q2',market='TPEX',
            rows=[dict(code='6494',revenue_ytd_k=1000)])))
        row=dict(self.row(),rankable=True,financial_period='2026-Q2',recommendation_blocked=True,
                 industry='SEMICONDUCTOR',liquidity=dict(ocf_k=200),scenario_upside_pct=50,
                 margin_bridge=dict(current_ytd_gm=.3,prior_ytd_gm=.2))
        rows,_,errors=feature_rows(self.root,dict(all_model_rows=[row],
            asof_price_date=self.day,financial_last_quarter='2026-Q2'),self.asof)
        self.assertEqual(errors,[])
        self.assertEqual(rows[0]['adv20_ntd'],30_950_000)
        self.assertTrue(rows[0]['recommendation_blocked'])
        self.assertTrue(rows[0]['features_are_research_not_quality_certification'])


if __name__=='__main__':unittest.main()
