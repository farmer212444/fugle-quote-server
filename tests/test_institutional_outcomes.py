"""A registered portfolio is evaluated from sources; no winner can be dropped."""
import datetime as dt
import hashlib
import json
import unittest

from tests import test_v897_freeze_model_vintage as vintage_fixtures
from scripts.v897_freeze_model_vintage import freeze
from tw_model_v880.contracts import canonical_hash
from tw_model_v880.validation_io import immutable_registration,collect_trials
from tw_model_v880.execution import COST_FIELDS
from tw_model_v880.peers import matched_multiples


class TrialSourceIntegration(unittest.TestCase):
    def setUp(self):
        fixture=vintage_fixtures.FrozenVintageTests('test_current_real_run_archive_contains_full_universe_and_exact_quotes')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.root=fixture.root
        paths={}
        for variant,code,sha in [('champion','1111','b'*64),('challenger','2222','c'*64)]:
            fixture.research['model_code_sha256']=sha
            fixture.research['top10_market_research']=[dict(market='TWSE',code=code)]
            fixture.rewrite_research()
            paths[variant]=freeze(self.root,vintage_fixtures.NOW,'V8.8.2')['path']
        spec=dict(trial_id='synthetic-source-integration',champion_model_sha256='b'*64,
                  challenger_model_sha256='c'*64,cost_policy={k:0. for k in COST_FIELDS},
                  reference_notional_ntd=100000,max_daily_participation=.05,
                  selection_rule='RESEARCH_TOP10_EQUAL_WEIGHT_NEXT_OPEN',holding_sessions=1)
        registered=immutable_registration(self.root,spec,'2026-10-21T08:00:00+08:00')
        original=self.save('raw-original.json',dict(synthetic_test_only=True))
        actions=self.save('actions.json',[])
        self.outcome=dict(signal_at='2026-10-21T08:10:00+08:00',exit_at='2026-10-21T14:00:00+08:00')
        self.bar_paths={}
        for variant,code,close in [('champion','1111',40),('challenger','2222',44)]:
            bars=[dict(code=code,market='TWSE',open_at='2026-10-21T09:00:00+08:00',
                       close_at='2026-10-21T13:30:00+08:00',open=40,close=close,
                       turnover_ntd=10000000,fillability_verified=True)]
            bar_ref=self.save(variant+'-bars.json',bars);self.bar_paths[variant]=self.root/bar_ref['path']
            review=self.save(variant+'-actions-review.json',dict(code=code,market='TWSE',complete=True,
                             reviewer_id='SYNTHETIC_TEST_NOT_REAL_REVIEWER',
                             **{'from':self.outcome['signal_at'],'through':self.outcome['exit_at']},
                             checked_at='2026-10-21T15:00:00+08:00',original_sources=[original]))
            leg=dict(code=code,market='TWSE',bars=bar_ref,actions=actions,corporate_action_review=review)
            self.outcome[variant]=dict(frozen_receipt_path=paths[variant],legs=[leg])
        self.payload=dict(registration_sha256=canonical_hash(registered),outcomes=[self.outcome])
        self.input_path=self.root/'experiments/inputs/synthetic-source-integration.json'
        self.input_path.parent.mkdir(parents=True);self.flush()

    def save(self,name,value):
        p=self.root/name;p.write_text(json.dumps(value))
        return dict(path=name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())

    def flush(self):
        self.input_path.write_text(json.dumps(self.payload))

    def test_actual_prices_recompute_returns_for_both_preselected_portfolios(self):
        result=collect_trials(self.root,'2026-10-22T12:00:00+08:00')
        self.assertFalse(result['errors'])
        trial=result['trials'][0];self.assertFalse(trial['rejected_outcomes'])
        pair=trial['pairs'][0]
        self.assertEqual(pair['champion_net_return'],0)
        self.assertAlmostEqual(pair['challenger_net_return'],.1)
        self.assertFalse(trial['formal_out_of_sample_pass'])

    def test_changing_price_bytes_rejects_whole_period(self):
        self.bar_paths['champion'].write_text('[]')
        trial=collect_trials(self.root,'2026-10-22T12:00:00+08:00')['trials'][0]
        self.assertFalse(trial['pairs']);self.assertTrue(trial['rejected_outcomes'])

    def test_omitting_the_losing_or_missing_stock_cannot_improve_backtest(self):
        self.outcome['champion']['legs']=[];self.flush()
        trial=collect_trials(self.root,'2026-10-22T12:00:00+08:00')['trials'][0]
        self.assertFalse(trial['pairs']);self.assertIn('MISSING_FROZEN',trial['rejected_outcomes'][0]['reason'])

    def test_outcome_unavailable_at_cutoff_is_not_a_realized_win(self):
        trial=collect_trials(self.root,'2026-10-21T13:00:00+08:00')['trials'][0]
        self.assertFalse(trial['pairs'])

    def test_model_archived_after_signal_is_not_prospective_even_with_old_estimate(self):
        for variant in ('champion','challenger'):
            with self.subTest(variant=variant):
                path=self.root/self.outcome[variant]['frozen_receipt_path']
                original=path.read_text();receipt=json.loads(original)
                receipt['archived_at_utc']='2026-10-21T10:00:00+00:00'
                path.write_text(json.dumps(receipt))
                trial=collect_trials(self.root,'2026-10-22T12:00:00+08:00')['trials'][0]
                self.assertFalse(trial['pairs'])
                self.assertIn('NOT_FROZEN_BEFORE_SIGNAL',trial['rejected_outcomes'][0]['reason'])
                path.write_text(original)

    def test_pair_uses_actual_archive_clock_not_the_earlier_estimate_label(self):
        trial=collect_trials(self.root,'2026-10-22T12:00:00+08:00')['trials'][0]
        self.assertEqual(trial['pairs'][0]['champion_frozen_at'],'2026-10-21T00:10:00+00:00')


