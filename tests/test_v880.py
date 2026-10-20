import copy,unittest
from tw_model_v880.math import previous_periods,quarter_end,standalone,share_scenarios,liquidity,operating_scenario,returns
from tw_model_v880.evidence import certify,GATES
from tw_model_v880.backtest import admission,event_return
from tw_model_v880.calibration import fit_accounting
from tw_model_v880.specialists import segment
from scripts.build_v880_evidence import component
from tw_model_v880.data import ensure_vintage
ASOF='2026-10-18T19:30:00+08:00';PERIOD='2026-Q2';CODE='SYNTHETIC_ONLY'
def certificates():
    return {name:dict(status='PASS',issuer=CODE,financial_period=PERIOD,checked_at='2026-10-17T12:00:00+08:00',available_at='2026-10-17T11:00:00+08:00',
      expires_at='2026-11-15T23:59:59+08:00',method='SYNTHETIC_UNIT_TEST_NOT_REAL_STOCK',stress_verified=True,
      sources=[dict(url='https://example.invalid/synthetic',sha256='a'*64,origin_authenticated=True,available_at='2026-10-16T12:00:00+08:00')]) for name in GATES}
class CertificationTests(unittest.TestCase):
    def test_a_plus_reachable_and_not_hardcoded(self):
        r=certify(CODE,30,5,certificates(),ASOF,PERIOD);self.assertTrue(r['formal_Aplus']);self.assertFalse(r['formal_Aplusplus'])
    def test_a_plusplus_requires_stress_signoff(self):
        gs=certificates();self.assertTrue(certify(CODE,35,9,gs,ASOF,PERIOD)['formal_Aplusplus']);gs['fully_diluted_shares']['stress_verified']=False
        self.assertFalse(certify(CODE,35,9,gs,ASOF,PERIOD)['formal_Aplusplus']);self.assertFalse(certify(CODE,35,-.1,certificates(),ASOF,PERIOD)['formal_Aplusplus'])
    def test_discovery_watch_and_threshold_boundaries(self):
        self.assertEqual(certify(CODE,29.999,1,certificates(),ASOF,PERIOD)['status'],'A_DISCOVERY');self.assertEqual(certify(CODE,24.999,1,certificates(),ASOF,PERIOD)['status'],'WATCH')
    def test_each_unknown_gate_blocks_promotion(self):
        for name in GATES:
            gs=certificates();gs[name]['status']='PENDING';self.assertFalse(certify(CODE,200,60,gs,ASOF,PERIOD)['formal_Aplus'])
    def test_wrong_issuer_period_expiry_and_future_certificate(self):
        for field,value in [('issuer','OTHER'),('financial_period','2026-Q3'),('expires_at','2026-10-17T12:00:00+08:00'),('checked_at','2026-10-19T12:00:00+08:00')]:
            gs=certificates();gs['auditor_scope'][field]=value;self.assertFalse(certify(CODE,100,60,gs,ASOF,PERIOD)['formal_Aplus'])
    def test_future_source_and_unauthenticated_hash_cannot_pass(self):
        for field,value in [('available_at','2026-10-20T12:00:00+08:00'),('origin_authenticated',False),('sha256','x'*64)]:
            gs=certificates();gs['cash_and_working_capital']['sources'][0][field]=value;self.assertFalse(certify(CODE,100,60,gs,ASOF,PERIOD)['formal_Aplus'])
    def test_wrong_issuer_failure_is_not_real_company_failure(self):
        gs=certificates();gs['auditor_scope'].update(status='FAIL',issuer='OTHER');self.assertEqual(certify(CODE,100,60,gs,ASOF,PERIOD)['status'],'CERTIFICATION_PENDING')
    def test_current_valid_failure_separate_from_missing(self):
        gs=certificates();gs['auditor_scope']['status']='FAIL';self.assertEqual(certify(CODE,100,60,gs,ASOF,PERIOD)['status'],'QUALITY_REVIEW_FAILED')
    def test_source_cannot_be_reviewed_before_available(self):
        gs=certificates();gs['auditor_scope']['sources'][0]['available_at']='2026-10-18T10:00:00+08:00';self.assertFalse(certify(CODE,100,60,gs,ASOF,PERIOD)['formal_Aplus'])
    def test_malformed_sources_are_pending_not_exception_or_pass(self):
        for bad in ({"url": "https://example.invalid"}, ["non-dict-source"], [], None):
            gs=certificates()
            gs["auditor_scope"]["sources"]=bad
            result=certify(CODE,100,100,gs,ASOF,PERIOD)
            self.assertFalse(result["formal_Aplus"])
            self.assertIn("auditor_scope",result["gates_pending"])
    def test_malformed_upside_is_unavailable_even_with_passed_gates(self):
        for bad in ("100", float("nan"), True, None):
            result=certify(CODE,bad,100,certificates(),ASOF,PERIOD)
            self.assertEqual(result["status"],"VALUATION_UNAVAILABLE")
            self.assertFalse(result["formal_Aplus"])
        for bad in ("100", float("inf"), True):
            result=certify(CODE,40,bad,certificates(),ASOF,PERIOD)
            self.assertFalse(result["formal_Aplusplus"])

