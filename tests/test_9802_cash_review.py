import copy,datetime as dt,hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from tw_model_v880.cash_review_9802 import STATUS,check_9802_cash_review
from tw_model_v880.data import MarketData,model_source_state
from tw_model_v880.working_capital_original import load_working_capital_watch
from scripts.cash_quality_9802 import build_report,markdown

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
RECEIPT='evidence/v880/working_capital_watch/9802.json'
ASOF='2026-10-25T12:00:00+08:00'


class OriginalCashReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record=json.loads((ROOT/RECEIPT).read_text())
        cls.income=dict(code='9802',market='TWSE',period='2026-Q2',revenue_ytd_k=8933111)
        cls.cash=dict(code='9802',market='TWSE',period='2026-Q2',operating_cashflow_ytd_k=-274010)
        cls.review=check_9802_cash_review(cls.record,ROOT,ASOF,cls.income,cls.cash)
    def check(self,record=None,root=ROOT,asof=ASOF,income=None,cash=None):
        return check_9802_cash_review(record or self.record,root,asof,income or self.income,cash or self.cash)
    def temporary_root(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        for source in self.record['sources']:
            path=root/source['archive_path'];path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/source['archive_path'],path)
        target=root/RECEIPT;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(self.record))
        return root
    def fixture(self):
        row=dict(code='9802',financial_period='2026-Q3',cashflow_financial_period='2026-Q2',formal_Aplus=False,
                 working_capital_original_subcheck=self.review,share_bridge=dict(bonds=[dict(code='98026',currency='TWD',face=999800000,put_date='20261115',snapshot_date='20261023')]))
        return dict(model='V8.10.8',estimate_vintage=ASOF,asof_price_date='2026-10-22',all_model_rows=[row])
    def test_cash_bridge_and_both_h1_cash_totals_reconcile(self):
        r=self.review;self.assertEqual(r['cash_before_working_capital_k'],[926025,1249773])
        self.assertEqual(r['working_capital_cash_change_k'],[-1039160,-1354088])
        self.assertEqual(r['cashflow_signed_k']['ocf'],[-274010,-287575])
        self.assertEqual(r['cashflow_signed_k']['cash_change'][0],-1213226)
        self.assertEqual(r['current_h1']['balances_k']['cash'][0],1151463)
        self.assertFalse(r['formal_cash_and_working_capital_gate_pass']);self.assertEqual(r['formal_Aplus_addition'],0)
    def test_ar_note_brackets_aging_and_inventory_cost_allowances(self):
        r=self.review;self.assertEqual(r['receivables_gross_k'][0],4356879)
        self.assertEqual(r['receivables_allowance_signed_k'][0],-6555)
        self.assertEqual(r['receivables_aging_k']['overdue_91_180'],[8083,581,0])
        self.assertAlmostEqual(r['ar_over_90_days_pct'],.5573026012)
        self.assertEqual(r['inventory_cost_allowance_and_components'][0]['total_cost_allowance_net_k'],[3485579,98480,3387099])
    def test_cycle_uses_actual_half_year_days_and_does_not_claim_observed_collections(self):
        r=self.review;self.assertEqual(r['current_h1']['days_in_h1'],181)
        self.assertAlmostEqual(r['current_h1_cycle_proxy']['inventory_proxy_days'],69.36447855)
        self.assertAlmostEqual(r['prior_h1_cycle_proxy']['inventory_proxy_days'],59.65809107)
        self.assertAlmostEqual(r['current_h1_cycle_proxy']['cash_conversion_cycle_proxy_days'],95.39572569)
        self.assertTrue(r['current_h1_cycle_proxy']['credit_sales_and_purchases_not_separately_verified'])
    def test_unallocated_balance_cashflow_residuals_are_not_forced_to_zero(self):
        self.assertEqual(self.review['balance_change_vs_cashflow_residual_k'],dict(receivables_net=48360,inventory=33594,payables=51208))
        self.assertTrue(self.review['residuals_are_unallocated_not_assumed_all_fx'])
    def test_changed_original_is_not_accepted_from_ledger_numbers(self):
        root=self.temporary_root();(root/self.record['sources'][0]['archive_path']).write_bytes(b'%PDF-tampered')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):self.check(root=root)
    def test_same_day_future_review_not_available_in_historical_cutoff(self):
        before=(dt.datetime.fromisoformat(self.record['reviewed_at'])-dt.timedelta(microseconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'REVIEW_FROM_FUTURE'):self.check(asof=before)
        root=self.temporary_root();results,errors=load_working_capital_watch(root,before,{('TWSE','9802'):{'2026-Q2':self.income}},{('TWSE','9802'):{'2026-Q2':self.cash}})
        self.assertFalse(results);self.assertFalse(errors)
        for day_only in ('2026-10-23',self.record['independently_read_date']):
            results,errors=load_working_capital_watch(root,day_only,{('TWSE','9802'):{'2026-Q2':self.income}},{('TWSE','9802'):{'2026-Q2':self.cash}})
            self.assertFalse(results);self.assertFalse(errors)
    def test_wrong_source_period_path_and_false_certification_reject(self):
        for key,value in [('issuer','8383'),('period','2026-Q3'),('formal_cash_and_working_capital_gate_pass',True),('issuer_historical_filings_PIT_verified',True)]:
            record=copy.deepcopy(self.record);record[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.check(record)
        for key,value in [('source_url','https://example.invalid/cash.pdf'),('archive_path','../cash.pdf')]:
            record=copy.deepcopy(self.record);record['sources'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.check(record)
    def test_cross_source_income_and_cash_period_or_values_must_match(self):
        for income,cash in [(dict(self.income,period='2026-Q3'),self.cash),(dict(self.income,revenue_ytd_k=1),self.cash),
                            (self.income,dict(self.cash,operating_cashflow_ytd_k=1))]:
            with self.subTest(income=income,cash=cash),self.assertRaises(ValueError):self.check(income=income,cash=cash)
    def test_corrupt_pdf_with_matching_new_hash_is_isolated(self):
        root=self.temporary_root();record=copy.deepcopy(self.record);path=root/record['sources'][0]['archive_path'];path.write_bytes(b'%PDF-invalid but hashed')
        record['sources'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();(root/RECEIPT).write_text(json.dumps(record))
        result,errors=load_working_capital_watch(root,ASOF,{('TWSE','9802'):{'2026-Q2':self.income}},{('TWSE','9802'):{'2026-Q2':self.cash}})
        self.assertFalse(result);self.assertEqual(len(errors),1)
    def test_full_put_uses_dated_face_and_never_adds_bank_lines_as_cash(self):
        full=self.fixture();before=copy.deepcopy(full);report=build_report(full);s=report['full_put_sensitivity']
        self.assertEqual(full,before);self.assertAlmostEqual(s['assumed_full_put_cash_k'],1009822.995)
        self.assertAlmostEqual(s['old_reported_cash_less_full_put_k'],141640.005)
        self.assertTrue(s['not_an_actual_current_funding_gap']);self.assertFalse(s['actual_exercise_or_settlement_verified'])
        self.assertFalse(self.review['unused_lines_are_cash']);self.assertFalse(self.review['current_facility_drawability_verified'])
        self.assertIn('122.81',markdown(report));self.assertFalse(report['changes_eps_or_target_price'])
    def test_invalid_or_future_bond_snapshot_does_not_produce_a_cash_stress(self):
        for key,value in [('snapshot_date','20261028'),('snapshot_date','20261399'),('put_date','20271115'),('currency','USD')]:
            full=self.fixture();full['all_model_rows'][0]['share_bridge']['bonds'][0][key]=value
            with self.subTest(key=key,value=value):self.assertIsNone(build_report(full)['full_put_sensitivity'])
    def test_originals_and_ledger_invalidate_cache_and_are_consumed(self):
        root=self.temporary_root()
        for name in ('prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json'):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
        before=model_source_state(root);record=copy.deepcopy(self.record);record['note']='review update';(root/RECEIPT).write_text(json.dumps(record));after=model_source_state(root)
        self.assertNotEqual(before[RECEIPT],after[RECEIPT])
        data=MarketData(ROOT,ASOF);self.assertEqual(data.working_capital_watch['9802']['status'],STATUS)
        paths={r['path'] for r in data.input_receipts};self.assertIn(RECEIPT,paths)
        for source in self.record['sources']:self.assertIn(source['archive_path'],paths)


class CashPeriodAttachment(unittest.TestCase):
    def test_h1_review_survives_q3_income_update_without_changing_valuation(self):
        from tests.test_institutional_controls import EarningsForecastIntegration,CAL,ASOF as MODEL_ASOF
        from tw_model_v880.model import estimate
        data,event=EarningsForecastIntegration().data();data.earnings_events={'SYNTHETIC_A':event}
        before=estimate(data,('TEST','SYNTHETIC_A'),CAL,MODEL_ASOF,'2027-12-31')
        data.working_capital_watch={'SYNTHETIC_A':dict(code='9802',period='2026-Q2',status=STATUS)}
        after=estimate(data,('TEST','SYNTHETIC_A'),CAL,MODEL_ASOF,'2027-12-31')
        self.assertEqual(after['working_capital_original_subcheck']['period'],'2026-Q2')
        self.assertEqual(after['base'],before['base']);self.assertEqual(after['gates']['cash_and_working_capital']['status'],'PENDING')
    def test_q3_cash_flow_does_not_inherit_h1_working_capital_receipt(self):
        from tests.test_tsmc_earnings import CondensedForecastIntegration
        from tests.test_institutional_controls import CAL,ASOF as MODEL_ASOF
        from tw_model_v880.model import estimate
        data,event=CondensedForecastIntegration().data();data.working_capital_watch={'SYNTHETIC_A':dict(code='9802',period='2026-Q2',status=STATUS)}
        row=estimate(data,('TEST','SYNTHETIC_A'),CAL,MODEL_ASOF,'2027-12-31')
        self.assertEqual(row['cashflow_financial_period'],'2026-Q3');self.assertIsNone(row['working_capital_original_subcheck'])

if __name__=='__main__':unittest.main()
