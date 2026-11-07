"""Synthetic failure examples; no real issuer or PIT certification is created."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.expected_return_blocker_triage import build,publish

class BlockerTriage(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name);(self.root/'rankings').mkdir()
        self.rows=[
            dict(market='TWSE',code='2330',rankable=True,bear=dict(target_price=80),base=dict(target_price=100),bull=dict(target_price=130)),
            dict(market='TWSE',code='1111',rankable=True,bear=dict(target_price=-5),base=dict(target_price=60),bull=dict(target_price=70)),
            dict(market='TPEX',code='2222',rankable=True,bear=dict(target_price=30),base=dict(target_price=25),bull=dict(target_price=80))]
        raw=json.dumps(dict(all_model_rows=self.rows)).encode();packed=gzip.compress(raw)
        (self.root/'rankings/v880_full_results.json.gz').write_bytes(packed)
        self.model=dict(model='TEST',asof_price_date='2026-11-06',estimate_vintage='2026-11-07T04:00:00+08:00',
            full_results=dict(path='v880_full_results.json.gz',sha256=hashlib.sha256(packed).hexdigest(),
                              json_sha256=hashlib.sha256(raw).hexdigest()))
        self.expected=dict(model='TEST',source_price_date='2026-11-06',
            source_estimate_vintage='2026-11-07T04:00:00+08:00',universe_rows=3,status='NO_CALIBRATION',
            issuer_results=[dict(market='TWSE',code='2330',status='AWAITING_MATCHED_MATURE_OOS_COHORTS'),
                dict(market='TWSE',code='1111',status='EXPECTED_RETURN_SCENARIOS_INVALID'),
                dict(market='TPEX',code='2222',status='EXPECTED_RETURN_SCENARIOS_INVALID')],
            issuer_status_counts=dict(AWAITING_MATCHED_MATURE_OOS_COHORTS=1,EXPECTED_RETURN_SCENARIOS_INVALID=2),
            verified_mature_observations=0)
        self.history=dict(historical_end='2026-11-06',verified_durable_original_receipts=2,
            admitted_historical_financial_pit_batches=0,historical_financial_pit_admissions=[],
            financial_mirrors=[dict(market='TWSE',period='2024-Q4',kind='income',path='fundamentals/2024-Q4/TWSE_income.json')],
            blockers=['ORIGINAL_VERSION_REQUIRED'])
        self.save()
    def save(self):
        for name,data in [('latest_research',self.model),('latest_expected_returns',self.expected),
                          ('historical_pit_readiness',self.history)]:
            (self.root/'rankings'/(name+'.json')).write_text(json.dumps(data))
    def test_invalid_case_diagnosis_keeps_probabilities_null(self):
        result=publish(self.root)
        self.assertEqual(result['invalid_scenario_count'],2)
        self.assertEqual(result['invalid_scenario_issuers'][0]['reasons'],['NONPOSITIVE_BEAR_TARGET'])
        self.assertEqual(result['invalid_scenario_issuers'][1]['reasons'],['BEAR_BASE_BULL_NOT_STRICTLY_ASCENDING'])
        self.assertIsNone(result['expected_return_top10'])
        self.assertEqual(result['formal_Aplus_added'],0)
        self.assertEqual(len(result['unadmitted_financial_mirrors']),1)
    def test_hash_tamper_and_stale_vintage_fail_closed(self):
        self.expected['source_price_date']='2026-11-05';self.save()
        with self.assertRaisesRegex(ValueError,'VINTAGE_MISMATCH'):build(self.root)
        self.expected['source_price_date']='2026-11-06';self.save()
        file=self.root/'rankings/v880_full_results.json.gz';file.write_bytes(file.read_bytes()+b'tampered')
        with self.assertRaisesRegex(ValueError,'GZIP_HASH_MISMATCH'):build(self.root)
    def test_admitted_pit_removes_only_matching_mirror(self):
        self.history['historical_financial_pit_admissions']=[dict(market='TWSE',period='2024-Q4',kind='income')]
        self.history['admitted_historical_financial_pit_batches']=1;self.save()
        result=build(self.root)
        self.assertEqual(len(result['unadmitted_financial_mirrors']),0)
        self.assertEqual(result['admitted_historical_pit_batches'],1)
if __name__=='__main__':unittest.main()