class AccountingTests(unittest.TestCase):
    def test_future_component_receipt_blocks_backdated_research(self):
        e=dict(snapshot_available_at='2026-10-17T00:00:00+08:00',last_public_refresh=dict(at='2026-10-18T09:00:00+08:00'),
          official_current_bulk=dict(TWSE_income=dict(fetched_at='2026-10-18T09:01:00+08:00')))
        with self.assertRaisesRegex(ValueError,'COMPONENT_VINTAGE'):ensure_vintage(e,'2026-10-18T09:00:30+08:00')
        ensure_vintage(e,'2026-10-18T09:02:00+08:00')
    def test_dynamic_eight_quarters_roll_year_boundary(self):
        self.assertEqual(previous_periods('2027-Q1'),['2025-Q2','2025-Q3','2025-Q4','2026-Q1','2026-Q2','2026-Q3','2026-Q4','2027-Q1']);self.assertEqual(str(quarter_end('2024Q1')),'2024-03-31')
    def test_missing_ytd_baseline_does_not_become_zero(self):
        self.assertIsNone(standalone(100,None,3));self.assertEqual(standalone(100,40,3),60)
    def test_dilution_does_not_double_count_weighted_cb(self):
        r=share_scenarios(100,[dict(code='CB',face=200,currency='TWD',conversion_price=10,current_terms_verified=True)],115);self.assertEqual(r['base_shares'],120)
    def test_fx_cb_without_exchange_terms_blocks_point_count(self):
        r=share_scenarios(100,[dict(code='FX',face=200,currency='USD',conversion_price=10,current_terms_verified=False)]);self.assertTrue(r['missing_legal_conversion_inputs'])
    def test_currency_fx_and_share_units(self):
        r=share_scenarios(100,[dict(code='FX',face=200,currency='USD',fx_twd=30,conversion_price=10,current_terms_verified=True)]);self.assertEqual(r['base_shares'],700)
        self.assertEqual(operating_scenario(1000,.3,.1,0,.2,1,10000,10)['eps'],16)
    def test_negative_ocf_not_automatic_failure_and_prepaid_separate(self):
        r=liquidity(1000,-100,-200,None);self.assertEqual(r['fcf_after_ppe_k'],-300);self.assertFalse(r['negative_ocf_automatic_failure']);self.assertIsNone(r['cash_after_separately_reported_prepaid_k'])
        self.assertEqual(liquidity(1000,294969,-260039,-76067)['cash_after_separately_reported_prepaid_k'],-41137)
    def test_ppe_purchase_sign_guard(self):
        with self.assertRaises(ValueError):liquidity(1000,100,30,None)
    def test_prior_ex_date_not_earned_and_unknown_dividends_not_zero(self):
        self.assertIsNone(returns(120,100,None,'2026-10-18','2027-12-31')['total_return_pct']);self.assertAlmostEqual(returns(120,100,[dict(ex_date='2026-09-10',per_share=3.1)],'2026-10-18','2027-12-31')['total_return_pct'],20)
    def test_impairment_is_retained_when_zeroing_volatile_sensitivity(self):
        facts=[dict(account_code=c,label=l,value=v*1000,unit='TWD',context='C') for c,l,v in [('7900','稅前淨利',100),('6900','營業利益',80),('N7270','減損迴轉利益（損失）',-30),('N7230','外幣兌換利益（損失）',10)]]
        r=component(dict(facts=facts),'C');self.assertEqual(r['sensitivity_gap_ex_volatile_k'],10);self.assertTrue(r['impairment_retained'])
