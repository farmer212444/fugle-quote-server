import importlib.util
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

if __name__=='__main__':unittest.main()
