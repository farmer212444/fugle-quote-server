import contextlib,datetime as dt,gzip,io,json,pathlib,tempfile,unittest
from unittest.mock import patch
from tw_model_v880.model import estimate
from tw_model_v880.math import previous_periods
from scripts.tw_v880_run import run,ordered_recovery_watch,resolve_asof,public_row
from tw_model_v880.data import ensure_vintage
ASOF='2026-10-18T19:30:00+08:00';CAL=dict(train_count=60,train_target='2025-Q4',revenue_persistence=.5,margin_persistence=.5,cost_persistence=.5)
class FakeData:
    def __init__(self,*a):
        self.period='2026-Q2';self.price_date='2026-10-16';self.revenue_month='2026-09';self.errors=[];self.required_periods=previous_periods(self.period)
        self.prices={};self.history={};self.revenue={};self.cash={};self.annual_monthly={}
        self.evidence=dict(master={},primary={},primary_cash_eight_quarters={},bonds={},pe_history={},peers={'X':[dict(code=str(i),pe=12) for i in range(8)]},certificates={})
        for code in ['SYNTHETIC_A','SYNTHETIC_B']:
            key=('TEST',code);rows={}
            for y in range(2024,2027):
                for q in range(1,5):
                    r=1000*q/4*(1.2 if y==2026 else 1);rows[f'{y}-Q{q}']=dict(code=code,name=code,revenue_ytd_k=r,gross_profit_ytd_k=.2*r,operating_profit_ytd_k=.1*r,basic_eps_ytd=123)
            self.history[key]=rows;self.prices[key]=dict(close=10,volume_shares=2000000);self.revenue[code]=dict(industry='SYNTHETIC_MANUFACTURING',monthly_yoy_pct=10,ytd_yoy_pct=5.55,ytd_revenue_k=950,last_year_ytd_revenue_k=900)
            self.evidence['master'][code]=dict(issued_shares=100000,industry_code='X');self.evidence['pe_history'][code]=[dict(pe=12) for _ in range(12)]
            no=dict(sensitivity_gap_ex_volatile_k=10,reported_gap_k=10)
            self.evidence['primary'][code]=dict(values=dict(revenue_k=600,gross_profit_k=120,operating_profit_k=60,pretax_profit_k=70,net_income_k=56,parent_net_income_k=56,ocf_k=-10,ppe_cash_flow_signed_k=-5,cash_k=100),
              prior_full_year=dict(revenue_k=1000,gross_profit_k=200,operating_profit_k=100,pretax_profit_k=120),nonop_current=no,nonop_prior_ytd=no,nonop_prior_fy=dict(sensitivity_gap_ex_volatile_k=20),qualified_review=True,equipment_prepaid_signed_k=None)
    def primary(self,c):return self.evidence['primary'].get(c)
    def detailed_values(self,*a):return None
