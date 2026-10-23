import copy,gzip,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from tw_model_v880.capital import apply_capital_terms,parse_twd_reset
from tw_model_v880.footwear_review import original_facts,build_review,markdown

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
ASOF='2026-10-25T00:00:00+08:00'


class ResetTermsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'evidence/v880/capital_terms';self.folder.mkdir(parents=True)
        sources=[];terms=[]
        for bond,ordinal,old,price in [('68901','一',246.4,237.5),('68902','二',245.2,236.3)]:
            raw=(f'<html><script>本公司自114年1月1日</script><p>(6890) 來億-KY</p><p>本公司自115年7月19日起，'
                 f'本公司國內第{ordinal}次無擔保轉換公司債之轉換價格由每股新台幣{old}元調整為新台幣{price}元</p>推薦新聞</html>').encode()
            path=self.folder/f'{bond}.html.gz';path.write_bytes(gzip.compress(raw,mtime=0))
            sources.append(dict(id=bond,path=path.relative_to(self.root).as_posix(),sha256=hashlib.sha256(raw).hexdigest(),
                available_at='2026-10-23T10:00:00+00:00',fetched_at='2026-10-23T10:00:00+00:00',source_record_type='ISSUER_RESET_ANNOUNCEMENT_HTML_REPUBLICATION'))
            terms.append(dict(code=bond,currency='TWD',conversion_price=price,effective_at='2026-07-19T00:00:00+08:00',price_basis='DATED_RESET_RESEARCH_ONLY',source_ids=[bond]))
        self.book=dict(code='6890',checked_at='2026-10-23T10:00:00+00:00',sources=sources,bonds=terms)
        self.data=SimpleNamespace(root=self.root,path=lambda p:self.root/p,receipt=lambda *args:None,errors=[],
            evidence={'bonds':{'6890':[dict(code='68901',currency='TWD',face=4327400000,conversion_price=246.4),dict(code='68902',currency='TWD',face=451900000,conversion_price=245.2)]}})
        self.before=copy.deepcopy(self.data.evidence)
    def apply(self):
        (self.folder/'6890.json').write_text(json.dumps(self.book));apply_capital_terms(self.data,ASOF)
    def test_valid_reset_preserves_outstanding_face_and_no_certification(self):
        self.apply();self.assertFalse(self.data.errors)
        for bond,price,old in zip(self.data.evidence['bonds']['6890'],[237.5,236.3],self.before['bonds']['6890']):
            self.assertEqual(bond['conversion_price'],price);self.assertEqual(bond['face'],old['face']);self.assertFalse(bond['current_terms_verified'])
    def test_second_invalid_price_is_atomic(self):
        self.book['bonds'][1]['conversion_price']=999;self.apply();self.assertEqual(self.data.evidence,self.before);self.assertTrue(self.data.errors)
    def test_hash_and_future_capture_fail_closed(self):
        for field,value in [('sha256','0'*64),('fetched_at','2027-01-01T00:00:00+00:00')]:
            with self.subTest(field=field):
                original=self.book['sources'][0][field];self.book['sources'][0][field]=value;self.apply()
                self.assertEqual(self.data.evidence,self.before);self.book['sources'][0][field]=original
    def test_no_rollback_of_later_known_terms(self):
        bond=self.data.evidence['bonds']['6890'][0];bond.update(conversion_price=200,terms_effective_at='2026-09-01T00:00:00+08:00')
        self.apply();self.assertEqual(self.data.evidence['bonds']['6890'][0]['conversion_price'],200)
    def test_wrong_issuer_and_effective_date_fail(self):
        raw=gzip.decompress((self.folder/'68901.html.gz').read_bytes())
        with self.assertRaises(ValueError):parse_twd_reset(raw.replace(b'6890',b'6899'),'6890','68901')
        self.book['bonds'][1]['effective_at']='2026-07-20T00:00:00+08:00';self.apply();self.assertEqual(self.data.evidence,self.before)
    def test_currency_and_duplicate_terms_fail_atomically(self):
        self.data.evidence['bonds']['6890'][1]['currency']='USD';before=copy.deepcopy(self.data.evidence)
        self.apply();self.assertEqual(self.data.evidence,before)
        self.data.evidence=copy.deepcopy(self.before);self.book['bonds'].append(copy.deepcopy(self.book['bonds'][0]));self.apply();self.assertEqual(self.data.evidence,self.before)


class OriginalReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=json.loads((ROOT/'evidence/v880/footwear/originals.json').read_text())['sources']
        cls.config=json.loads((ROOT/'config/footwear_research_v1.json').read_text())
    def facts(self,code):return original_facts(ROOT,code,self.sources[code],ASOF)
    def fixture(self):
        facts=self.facts('6890')
        rows=[]
        for code,price,shares in [('6890',144.5,270429681.07111835),('9904',26.35,2946787213)]:
            rows.append(dict(code=code,price_date='2026-10-22',reference_close=price,base={'eps':9},
                point_valuation_available=True,share_bridge={'base_shares':shares,'fully_diluted_shares_certified':False},
                formal_Aplus=False,formal_Aplusplus=False,_official_current_values=facts))
        full=dict(model='V8.10.6',estimate_vintage=ASOF,asof_price_date='2026-10-22',financial_last_quarter='2026-Q2',revenue_month='2026-09',target_date='2027-12-31',all_model_rows=rows)
        config=copy.deepcopy(self.config);config['companies']=[c for c in config['companies'] if c['code'] in ('6890','9904')]
        return full,config
    def test_lai_h1_columns_cash_and_normalization(self):
        f=self.facts('6890');self.assertEqual(f['revenue_k'],17901059);self.assertEqual(f['parent_net_income_k'],1130512)
        self.assertEqual(f['operating_cashflow_k'],211579);self.assertEqual(f['cb_interest_k'],51301)
        self.assertEqual(f['disposal_gain_k'],29);self.assertEqual(f['normalized_annual_nonoperating_full_conversion_k'],71034)
    def test_pouchen_components_reconcile_without_double_count(self):
        f=self.facts('9904');self.assertEqual(f['parent_equity_k'],187016299);self.assertEqual(f['yue_yuen_attributable_equity_k'],71011177)
        self.assertEqual(f['ruen_chen_direct_carrying_k'],93767632);self.assertEqual(f['residual_parent_equity_k'],22237490)
    def test_tampered_original_is_blocked(self):
        source=dict(self.sources['6890'],sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):original_facts(ROOT,'6890',source,ASOF)
    def test_conditional_values_do_not_grant_formal_quality(self):
        full,config=self.fixture();before=copy.deepcopy(full);report=build_review(ROOT,full,config)
        self.assertEqual(full,before);self.assertFalse(report['grants_quality_certification']);self.assertFalse(report['replaces_production_forecasts'])
        by_code={r['code']:r for r in report['companies']}
        self.assertAlmostEqual(by_code['6890']['research_cases']['Base']['eps'],10.3431935357,places=7)
        self.assertAlmostEqual(by_code['9904']['research_cases']['Base']['target_price'],33.2415069,places=6)
        for row in by_code.values():self.assertFalse(row['formal_Aplus']);self.assertFalse(row['all_quality_gates_granted_by_this_review'])
    def test_new_period_and_source_mismatch_block_prices(self):
        for key,value in [('revenue_month','2026-10'),('financial_last_quarter','2026-Q3')]:
            full,config=self.fixture();full[key]=value
            self.assertTrue(all(r['research_cases'] is None for r in build_review(ROOT,full,config)['companies']))
        full,config=self.fixture();full['all_model_rows'][0]['_official_current_values']['revenue_k']=1
        row=build_review(ROOT,full,config)['companies'][0];self.assertEqual(row['status'],'INPUT_BLOCKED');self.assertIsNone(row['research_cases'])

if __name__=='__main__':unittest.main()
