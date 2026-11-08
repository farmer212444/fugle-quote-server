"""Synthetic source-contract tests; these do not certify any real issuer."""
import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tw_model_v880.early_bulk import (ANNOUNCEMENT_KIND, FOLDER, SCHEMA, SOURCE_KIND,
    URLS, announcement, facts, load, parse, sha)
from tw_model_v880.data import model_source_state
from tw_model_v880.model import estimate
from tests import test_institutional_controls as fixtures

ASOF = '2026-11-08T22:00:00+08:00'
CAPTURE = '2026-11-08T12:00:00+00:00'


def row():
    return {'公司代號': '1234', '出表日期': '1151108', '年度': '115', '季別': '3',
            '營業收入': '900', '營業毛利（毛損）淨額': '210', '營業費用': '120',
            '營業利益（損失）': '90', '營業外收入及支出': '20', '稅前淨利（淨損）': '110',
            '所得稅費用（利益）': '22', '本期淨利（淨損）': '88',
            '淨利（淨損）歸屬於母公司業主': '88', '淨利（淨損）歸屬於非控制權益': '0',
            '基本每股盈餘（元）': '0.88'}


def notice():
    return '''<html><body>本資料由 (上市公司) 1234 SYNTHETIC TEST ONLY 公司提供
發言日期 115/11/05 發言時間 19:17:40
3.財務報告或年度自結財務資訊報導期間起訖日期(XXX/XX/XX~XXX/XX/XX):115/01/01~115/09/30
4.1月1日累計至本期止營業收入(仟元):900
5.1月1日累計至本期止營業毛利(毛損) (仟元):210
6.1月1日累計至本期止營業利益(損失) (仟元):90
7.1月1日累計至本期止稅前淨利(淨損) (仟元):110
8.1月1日累計至本期止本期淨利(淨損) (仟元):88
9.1月1日累計至本期止歸屬於母公司業主淨利(損) (仟元):88
10.1月1日累計至本期止基本每股盈餘(損失) (元):0.88
11.期末總資產(仟元):1000</body></html>'''.encode()


def notice_receipt():
    return dict(code='1234', market='TWSE', source_kind=ANNOUNCEMENT_KIND, captured_at=CAPTURE,
        source_url='https://mopsov.twse.com.tw/mops/web/ajax_t05st01?co_id=1234&TYPEK=sii&step=2&spoke_date=20261105&spoke_time=191740&seq_no=1')


