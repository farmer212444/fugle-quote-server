import importlib.util
import copy
import json
import tempfile
import unittest
from pathlib import Path

SRC=Path(__file__).resolve().parents[1]/'scripts/expected_return_readiness.py'
spec=importlib.util.spec_from_file_location('expected_return_readiness',SRC)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample():
    research=dict(model='V8.10.8',asof_price_date='2026-10-22',
                  estimate_vintage='2026-10-25T22:44:37+08:00',strategy_variant='current-information')
    ret=dict(model='V8.10.8',asof_price_date='2026-10-22',
             estimate_vintage='2026-10-25T22:44:37+08:00',
             horizon_reports=[dict(holding_sessions=h,verified_return_periods=0,walk_forward_test_periods=0)
                              for h in (21,63,126)])
    return research,ret

class ExpectedReturnReadinessTest(unittest.TestCase):
    def test_realistic_2026_zero_outcomes_and_newer_prices_fail_closed(self):
        research,ret=sample()
        result=module.evaluate(research,ret,dict(date='2026-11-05'))
        self.assertIsNone(result['expected_net_return_top10'])
        self.assertIsNone(result['calibrated_issuer_scenario_probabilities'])
        self.assertEqual(result['horizon_evidence'][0]['walk_forward_test_periods'],0)
        self.assertIn('RESEARCH_PRICE_DATE_OLDER_THAN_LATEST_ARCHIVED_OFFICIAL_CLOSE',result['blockers'])
        self.assertFalse(result['base_price_upside_ranking_is_expected_return'])
    def test_outcomes_without_probability_still_cannot_be_called_expected(self):
        research,ret=sample()
        for item in ret['horizon_reports']:
            item.update(verified_return_periods=60,walk_forward_test_periods=60)
        result=module.evaluate(research,ret,dict(date='2026-10-22'))
        self.assertIsNone(result['expected_net_return_top10'])
        self.assertNotIn('INSUFFICIENT_PIT_COST_ADJUSTED_WALK_FORWARD_PERIODS',result['blockers'])
    def test_mixed_source_vintage_refused(self):
        research,ret=sample();ret['asof_price_date']='2026-11-05'
        with self.assertRaisesRegex(ValueError,'EXPECTED_RETURN_VINTAGE_MISMATCH'):
            module.evaluate(research,ret)
    def test_negative_or_non_integer_outcomes_refused(self):
        research,ret=sample();ret['horizon_reports'][0]['verified_return_periods']=-1
        with self.assertRaisesRegex(ValueError,'EXPECTED_RETURN_INVALID_PERIOD_COUNTS'):
            module.evaluate(research,ret)
    def test_emit_has_source_checksums_and_never_relabels_base(self):
        research,ret=sample()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'rankings').mkdir();(root/'prices').mkdir()
            (root/'rankings/latest_research.json').write_text(json.dumps(research))
            (root/'rankings/latest_return_model_search.json').write_text(json.dumps(ret))
            (root/'prices/latest_manifest.json').write_text(json.dumps(dict(date='2026-11-05')))
            result=module.publish(root)
            self.assertEqual(len(result['source_sha256']),3)
            data=json.loads((root/'rankings/latest_expected_return_readiness.json').read_text())
            self.assertIsNone(data['expected_net_return_top10'])
            self.assertIn('沒有正式 TOP10',(root/'rankings/latest_expected_return_readiness.md').read_text())