class SpecialistTests(unittest.TestCase):
    def test_contract_cash_is_not_backlog(self):
        with self.assertRaises(ValueError):segment(dict(kind='project',projects=[dict(contract_total_k=100,cash_collected_k=20,recognition_fraction=.5,project_gross_margin=.3)],opex_fixed_k=1,opex_rate=.1))
    def test_project_recognition_not_total_sales(self):
        r=segment(dict(kind='project',projects=[dict(remaining_contract_revenue_k=100,recognition_fraction=.4,project_gross_margin=.3)],opex_fixed_k=1,opex_rate=.1));self.assertEqual(r['revenue_k'],40);self.assertEqual(r['operating_profit_k'],7)
    def test_distributor_uses_unit_spread(self):
        self.assertEqual(segment(dict(kind='distributor',units_sold=1000,asp_twd=100,unit_cost_twd=95,inventory_provision_k=2,opex_fixed_k=1,opex_rate=.01))['operating_profit_k'],1)
    def test_capacity_utilization_above_one_rejected(self):
        with self.assertRaises(ValueError):segment(dict(kind='manufacturing',capacity_units=10,utilization=1.1))
class BacktestTests(unittest.TestCase):
    def snap(self):return dict(universe_membership_verified=True,model_created_at='2026-01-01T00:00:00+08:00',estimate_created_at='2026-10-16T16:00:00+08:00',inputs=[dict(sha256='a'*64,published_at='2026-08-10T12:00:00+08:00',revision_at='2026-08-10T12:00:00+08:00')],cost_policy=dict(buy_fee_rate=.001,sell_fee_rate=.001,sell_tax_rate=.002))
    def test_later_estimate_cannot_trade_earlier_close(self):self.assertFalse(admission(self.snap(),'2026-10-16T13:30:00+08:00')['admitted'])
    def test_future_revision_blocks_backfill(self):
        s=self.snap();s['inputs'][0]['revision_at']='2026-10-20T12:00:00+08:00';self.assertIn('RESTATED_DATA_FROM_FUTURE',admission(s,'2026-10-16T17:00:00+08:00')['reasons'])
    def test_unknown_universe_and_costs_block(self):
        s=self.snap();s['universe_membership_verified']=False;s['cost_policy']=None;self.assertFalse(admission(s,'2026-10-16T17:00:00+08:00')['admitted'])
    def test_next_session_weekend_split_and_dividend(self):
        bars=[dict(open_at='2026-10-16T09:00:00+08:00',close_at='2026-10-16T13:30:00+08:00',open=90,close=100),dict(open_at='2026-10-19T09:00:00+08:00',close_at='2026-10-19T13:30:00+08:00',open=100,close=102),dict(open_at='2026-10-20T09:00:00+08:00',close_at='2026-10-20T13:30:00+08:00',open=51,close=55)]
        acts=[dict(type='split',effective_at='2026-10-20T00:00:00+08:00',ratio=2),dict(type='cash_dividend',effective_at='2026-10-20T08:00:00+08:00',per_share=1)]
        r=event_return(self.snap(),bars,'2026-10-16T17:00:00+08:00','2026-10-20T14:00:00+08:00',acts)
        self.assertEqual(r['entry_at'],'2026-10-19T09:00:00+08:00');self.assertEqual(r['ending_shares'],2);self.assertEqual(r['dividend_cash'],2);self.assertAlmostEqual(r['total_return_pct'],((110*.997+2)/(100*1.001)-1)*100)
class CalibrationTests(unittest.TestCase):
    def data(self):
        h={}
        for i in range(60):
            s=100+i;h[('TEST',str(i))]={}
            for p,r,gm,co in [('2024-Q3',s*.75,.2,.1),('2024-Q4',s,.2,.1),('2025-Q3',s*.825,.22,.105),('2025-Q4',s*1.1,.215,.104),('2025-Q1',s*.25,.21,.1),('2025-Q2',s*.5,.21,.1),('2026-Q1',s*.3,.24,.11),('2026-Q2',s*.6,.23,.11)]:h[('TEST',str(i))][p]=dict(revenue_ytd_k=r,gross_profit_ytd_k=r*gm,operating_profit_ytd_k=r*(gm-co))
        return h
    def test_holdout_cannot_change_fitted_coefficients(self):
        h=self.data();a=fit_accounting(h,'2026-Q2')
        for rows in h.values():rows['2026-Q2']['revenue_ytd_k']*=10
        b=fit_accounting(h,'2026-Q2')
        for k in ['revenue_persistence','margin_persistence','cost_persistence']:self.assertEqual(a[k],b[k])
        self.assertNotEqual(a['holdout_metrics'],b['holdout_metrics']);self.assertFalse(a['pit_return_backtest_passed'])
if __name__=='__main__':unittest.main()
