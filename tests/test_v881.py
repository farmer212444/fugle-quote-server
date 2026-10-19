import contextlib,copy,datetime as dt,hashlib,io,json,pathlib,tempfile,unittest
from unittest.mock import patch
from test_integration_v880 import FakeData,CAL,ASOF
import test_v880 as prior_tests
from scripts.tw_v880_run import run,tracked_universe
from scripts.refresh_v881_capital import refresh_capital,fetch_capital
from tw_model_v880.model import estimate
from tw_model_v880.math import share_scenarios
from tw_model_v880.capital import apply_capital_terms
from tw_model_v880.calibration import fit_accounting

class CoverageRegressionTests(unittest.TestCase):
    def test_nonlegacy_official_issuer_can_rank_but_is_not_certified(self):
        d=FakeData();primary=d.evidence['primary'].pop('SYNTHETIC_A')
        d.detailed_values=lambda key,period:primary['values'] if period==d.period else primary['prior_full_year']
        r=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertTrue(r['rankable']);self.assertFalse(r['original_current_issuer_numeric_checked']);self.assertFalse(r['formal_Aplus'])
        self.assertIn('UNVERIFIED_HISTORICAL_DETAIL',r['source_tier'])
    def test_price_only_master_only_and_filtered_issuers_remain_in_ledger(self):
        d=FakeData();d.prices[('TEST','PRICE_ONLY')]=dict(close=10,volume_shares=10)
        d.evidence['master']['MASTER_ONLY']=dict(market='TEST',name='MASTER_ONLY',issued_shares=100000)
        d.prices[('TEST','SYNTHETIC_A')]['volume_shares']=1
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.tw_v880_run.MarketData',return_value=d),patch('scripts.tw_v880_run.fit_accounting',return_value=CAL),contextlib.redirect_stdout(io.StringIO()):
            r=run(tmp,ASOF,'2027-12-31',tmp)
        by_code={x['code']:x for x in r['all_model_rows']}
        self.assertEqual(len(by_code),4);self.assertTrue(r['universe_accounted_for'])
        self.assertEqual(by_code['SYNTHETIC_A']['status'],'TURNOVER_FILTER_BELOW_12M_TWD')
        self.assertEqual(by_code['MASTER_ONLY']['status'],'CURRENT_FINANCIAL_STATEMENT_MISSING')
        self.assertEqual(by_code['PRICE_ONLY']['status'],'CURRENT_FINANCIAL_STATEMENT_MISSING')
        self.assertEqual(r['top10_market_research'][0]['code'],'SYNTHETIC_B')
    def test_starred_name_with_actual_shares_is_not_blanket_excluded(self):
        d=FakeData();d.history[('TEST','SYNTHETIC_A')][d.period]['name']='SYNTHETIC*'
        self.assertTrue(estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')['rankable'])

class CapitalRegressionTests(unittest.TestCase):
    def test_distinct_private_issuer_placeholder_bond_codes_do_not_reject_feed(self):
        row=dict(Date=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d'),IssuerCode='12345678',BondCode='無',OutstandingAmount='100',IssueDate='20250101',MaturityDate='20300101',Currency='1')
        response=unittest.mock.MagicMock();response.__enter__.return_value.read.return_value=json.dumps([row,{**row,'IssuerCode':'87654321'},{**row,'IssuerCode':'99999999','BondCode':''}]).encode()
        with patch('scripts.refresh_v881_capital.urllib.request.urlopen',return_value=response):
            result=fetch_capital('bond_5','https://example.invalid/official')
        self.assertEqual(len(result[2]),3)
    def test_malformed_or_nonfinite_official_feed_is_rejected_before_replacement(self):
        row=dict(Date=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d'),IssuerCode='1234',BondCode='12341',OutstandingAmount='100',IssueDate='20250101',MaturityDate='20300101',Currency='1')
        for change in [dict(OutstandingAmount='NaN'),dict(IssueDate='broken'),dict(Currency='unknown'),dict(IssuerCode='')]:
            with self.subTest(change=change):
                response=unittest.mock.MagicMock();response.__enter__.return_value.read.return_value=json.dumps([{**row,**change}]).encode()
                with patch('scripts.refresh_v881_capital.urllib.request.urlopen',return_value=response),self.assertRaises((ValueError,KeyError)):
                    fetch_capital('bond_5','https://example.invalid/official')
    def fixture(self,root):
        folder=root/'evidence/v880/capital_terms';folder.mkdir(parents=True)
        rec=dict(facts=[dict(issuer='1234',bond='XS1',fixed_fx_twd_per_usd=31.5),dict(issuer='1234',bond='XS1',conversion_price_twd=100)])
        b=json.dumps(rec).encode();source=root/'facts.json';source.write_bytes(b)
        stamp='2026-10-18T10:00:00+00:00'
        book=dict(code='1234',checked_at=stamp,sources=[dict(id='legal',path='facts.json',sha256=hashlib.sha256(b).hexdigest(),available_at=stamp,fetched_at=stamp,
          source_record_type='NUMERIC_EXTRACTION_AND_CAPTURE_RECEIPT_NOT_ORIGINAL_DOCUMENT_BYTES')],
          bonds=[dict(code='XS1',currency='USD',fixed_fx_twd=31.5,conversion_price=100,effective_at=stamp,price_basis='DATED_RESET',source_ids=['legal'])])
        (folder/'1234.json').write_text(json.dumps(book))
        class Data:
            def path(self,s):
                p=(self.root/s).resolve()
                if not p.is_relative_to(self.root):raise ValueError('OUTSIDE')
                return p
            def receipt(self,*a):pass
        d=Data();d.root=root;d.errors=[];d.evidence=dict(bonds={'1234':[dict(code='XS1',face=1000000,currency='FOREIGN_CURRENCY_2',conversion_price=100,current_terms_verified=False)]})
        return d,book,folder/'1234.json'
    def test_dated_fixed_fx_uses_outstanding_face_and_stays_uncertified(self):
        with tempfile.TemporaryDirectory() as tmp:
            d,book,path=self.fixture(pathlib.Path(tmp));apply_capital_terms(d,ASOF)
            r=share_scenarios(1000000,d.evidence['bonds']['1234'])
            self.assertEqual(d.errors,[]);self.assertEqual(r['cb_additional_shares'],315000)
            self.assertEqual(r['base_shares'],1315000);self.assertFalse(r['fully_diluted_shares_certified']);self.assertEqual(r['unresolved_terms'],['XS1'])
            self.assertGreater(r['conversion_price_down_10pct_full_conversion_shares'],r['base_shares'])
    def test_foreign_same_currency_price_needs_no_fx_and_unknown_units_block(self):
        b=dict(code='XS',face=100000,currency='USD',conversion_price=20,conversion_price_currency='USD',current_terms_verified=False)
        self.assertEqual(share_scenarios(10000,[b])['cb_additional_shares'],5000)
        b['conversion_price_currency']='EUR';self.assertEqual(share_scenarios(10000,[b])['missing_legal_conversion_inputs'],['XS'])
    def test_changed_source_hash_keeps_whole_issuer_unapplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            d,book,path=self.fixture(pathlib.Path(tmp));(d.root/'facts.json').write_text('{}');before=copy.deepcopy(d.evidence)
            apply_capital_terms(d,ASOF);self.assertEqual(d.evidence,before);self.assertIn('HASH_MISMATCH',d.errors[0]['error'])
    def test_wrong_issuer_numeric_record_cannot_supply_legal_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d,book,path=self.fixture(pathlib.Path(tmp));raw=json.loads((d.root/'facts.json').read_text());raw['facts'][0]['issuer']='9999'
            b=json.dumps(raw).encode();(d.root/'facts.json').write_bytes(b);book['sources'][0]['sha256']=hashlib.sha256(b).hexdigest();path.write_text(json.dumps(book))
            apply_capital_terms(d,ASOF);self.assertTrue(d.errors);self.assertNotIn('fx_twd',d.evidence['bonds']['1234'][0])
    def test_future_review_and_future_source_are_rejected_separately(self):
        for field in ['checked_at','fetched_at']:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp:
                d,book,path=self.fixture(pathlib.Path(tmp));target=book if field=='checked_at' else book['sources'][0];target[field]='2026-10-19T10:00:00+00:00';path.write_text(json.dumps(book))
                apply_capital_terms(d,ASOF);self.assertTrue(d.errors);self.assertNotIn('fx_twd',d.evidence['bonds']['1234'][0])
    def test_one_official_capital_source_failure_does_not_erase_other_debt(self):
        e=dict(master={'1234':dict(market='TEST',issued_shares=100000)},bonds={'1234':[dict(code='XS1',face=100,currency='FOREIGN_CURRENCY_2',conversion_price=100)]})
        def fetch(name,url):
            if name.endswith('master') or name=='bond_6':raise OSError('isolated source outage')
            rows=[dict(Date='20261018',IssuerCode='')]
            if name=='bond_5':rows=[dict(Date='20261018',IssuerCode='1234',BondCode='12341',OutstandingAmount='500',IssueDate='20250101',MaturityDate='20300101',Currency='1',**{'Conversion/ExchangePriceAtIssuance':'50'})]
            raw=json.dumps(rows).encode();return name,raw,rows,dict(date='2026-10-18',sha256=hashlib.sha256(raw).hexdigest(),fetched_at='2026-10-18T10:00:00+00:00')
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.refresh_v881_capital.fetch_capital',side_effect=fetch):status=refresh_capital(e,pathlib.Path(tmp))
        self.assertEqual({b['code'] for b in e['bonds']['1234']},{'XS1','12341'});self.assertEqual(len(status['failed_sources']),3)

class GrowthHorizonRegressionTests(unittest.TestCase):
    def test_known_prefix_is_preserved_in_heldout_next_quarter_forecast(self):
        # Every company's Q1 grows 20%, but Q2 returns to its prior-year level.
        # Evaluating an entire H1 growth factor would incorrectly grow known Q1
        # again; the heldout forecast must keep the observed prefix untouched.
        h=prior_tests.CalibrationTests().data()
        for rs in h.values():
            rs['2026-Q2']['revenue_ytd_k']=rs['2026-Q1']['revenue_ytd_k']+rs['2025-Q2']['revenue_ytd_k']-rs['2025-Q1']['revenue_ytd_k']
        r=fit_accounting(h,'2026-Q2')
        self.assertLess(r['holdout_known_prefix_zero_growth_baseline']['median_absolute_pct_error'],1e-10)
        self.assertTrue(r['annual_forward_growth_is_extrapolation_not_validated']);self.assertFalse(r['pit_return_backtest_passed'])
    def test_nonpositive_restated_remaining_quarter_is_excluded_from_fit(self):
        h=prior_tests.CalibrationTests().data();rs=h[('TEST','0')];rs['2025-Q4']['revenue_ytd_k']=rs['2025-Q3']['revenue_ytd_k']-1
        r=fit_accounting(h,'2026-Q2');self.assertEqual(r['train_count'],59)

if __name__=='__main__':unittest.main()