class IntegrationTests(unittest.TestCase):
    def test_same_second_fresh_source_is_not_misclassified_as_future(self):
        now=dt.datetime.fromisoformat('2026-10-18T21:45:20.780000+08:00')
        e=dict(snapshot_available_at='2026-10-18T11:29:14+00:00',official_current_bulk=dict(TPEX_balance=dict(fetched_at='2026-10-18T13:45:20.410000+00:00')))
        for raw in [None,'2026-10-18']:ensure_vintage(e,resolve_asof(raw,now))
        with self.assertRaisesRegex(ValueError,'COMPONENT_VINTAGE'):ensure_vintage(e,'2026-10-18T21:45:20+08:00')
    def test_explicit_cutoff_and_future_microsecond_stay_strict(self):
        now=dt.datetime.fromisoformat('2026-10-18T21:45:20.780000+08:00')
        cutoff=resolve_asof('2026-10-18T21:45:20.400000+08:00',now)
        e=dict(snapshot_available_at='2026-10-18T11:29:14+00:00',official_current_bulk=dict(TPEX_balance=dict(fetched_at='2026-10-18T13:45:20.400001+00:00')))
        with self.assertRaisesRegex(ValueError,'COMPONENT_VINTAGE'):ensure_vintage(e,cutoff)
        with self.assertRaisesRegex(ValueError,'FUTURE_ESTIMATE'):resolve_asof('2026-10-18T21:45:20.780001+08:00',now)
    def test_date_cutoff_rejects_future_day_and_includes_past_day_end(self):
        now=dt.datetime.fromisoformat('2026-10-18T21:45:20.780000+08:00')
        self.assertEqual(resolve_asof('2026-10-17',now),'2026-10-17T23:59:59.999999+08:00')
        with self.assertRaisesRegex(ValueError,'FUTURE_ESTIMATE'):resolve_asof('2026-10-19',now)
    def test_public_recovery_watch_does_not_hide_late_code_primary_issuer(self):
        rows=[dict(code=f'{i:04}',source_tier='OFFICIAL_CURRENT_BATCH_WITH_UNVERIFIED_HISTORICAL_DETAIL',early_recovery_watch=True) for i in range(35)]
        rows.append(dict(code='9802',source_tier='ORIGINAL_CURRENT_ISSUER_NUMERICS',early_recovery_watch=True))
        self.assertIn('9802',[r['code'] for r in ordered_recovery_watch(rows)[:30]])
        self.assertEqual(len(ordered_recovery_watch(rows)),36)
    def test_watch_priority_preserves_values_ratings_and_nonwatch_exclusion(self):
        rows=[dict(code='9802',source_tier='ORIGINAL_CURRENT_ISSUER_NUMERICS',early_recovery_watch=True,base=dict(target_price=55.06),formal_Aplus=False),
              dict(code='0001',early_recovery_watch=False,formal_Aplus=True)]
        out=ordered_recovery_watch(rows)
        self.assertEqual([r['code'] for r in out],['9802']);self.assertEqual(out[0]['base']['target_price'],55.06);self.assertFalse(out[0]['formal_Aplus'])
    def test_one_million_research_gate_and_separate_tradability_gate(self):
        d=FakeData();price=d.prices[('TEST','SYNTHETIC_A')]
        price['volume_shares']=100000 # NT$10 x 100k = NT$1m exactly
        at_floor=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertTrue(at_floor['rankable'])
        self.assertEqual(at_floor['single_day_turnover_ntd'],1000000)
        self.assertEqual(at_floor['liquidity_research_band'],'RESEARCH_1M_TO_12M_PENDING_EXECUTION')
        self.assertEqual(at_floor['gates']['tradability']['status'],'PENDING')
        self.assertFalse(at_floor['formal_Aplus'])
        price['volume_shares']=99999
        under_floor=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertFalse(under_floor['rankable'])
        self.assertEqual(under_floor['status'],'TURNOVER_FILTER_BELOW_1M_TWD')
        price['volume_shares']=1200000
        above_review=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertTrue(above_review['rankable'])
        self.assertEqual(above_review['liquidity_research_band'],'RESEARCH_AT_LEAST_12M_PENDING_EVIDENCE')
    def test_low_turnover_cannot_reuse_generic_tradability_pass(self):
        d=FakeData();d.prices[('TEST','SYNTHETIC_A')]['volume_shares']=150000
        d.evidence['certificates']['SYNTHETIC_A']={'tradability':dict(status='PASS')}
        a=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertTrue(a['rankable'])
        self.assertEqual(a['gates']['tradability']['status'],'PENDING')
        self.assertIn('EXIT_CAPACITY_REVIEW',a['gates']['tradability']['reason'])
        self.assertFalse(a['formal_Aplus'])
    def test_reported_eps_edit_does_not_change_operating_forecast(self):
        d=FakeData();a=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        for row in d.history[('TEST','SYNTHETIC_A')].values():row['basic_eps_ytd']*=20
        self.assertEqual(a['base']['eps'],estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')['base']['eps'])
    def test_share_doubling_halves_scenario_eps(self):
        d=FakeData();a=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31');d.evidence['master']['SYNTHETIC_A']['issued_shares']*=2
        self.assertAlmostEqual(a['base']['eps']/2,estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')['base']['eps'])
    def test_project_without_contract_bridge_cannot_enter_top_ranking(self):
        d=FakeData();d.revenue['SYNTHETIC_A']['industry']='建材營造';a=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31');self.assertFalse(a['rankable']);self.assertIsNone(a['research_2027_price_scenario']);self.assertEqual(a['base_scenario_role'],'DIAGNOSTIC_ONLY_NOT_ADMISSIBLE_BASE')
    def test_qualified_scope_and_negative_ocf_are_pending_not_false_failure(self):
        a=estimate(FakeData(),('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31');self.assertEqual(a['certification']['status'],'CERTIFICATION_PENDING');self.assertIn('auditor_scope',a['certification']['gates_pending']);self.assertEqual(a['certification']['gates_failed'],[])
    def test_engineering_in_other_industry_requires_contract_bridge(self):
        d=FakeData();d.evidence['primary']['SYNTHETIC_A']['business_description']='無塵室及廠務工程之設計與建造';a=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31');self.assertFalse(a['rankable']);self.assertTrue(a['business_profile']['engineering_business_observed'])
    def test_january_rollover_uses_december_revenue_not_old_fiscal_year(self):
        d=FakeData();d.period='2026-Q3';d.revenue_month='2027-01';d.required_periods=previous_periods(d.period);d.evidence['primary']['SYNTHETIC_A']['values'].update(revenue_k=900,gross_profit_k=180,operating_profit_k=90)
        d.revenue['SYNTHETIC_A'].update(ytd_revenue_k=110,last_year_ytd_revenue_k=100);d.annual_monthly[('SYNTHETIC_A',2026)]=1200
        a=estimate(d,('TEST','SYNTHETIC_A'),CAL,'2027-02-12T12:00:00+08:00','2028-12-31');self.assertEqual(a['revenue_bridge']['prior_year_remaining_k'],1100);self.assertIsNone(a['research_2027_price_scenario']);self.assertIsNotNone(a['research_target_price_scenario'])
        d.annual_monthly={};self.assertEqual(estimate(d,('TEST','SYNTHETIC_A'),CAL,'2027-02-12T12:00:00+08:00','2028-12-31')['status'],'YEAR_ROLLOVER_DECEMBER_REVENUE_REQUIRED')
    def test_fourth_quarter_uses_current_fiscal_full_year(self):
        d=FakeData();d.period='2026-Q4';d.revenue_month='2027-03';d.required_periods=previous_periods(d.period);d.evidence['primary']['SYNTHETIC_A']['values'].update(revenue_k=1200,gross_profit_k=240,operating_profit_k=120);d.revenue['SYNTHETIC_A'].update(ytd_revenue_k=330,last_year_ytd_revenue_k=300)
        a=estimate(d,('TEST','SYNTHETIC_A'),CAL,'2027-04-10T12:00:00+08:00','2028-12-31');self.assertEqual(a['revenue_bridge']['prior_year_annual_revenue_k'],1200)
    def test_stale_forecast_certificate_is_not_reused(self):
        d=FakeData();d.evidence['certificates']['SYNTHETIC_A']={'forecast_bridge':dict(status='PASS',model_code_sha256='old')};a=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31');self.assertIn('DOES_NOT_MATCH',a['gates']['forecast_bridge']['reason'])
    def test_sports_footwear_cycle_flag_does_not_silently_alter_base_pe(self):
        d=FakeData()
        baseline=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        d.revenue['SYNTHETIC_A']['industry']='運動休閒'
        footwear=estimate(d,('TEST','SYNTHETIC_A'),CAL,ASOF,'2027-12-31')
        self.assertTrue(footwear['cycle_research']['cyclical_sector'])
        self.assertTrue(public_row(footwear)['cycle_research']['research_only'])
        self.assertFalse(footwear['cycle_research']['legacy_pe_cap_applied'])
        self.assertFalse(footwear['formal_Aplus'])
        self.assertEqual(footwear['pe_bridge']['base'],baseline['pe_bridge']['base'])
        self.assertEqual(footwear['base']['eps'],baseline['base']['eps'])
        self.assertIn('CYCLICAL_SECTOR_RESEARCH_ONLY_PE_UNCHANGED_PENDING_BACKTEST',
                      footwear['warning_flags'])

    def test_one_bad_issuer_does_not_stop_other_issuer(self):
        d=FakeData();d.evidence['primary']['SYNTHETIC_A']['values']['gross_profit_k']=999
        with tempfile.TemporaryDirectory() as tmp:
            with patch('scripts.tw_v880_run.MarketData',return_value=d),patch('scripts.tw_v880_run.fit_accounting',return_value=CAL),contextlib.redirect_stdout(io.StringIO()):r=run(tmp,ASOF,'2027-12-31',tmp)
            self.assertEqual(len(r['issuer_failures']),1);by_code={x['code']:x for x in r['all_model_rows']}
            self.assertEqual(by_code['SYNTHETIC_A']['status'],'ISSUER_INPUT_OR_MODEL_ERROR');self.assertTrue(by_code['SYNTHETIC_B']['rankable']);self.assertEqual(r['formal_Aplus_count'],0)
            self.assertEqual(json.loads(gzip.decompress((pathlib.Path(tmp)/'v880_full_results.json.gz').read_bytes()))['issuer_failures'],r['issuer_failures'])
if __name__=='__main__':unittest.main()