class EarlyQuarterSources(unittest.TestCase):
    def test_partial_table_is_usable_without_claiming_full_market_coverage(self):
        result = parse(json.dumps([row()]).encode())
        self.assertEqual(facts(result['1234'])['parent_net_income_k'], 88)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            parse(json.dumps([row(), row()]).encode())

    def test_inconsistent_missing_and_nonfinite_fields_reject(self):
        for key, value in [('營業費用', '999'), ('營業收入', 'NaN'), ('本期淨利（淨損）', '')]:
            with self.subTest(key=key):
                bad = row(); bad[key] = value
                with self.assertRaises(ValueError):
                    facts(bad)

    def test_disclosed_other_operating_gains_are_reconciled_without_calling_net_cost_opex(self):
        original=row();original['其他收益及費損淨額']='12';original['營業費用']='132'
        result=facts(original)
        self.assertEqual(result['opex_k'],120)
        self.assertEqual(result['reported_opex_k'],132)
        self.assertEqual(result['other_operating_gains_k'],12)

    def test_company_notice_has_bound_issuer_period_units_and_release_clock(self):
        receipt = notice_receipt()
        parsed = announcement(notice(), receipt)['1234']
        self.assertEqual(facts(parsed), facts(row()))
        self.assertEqual(facts(announcement(notice().replace(b'115/01/01~115/09/30', b'115/01/01-115/09/30'),receipt)['1234']), facts(row()))
        for old, new in [('(上市公司) 1234', '(上市公司) 9999'), ('115/09/30', '114/09/30'),
                         ('營業收入(仟元)', '營業收入(百萬元)'), ('19:17:40', '19:17:41')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                announcement(notice().decode().replace(old, new).encode(), receipt)
        with self.assertRaisesRegex(ValueError, 'RELEASE_FROM_FUTURE'):
            announcement(notice(), dict(receipt, captured_at='2026-11-04T00:00:00+00:00'))

    def test_negative_announcement_values_remain_negative(self):
        raw = notice().decode().replace('損失) (仟元):90', '損失) (仟元):(90)')
        self.assertEqual(announcement(raw.encode(), notice_receipt())['1234']['營業利益（損失）'], -90)

    def setup_data(self, root):
        raw = json.dumps([row()], ensure_ascii=False).encode()
        packed = gzip.compress(raw, mtime=0)
        path = root/FOLDER/'TWSE'/'source.raw.gz';path.parent.mkdir(parents=True)
        path.write_bytes(packed)
        receipt = dict(market='TWSE', source_url=URLS['TWSE'], archive_path=path.relative_to(root).as_posix(),
                       raw_sha256=sha(raw), gzip_sha256=sha(packed), bytes=len(raw), captured_at=CAPTURE)
        doc = dict(schema=SCHEMA, formal_quality_pass=False, captures=[receipt],
                   requested_issuers=[dict(code='1234', market='TWSE'), dict(code='5678', market='TWSE')])
        manifest = root/FOLDER/'manifest.json'
        manifest.write_text(json.dumps(doc))
        prev = dict(revenue_k=600, gross_profit_k=180, operating_profit_k=60,
                    pretax_profit_k=70, net_income_k=56, parent_net_income_k=56)
        prior = dict(revenue_k=750, gross_profit_k=150, operating_profit_k=75,
                     pretax_profit_k=90, net_income_k=72, parent_net_income_k=72)
        data = SimpleNamespace(root=root, period='2026-Q2', history={('TWSE','1234'): {}},
                evidence={'master': {'1234': {'market': 'TWSE'}}},
                detailed_values=lambda key, p: prev if p=='2026-Q2' else prior)
        return data, doc, path, manifest

    def test_absent_issuer_is_unknown_not_zero_and_future_capture_is_not_used(self):
        with tempfile.TemporaryDirectory() as folder:
            data, doc, _, manifest = self.setup_data(Path(folder))
            events, states = load(data, ASOF)
            self.assertEqual(events['1234']['single_quarter']['revenue_k'], 300)
            self.assertFalse(events['1234']['formal_quality_pass'])
            self.assertTrue(events['1234']['standalone_quarter_derived_by_ytd_difference'])
            self.assertEqual(states['5678']['status'], 'NOT_OBSERVED_IN_PARTIAL_OFFICIAL_TABLE')
            self.assertNotIn('5678', events)
            events, states = load(data, '2026-11-08T19:59:59+08:00')
            self.assertFalse(events)
            self.assertFalse(states['1234']['blocks_current_decision'])

    def test_tampered_unsafe_and_wrong_source_do_not_reuse_old_forecast(self):
        for field, value in [('gzip_sha256','0'*64), ('archive_path','../outside.gz'),
                             ('source_url','https://example.invalid/table')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                data, doc, _, manifest = self.setup_data(Path(folder))
                doc['captures'][0][field] = value;manifest.write_text(json.dumps(doc))
                events, states = load(data, ASOF)
                self.assertFalse(events)
                self.assertTrue(states['1234']['blocks_current_decision'])

    def test_duplicate_market_and_incomplete_prior_components_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            data, doc, _, manifest = self.setup_data(Path(folder))
            data.detailed_values = lambda *args: {'revenue_k': 1}
            events, states = load(data, ASOF)
            self.assertFalse(events)
            self.assertTrue(states['1234']['blocks_current_decision'])
            doc['captures'] *= 2;manifest.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'DUPLICATE_MARKET'):
                load(data, ASOF)

    def test_conflicting_company_notice_and_official_table_isolates_issuer(self):
        with tempfile.TemporaryDirectory() as folder:
            data, doc, _, manifest = self.setup_data(Path(folder))
            raw = notice().replace(b':900', b':901')
            path = Path(folder)/FOLDER/'notice.gz';packed=gzip.compress(raw,mtime=0);path.write_bytes(packed)
            receipt = dict(notice_receipt(), archive_path=path.relative_to(folder).as_posix(),
                           raw_sha256=sha(raw),gzip_sha256=sha(packed),bytes=len(raw))
            doc['announcements']=[receipt];manifest.write_text(json.dumps(doc))
            # Difference 2 exceeds the one-thousand-dollar source tolerance.
            raw=raw.replace(b':901',b':902');packed=gzip.compress(raw,mtime=0);path.write_bytes(packed)
            receipt.update(raw_sha256=sha(raw),gzip_sha256=sha(packed),bytes=len(raw));manifest.write_text(json.dumps(doc))
            events,states=load(data,ASOF)
            self.assertFalse(events)
            self.assertIn('CONFLICT',states['1234']['reason'])

    def test_source_cache_invalidation_includes_manifest_and_linked_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data,_,source,_=self.setup_data(root)
            for name in ['prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
            before=model_source_state(root)
            source.write_bytes(source.read_bytes()+b'changed')
            after=model_source_state(root)
            self.assertIn(FOLDER+'/manifest.json',before)
            self.assertNotEqual(before,after)


class ForecastAdmission(unittest.TestCase):
    def test_new_summary_cannot_restore_previously_removed_volatile_gains(self):
        data,event=fixtures.EarningsForecastIntegration().data()
        primary=data.evidence['primary']['SYNTHETIC_A']
        primary['nonop_prior_fy']={'sensitivity_gap_ex_volatile_k':5}
        primary['nonop_prior_ytd']={'sensitivity_gap_ex_volatile_k':8}
        event['source_kind']=ANNOUNCEMENT_KIND;data.earnings_events={'SYNTHETIC_A':event}
        row=estimate(data,('TEST','SYNTHETIC_A'),fixtures.CAL,fixtures.ASOF,'2027-12-31')
        self.assertEqual(row['base']['nonoperating_k'],7)
        self.assertIn('PRIOR_COMPONENT_BASELINE_HELD',row['nonoperating_bridge']['method'])

    def test_partial_bulk_updates_income_without_promoting_original_or_cash_reviews(self):
        for kind, original in [(SOURCE_KIND,False),(ANNOUNCEMENT_KIND,True)]:
            with self.subTest(kind=kind):
                data,event=fixtures.EarningsForecastIntegration().data()
                event['source_kind']=kind;data.earnings_events={'SYNTHETIC_A':event}
                row=estimate(data,('TEST','SYNTHETIC_A'),fixtures.CAL,fixtures.ASOF,'2027-12-31')
                self.assertEqual(row['financial_period'],'2026-Q3')
                self.assertEqual(row['cashflow_financial_period'],'2026-Q2')
                self.assertEqual(row['original_current_issuer_numeric_checked'],original)
                self.assertEqual(row['base']['nonoperating_k'],20)
                self.assertFalse(row['formal_Aplus'])
                self.assertEqual(row['gates']['original_eight_quarter_statements']['status'],'PENDING')

    def test_zero_nonoperating_sensitivity_keeps_base_and_peer_multiple_unchanged(self):
        data,event=fixtures.EarningsForecastIntegration().data()
        before=estimate(data,('TEST','SYNTHETIC_A'),fixtures.CAL,fixtures.ASOF,'2027-12-31')
        shock=before['nonoperating_bridge']['zero_nonoperating_sensitivity']
        self.assertEqual(shock['nonoperating_k'],0)
        self.assertEqual(shock['pe'],before['base']['pe'])
        self.assertTrue(shock['all_other_inputs_unchanged'])
        self.assertGreater(before['base']['eps'],shock['eps'])