class AnnualEngineReadinessTests(unittest.TestCase):
    """Only synthetic outcomes; engineering evidence, not investment performance."""
    @classmethod
    def setUpClass(cls):
        from tests.test_expected_returns import records,forecast,ZERO
        from tw_model_v880.expected_returns import estimate,POLICY,RETURN_DEFINITION
        f=forecast();samples=records()
        row=dict(market=f['market'],code=f['code'],name='SYNTHETIC',**estimate(f,samples,
            asof='2026-01-01T15:00:00+08:00',costs=ZERO,notional=1e6))
        cls.research=dict(model='SYNTHETIC',asof_price_date=f['price_date'],estimate_vintage=f['estimate_vintage'],
            target_date=f['target_date'],strategy_variant='current-information',data_scope=dict(model_rows=1))
        cls.returns=dict(model='SYNTHETIC',asof_price_date=f['price_date'],estimate_vintage=f['estimate_vintage'],
            horizon_reports=[dict(holding_sessions=21,verified_return_periods=0,walk_forward_test_periods=0)])
        cls.annual=dict(schema='EXPECTED_RETURN_STATUS_V1',model='SYNTHETIC',source_price_date=f['price_date'],
            source_estimate_vintage=f['estimate_vintage'],target_date=f['target_date'],policy=POLICY,
            return_definition=RETURN_DEFINITION,status='RESEARCH_ESTIMATES_AFTER_OOS_CHECKS',source_errors=[],
            universe_rows=1,verified_mature_observations=len(samples),formal_Aplus_added=0,trade_orders_created=0,
            issuer_results=[row],research_expected_return_ranking=[row])

    def calculate(self,annual=None,price=None):
        return module.evaluate(self.research,self.returns,dict(date=price or self.research['asof_price_date']),
            copy.deepcopy(self.annual) if annual is None else annual)

    def test_verified_annual_engine_can_release_research_results(self):
        result=self.calculate()
        self.assertEqual(result['status'],'RESEARCH_EXPECTED_RETURN_AVAILABLE')
        self.assertEqual(result['blockers'],[])
        self.assertEqual(len(result['expected_net_return_top10']),1)
        self.assertAlmostEqual(result['expected_net_return_top10'][0]['expected_net_total_return'],.05)
        self.assertTrue(result['formal_Aplus_status_unchanged'])
        self.assertFalse(result['trading_orders_created'])
        self.assertEqual(result['horizon_evidence'][0]['walk_forward_test_periods'],0)

    def test_other_vintage_or_newer_price_never_releases_an_old_result(self):
        annual=copy.deepcopy(self.annual);annual['source_price_date']='2025-12-31'
        result=self.calculate(annual)
        self.assertIsNone(result['expected_net_return_top10'])
        self.assertIn('ANNUAL_ENGINE_REPORT_CONTEXT_MISMATCH',result['blockers'])
        self.assertIsNone(self.calculate(price='2026-01-02')['expected_net_return_top10'])

    def test_flags_bad_probabilities_or_unreconciled_mean_cannot_mint_results(self):
        changes=[lambda r:r['diagnostics'].update(diagnostics_passed=False),
            lambda r:r['diagnostics'].update(oos_cohorts=1),
            lambda r:r['scenario_probabilities'].update(base=.9),
            lambda r:r.update(expected_net_total_return=.50),
            lambda r:r.update(research_policy_sha256='f'*64)]
        for change in changes:
            annual=copy.deepcopy(self.annual);change(annual['issuer_results'][0])
            with self.assertRaisesRegex(ValueError,'ANNUAL_RESULT_NOT_VERIFIABLE'):self.calculate(annual)

    def test_source_rejections_still_block_an_apparently_successful_engine(self):
        annual=copy.deepcopy(self.annual);annual['source_errors']=[dict(reason='SYNTHETIC_TAMPERING')]
        result=self.calculate(annual)
        self.assertIsNone(result['expected_net_return_top10'])
        self.assertIn('ANNUAL_ENGINE_SOURCE_REJECTIONS_REQUIRE_REPAIR',result['blockers'])

    def test_readiness_publication_never_rewrites_the_engine_or_frozen_method(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'rankings').mkdir();(root/'prices').mkdir()
            documents={'rankings/latest_research.json':self.research,'rankings/latest_return_model_search.json':self.returns,
                'prices/latest_manifest.json':dict(date=self.research['asof_price_date']),
                'rankings/latest_expected_returns.json':self.annual}
            for path,obj in documents.items():(root/path).write_text(json.dumps(obj))
            annual_path=root/'rankings/latest_expected_returns.json';before=annual_path.read_bytes()
            result=module.publish(root)
            self.assertEqual(annual_path.read_bytes(),before)
            self.assertEqual(result['status'],'RESEARCH_EXPECTED_RETURN_AVAILABLE')
            self.assertIn('annual_engine',result['source_sha256'])

if __name__=='__main__':unittest.main()
