import json
import tempfile
import unittest
from pathlib import Path

from scripts.historical_pit_readiness import build, render
from scripts.tw_history_backfill import process
from tests.test_tw_history_backfill import response, days
from tw_model_v880.execution import COST_FIELDS


class HistoricalReadiness(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'prices').mkdir();(self.root/'config').mkdir()
        (self.root/'prices/latest_manifest.json').write_text(json.dumps({'date':'2026-10-16'}))
        (self.root/'config/institutional_research.json').write_text(json.dumps({'cost_policy':None}))

    def collect(self,code='6206'):
        raw=response('2026-09',days('2026-09')).replace(b'6206',code.encode())
        process(code,'2026-10-16',['2026-09'],lambda _:raw,
            self.root/'prices/issuer_history/TWSE',self.root/'raw',sleep=0,root=self.root)

    def test_dated_quotes_with_current_capture_are_not_historical_financial_pit(self):
        self.collect()
        report=build(self.root)
        self.assertEqual(report['verified_durable_original_receipts'],1)
        self.assertGreater(report['issuer_price_coverage'][0]['sessions_with_observed_open'],0)
        self.assertEqual(report['admitted_historical_financial_pit_batches'],0)
        self.assertFalse(report['formal_out_of_sample_pass'])
        self.assertIsNone(report['certified_oos_returns'])
        self.assertIn('PROSPECTIVE_COST_POLICY_NOT_FIXED',report['blockers'])
        self.assertIn('不能替代財報首次公開',render(report))

    def test_changed_normalized_open_is_rejected_without_blocking_other_company(self):
        self.collect();self.collect('9802')
        path=self.root/'prices/issuer_history/TWSE/6206.json'
        obj=json.loads(path.read_text());obj['by_month']['2026-09']['rows'][0]['open']=1
        path.write_text(json.dumps(obj))
        report=build(self.root)
        self.assertEqual([r['code'] for r in report['issuer_price_coverage']],['9802'])
        self.assertTrue(any('NORMALIZED_ROWS_DIFFER' in r['reason'] for r in report['source_rejections']))

    def test_mirror_boolean_does_not_authenticate_historical_publication_or_revision(self):
        folder=self.root/'fundamentals/2025-Q1';folder.mkdir(parents=True)
        (folder/'TWSE_income.json').write_text(json.dumps(dict(period='2025-Q1',kind='income',
            market='TWSE',capture_utc='2026-10-22T00:00:00+00:00',company_PIT_verified=True,rows=[])))
        report=build(self.root)
        self.assertFalse(report['financial_mirrors'][0]['historical_publication_and_revision_proof_admitted'])
        self.assertEqual(report['admitted_historical_financial_pit_batches'],0)

    def test_other_issuers_valid_original_cannot_be_relabelled(self):
        self.collect()
        path=self.root/'prices/issuer_history/TWSE/6206.json'
        obj=json.loads(path.read_text());obj['issuer']='9802'
        path.unlink()
        (path.parent/'9802.json').write_text(json.dumps(obj))
        report=build(self.root)
        self.assertEqual(report['issuer_price_coverage'],[])
        self.assertIn('ISSUER_OR_PERIOD_MISMATCH',report['source_rejections'][0]['reason'])

    def test_empty_partial_and_nonfinite_cost_policies_stay_blocked(self):
        complete={name:0. for name in COST_FIELDS}
        for policy in ({},dict(buy_fee_rate=0),dict(complete,sell_tax_rate=float('nan'))):
            with self.subTest(policy=policy):
                (self.root/'config/institutional_research.json').write_text(json.dumps({'cost_policy':policy}))
                report=build(self.root)
                self.assertFalse(report['prospective_cost_policy_fixed'])
                self.assertIn('PROSPECTIVE_COST_POLICY_NOT_FIXED',report['blockers'])
        (self.root/'config/institutional_research.json').write_text(json.dumps({'cost_policy':complete}))
        report=build(self.root)
        self.assertTrue(report['prospective_cost_policy_fixed'])
        self.assertFalse(report['formal_out_of_sample_pass'])


if __name__=='__main__':unittest.main()
