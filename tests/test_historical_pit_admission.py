"""Synthetic review packs exercise admission; no production PASS is fabricated."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.historical_pit_readiness import build
from scripts.expected_return_readiness import publish
from tw_model_v880.expected_returns import POLICY
from tw_model_v880.historical_pit import (FOLDER,admitted_batches,calibration_feasibility,check)

ASOF = '2026-11-06T15:00:00+08:00'


class HistoricalAdmission(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'prices').mkdir();(self.root/'config').mkdir()
        (self.root/'prices/latest_manifest.json').write_text(json.dumps(dict(date='2026-11-06')))
        (self.root/'config/institutional_research.json').write_text(json.dumps(dict(cost_policy=None)))

    def save(self,path,value,raw=False):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True)
        payload=value if raw else json.dumps(value).encode()
        p.write_bytes(payload)
        return dict(path=path,sha256=hashlib.sha256(payload).hexdigest())

    def fixture(self):
        original=self.save('synthetic/original.pdf',b'SYNTHETIC original statement; NOT actual company evidence',True)
        publication=self.save('synthetic/announcement.html',b'SYNTHETIC dated publication and version evidence',True)
        normalized=self.save('fundamentals/2025-Q1/TWSE_income.json',dict(market='TWSE',period='2025-Q1',kind='income',
            rows=[dict(code='6206',market='TWSE',period='2025-Q1',basic_eps_ytd=1.)]))
        gate=dict(status='PASS',issuer='6206',financial_period='2025-Q1',reviewed_by='SYNTHETIC_REVIEWER_NOT_PRODUCTION',
            method='SYNTHETIC named original/version review',review_signal_at='2025-06-01T15:00:00+08:00',checked_at=ASOF,
            original_archive_sha256_recomputed=True,human_source_identity_review_documented=True,
            normalized_values_reconciled_to_originals=True,revision_history_complete_through_signal=True,
            publication_and_revision_evidence=[dict(publication,url='https://mops.twse.com.tw/synthetic')],
            sources=[dict(archive_path=original['path'],sha256=original['sha256'],url='https://mops.twse.com.tw/synthetic.pdf',
                origin_authenticated=True,version_id='SYNTHETIC-V1',published_at='2025-05-12T15:00:00+08:00',
                revision_at='2025-05-12T15:00:00+08:00',available_at='2025-05-12T15:00:00+08:00')])
        review=dict(code='6206',market='TWSE',kind='income',normalized_input_sha256=normalized['sha256'],gates=dict(point_in_time=gate))
        ref=self.save('synthetic/review.json',review)
        pack=dict(schema='HISTORICAL_FINANCIAL_PIT_REVIEW_V1',market='TWSE',period='2025-Q1',kind='income',
                  signal_at='2025-06-01T15:00:00+08:00',checked_at=ASOF,normalized_input=normalized,issuer_reviews=[ref])
        return pack,review

    def replace_review(self,pack,review):
        pack['issuer_reviews']=[self.save('synthetic/review.json',review)]

    def test_complete_source_review_is_admitted_without_faking_model_preissuance(self):
        pack,_=self.fixture();r=check(self.root,pack,ASOF)
        self.assertEqual(r['issuer_count'],1)
        self.assertFalse(r['historical_model_preissuance_claimed'])
        self.assertEqual(r['reviewed_at'],ASOF)

    def test_empty_folder_counts_zero_from_evidence_not_a_constant(self):
        self.assertEqual(admitted_batches(self.root,ASOF),dict(admitted=[],rejected=[]))

    def test_readiness_count_changes_when_valid_review_arrives_and_rejects_tampering(self):
        pack,_=self.fixture();self.save(FOLDER+'/sample.json',pack)
        a=build(self.root);self.assertEqual(a['admitted_historical_financial_pit_batches'],1)
        self.assertFalse(a['formal_out_of_sample_pass']);self.assertIsNone(a['certified_oos_returns'])
        (self.root/'synthetic/original.pdf').write_bytes(b'tampered')
        b=build(self.root);self.assertEqual(b['admitted_historical_financial_pit_batches'],0)
        self.assertTrue(any('HASH_MISMATCH' in x['reason'] for x in b['source_rejections']))

    def test_future_restatement_is_rejected_even_with_review_flags(self):
        pack,review=self.fixture();review['gates']['point_in_time']['sources'][0]['revision_at']='2025-07-01T15:00:00+08:00'
        self.replace_review(pack,review)
        with self.assertRaisesRegex(ValueError,'LATER_REVISION'):check(self.root,pack,ASOF)

    def test_partial_issuer_coverage_cannot_admit_batch(self):
        pack,_=self.fixture();pack['issuer_reviews']=[]
        with self.assertRaisesRegex(ValueError,'PARTIAL_OR_EXTRA'):check(self.root,pack,ASOF)

    def test_false_mirror_flag_is_not_publication_evidence(self):
        pack,review=self.fixture();review['gates']['point_in_time']['publication_and_revision_evidence']=[]
        self.replace_review(pack,review)
        with self.assertRaisesRegex(ValueError,'PUBLICATION_PROOF_MISSING'):check(self.root,pack,ASOF)

    def test_unreviewed_source_identity_cannot_be_auto_signed(self):
        pack,review=self.fixture();review['gates']['point_in_time']['human_source_identity_review_documented']=False
        self.replace_review(pack,review)
        with self.assertRaisesRegex(ValueError,'REVIEW_NOT_DOCUMENTED'):check(self.root,pack,ASOF)

    def test_changed_normalized_values_are_rejected(self):
        pack,_=self.fixture();(self.root/pack['normalized_input']['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):check(self.root,pack,ASOF)

    def test_unofficial_source_and_future_review_clock_are_rejected(self):
        pack,review=self.fixture();review['gates']['point_in_time']['sources'][0]['url']='https://example.com/fake.pdf'
        self.replace_review(pack,review)
        with self.assertRaisesRegex(ValueError,'OFFICIAL_SOURCE'):check(self.root,pack,ASOF)
        pack['checked_at']='2027-01-01T00:00:00+08:00'
        with self.assertRaisesRegex(ValueError,'CLOCK'):check(self.root,pack,ASOF)

    def test_duplicate_packs_do_not_inflate_admission_count(self):
        pack,_=self.fixture();self.save(FOLDER+'/a.json',pack);self.save(FOLDER+'/b.json',pack)
        r=admitted_batches(self.root,ASOF)
        self.assertEqual(len(r['admitted']),1);self.assertIn('DUPLICATE_BATCH',r['rejected'][0]['reason'])


class CalibrationFeasibility(unittest.TestCase):
    def test_fixed_terminal_date_cannot_supply_24_nonoverlapping_windows(self):
        f=calibration_feasibility('2026-11-06','2027-12-31',POLICY)
        self.assertEqual(f['holding_calendar_days'],420)
        self.assertEqual(f['minimum_total_nonoverlapping_cohorts'],24)
        self.assertEqual(f['maximum_nonoverlapping_cohorts_with_same_terminal_date'],1)
        self.assertEqual(f['minimum_history_span_days_ignoring_embargo'],10080)
        self.assertFalse(f['fixed_target_only_can_satisfy_policy'])
        self.assertFalse(f['waiting_until_target_date_alone_resolves_calibration'])

    def test_invalid_period_and_policy_are_not_silently_adjusted(self):
        for start,end,p in [('2027-12-31','2027-12-31',POLICY),('2026-11-06','2027-12-31',dict(POLICY,minimum_train_cohorts=True))]:
            with self.assertRaises(ValueError):calibration_feasibility(start,end,p)


class ReadinessPublication(unittest.TestCase):
    def fixture(self,root):
        (root/'rankings').mkdir();(root/'prices').mkdir()
        r=dict(model='V8.10.8',asof_price_date='2026-11-06',estimate_vintage=ASOF,
               target_date='2027-12-31',strategy_variant='current-information')
        returns=dict(model=r['model'],asof_price_date=r['asof_price_date'],estimate_vintage=ASOF,
            horizon_reports=[dict(holding_sessions=21,verified_return_periods=0,walk_forward_test_periods=0)])
        annual=dict(schema='EXPECTED_RETURN_STATUS_V1',model=r['model'],source_price_date=r['asof_price_date'],
            source_estimate_vintage=ASOF,target_date=r['target_date'],status='AWAITING_MATCHED_MATURE_CALIBRATION',
            universe_rows=1,comparable_forecasts=1,verified_mature_observations=0,source_errors=[],issuer_status_counts={'PENDING':1},
            pending_cohorts=[],research_expected_return_ranking=[],expected_net_return=None,registration_id='KEEP_THIS_ID')
        for name,value in [('rankings/latest_research.json',r),('rankings/latest_return_model_search.json',returns),
                           ('prices/latest_manifest.json',dict(date='2026-11-06')),('rankings/latest_expected_returns.json',annual)]:
            (root/name).write_text(json.dumps(value))
        return annual

    def test_reports_impossible_wait_without_changing_forecasts_or_registration(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);annual=self.fixture(root)
            frozen=root/'experiments/expected_returns_v1/cohorts/sentinel.json';frozen.parent.mkdir(parents=True);frozen.write_bytes(b'UNCHANGED')
            path=root/'rankings/latest_expected_returns.json';prior=path.read_bytes()
            report=publish(root);updated=json.loads(path.read_text())
            self.assertTrue(report['annual_engine_context_matches'])
            self.assertEqual(path.read_bytes(),prior)
            self.assertEqual(updated['status'],'AWAITING_MATCHED_MATURE_CALIBRATION')
            self.assertIn('FIXED_TARGET_ONLY_CANNOT_SUPPLY_INDEPENDENT_ANNUAL_CALIBRATION_COHORTS',report['blockers'])
            self.assertEqual(updated['registration_id'],annual['registration_id']);self.assertIsNone(updated['expected_net_return'])
            self.assertEqual(frozen.read_bytes(),b'UNCHANGED')
            self.assertEqual(hashlib.sha256((root/'rankings/latest_expected_returns.json').read_bytes()).hexdigest(),report['annual_engine_report_sha256'])

    def test_stale_annual_report_is_not_relabelled_as_current(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);annual=self.fixture(root);annual['source_estimate_vintage']='2026-10-01T00:00:00+08:00'
            path=root/'rankings/latest_expected_returns.json';path.write_text(json.dumps(annual));prior=path.read_bytes()
            r=publish(root)
            self.assertFalse(r['annual_engine_context_matches']);self.assertEqual(path.read_bytes(),prior)

    def test_source_failure_is_not_hidden_by_methodology_annotation(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);annual=self.fixture(root);annual.update(status='SOURCE_REJECTED',source_errors=[{'reason':'SYNTHETIC_FAILURE'}])
            path=root/'rankings/latest_expected_returns.json';path.write_text(json.dumps(annual))
            publish(root);updated=json.loads(path.read_text())
            self.assertEqual(updated['status'],'SOURCE_REJECTED');self.assertEqual(updated['source_errors'],annual['source_errors'])


if __name__=='__main__':unittest.main()