class MatchedPeerInputs(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);raw=self.root/'source.pdf';raw.write_bytes(b'%PDF-synthetic')
        self.data=SimpleNamespace(root=self.root,price_date='2026-10-20',prices={('TEST',str(i)):dict(date='2026-10-20',close=100+i*10) for i in range(3)})
        bridge=dict(revenue_k=1000,gross_margin=.3,opex_ratio=.1,nonoperating_k=0,tax_rate=.2,parent_fraction=1,shares=10000)
        self.ledger=dict(code='X',financial_period='2026-Q2',target_date='2027-12-31',review_completed=True,
                         reviewer_id='SYNTHETIC_ONLY',issuer_business_model='test manufacturer',
                         available_at='2026-10-19T00:00:00+08:00',checked_at='2026-10-20T00:00:00+08:00',expires_at='2026-11-01T00:00:00+08:00',
                         sources=[dict(archive_path='source.pdf',url='https://example.invalid/test',available_at='2026-10-19T00:00:00+08:00',sha256=hashlib.sha256(raw.read_bytes()).hexdigest())],
                         peers=[dict(code=str(i),market='TEST',business_model='test manufacturer',earnings_basis='TARGET_YEAR_FORWARD_DILUTED_EPS',currency='TWD',operating_bridge=bridge) for i in range(3)])

    def evaluate(self,cyclical=False):
        return matched_multiples(self.ledger,self.data,'X','2026-Q2','2027-12-31','2026-10-21T12:00:00+08:00',cyclical)

    def test_peer_forward_eps_is_computed_from_operating_inputs(self):
        result=self.evaluate();self.assertAlmostEqual(result['base'],110/16)
        self.assertFalse(result['formal_quality_pass'])

    def test_trailing_pe_or_wrong_business_cannot_stand_in_for_matched_forward_pe(self):
        self.ledger['peers'][0]['earnings_basis']='TRAILING_TWELVE_MONTHS'
        with self.assertRaisesRegex(ValueError,'BASIS_MISMATCH'):self.evaluate()

    def test_cyclical_peers_require_normalized_earnings(self):
        with self.assertRaisesRegex(ValueError,'BASIS_MISMATCH'):self.evaluate(cyclical=True)

    def test_duplicate_or_self_peer_and_source_mutation_are_rejected(self):
        self.ledger['peers'][1]['code']='0'
        with self.assertRaisesRegex(ValueError,'DISTINCT'):self.evaluate()


if __name__=='__main__':unittest.main()
