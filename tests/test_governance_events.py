import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_integration_v880 import FakeData, CAL, ASOF
from tw_model_v880.evidence import GATES, certify
from tw_model_v880.governance import (
    BLOCK, INVALID, CLOSURE_CHECKS, SCHEMA, evaluate_document,
    issuer_review, load_governance_reviews, reopen_quality_reviews,
)
from tw_model_v880.model import estimate
from tw_model_v880.portfolio import constrained_portfolio
from scripts.tw_v880_run import run, public_row

NOW = '2026-10-23T12:00:00+08:00'
RECORDED = '2026-10-23T09:00:00+08:00'
CHECKED = '2026-10-23T09:05:00+08:00'
POLICY = dict(max_stock_weight=.1, max_sector_weight=.25, max_common_risk_weight=.2,
              max_portfolio_bear_loss=.05, max_daily_participation=.05, max_exit_sessions=5)


class GovernanceOriginals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root / 'original.html'
        source.write_text('<html>SYNTHETIC ISSUER reported indictment; operating normally</html>')
        self.source = dict(url='https://issuer.example.com/notice', role='issuer_announcement',
            archive_path='original.html', sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            available_at='2026-09-11T21:48:24+08:00', captured_at_utc=RECORDED,
            http_status=200, origin_identity_reviewed=True,
            required_text_markers=['SYNTHETIC ISSUER', 'reported indictment'])
        self.update = dict(status='OPEN_REVIEW_REQUIRED', legal_stage='INDICTMENT_REPORTED_NOT_CONVICTED',
            available_at=self.source['available_at'], first_recorded_at=RECORDED,
            checked_at=CHECKED, reviewed_by='SYNTHETIC_TEST_REVIEWER', sources=[self.source])
        self.doc = dict(schema=SCHEMA, code='1111', market='TWSE', issuer_domains=['example.com'],
            events=[dict(event_id='SYNTHETIC_EVENT', category='RELATED_PARTY', materiality='MAJOR',
                         alleged_loss_ntd=2100000000, updates=[self.update])])

    def evaluate(self, asof=NOW):
        return evaluate_document(self.root, '1111', self.doc, asof)

    def save(self, code='1111'):
        path = self.root / ('evidence/v880/governance/' + code + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.doc))
        return path

    def test_material_case_blocks_without_inventing_guilt_or_expense(self):
        review = self.evaluate()
        self.assertEqual(review['status'], BLOCK)
        self.assertTrue(review['blocks_recommendation'])
        self.assertTrue(review['eps_pe_unchanged'])
        event = review['events'][0]
        self.assertTrue(event['conviction_not_inferred'])
        self.assertTrue(event['alleged_loss_is_not_current_period_expense'])
        self.assertEqual(event['alleged_loss_ntd'], 2100000000)

    def test_september_publication_cannot_be_backfilled_as_october_live_knowledge(self):
        self.assertIsNone(self.evaluate('2026-10-22T23:59:59+08:00'))
        self.assertIsNone(self.evaluate('2026-10-23T09:04:59+08:00'))
        self.assertEqual(self.evaluate(CHECKED)['status'], BLOCK)

    def test_tampered_missing_wrong_identity_and_unsafe_original_are_rejected(self):
        for change, message in [
            ({'sha256': '0'*64}, 'HASH_MISMATCH'),
            ({'required_text_markers': ['SOME_OTHER_ISSUER']}, 'MARKER_MISMATCH'),
            ({'archive_path': '../original.html'}, 'PATH_UNSAFE'),
            ({'url': 'https://news.other.example/story'}, 'ORIGIN_NOT_ALLOWED'),
            ({'captured_at_utc': '2026-10-24T12:00:00+08:00'}, 'CLOCK_INVALID'),
        ]:
            with self.subTest(change=change):
                doc = copy.deepcopy(self.doc)
                doc['events'][0]['updates'][0]['sources'][0].update(change)
                with self.assertRaisesRegex(ValueError, message):
                    evaluate_document(self.root, '1111', doc, NOW)

    def test_one_invalid_case_is_quarantined_and_not_silently_cleared(self):
        path = self.save()
        path.write_text('{invalid')
        reviews, errors, _ = load_governance_reviews(self.root, NOW)
        self.assertEqual(reviews['1111']['status'], INVALID)
        self.assertTrue(reviews['1111']['blocks_recommendation'])
        self.assertEqual(len(errors), 1)
        self.assertFalse(issuer_review(reviews, '2222', 'TWSE')['blocks_recommendation'])
        self.assertIn('NOT_LEGAL_CLEARANCE', issuer_review(reviews, '2222', 'TWSE')['status'])

    def test_market_mismatch_blocks_and_nonmaterial_event_is_not_automatic_rejection(self):
        review = self.evaluate()
        self.assertEqual(issuer_review({'1111': review}, '1111', 'TPEX')['status'], INVALID)
        self.doc['events'][0]['materiality'] = 'OTHER'
        self.assertFalse(self.evaluate()['blocks_recommendation'])

    def test_operating_normally_cannot_close_case_without_substantive_evidence(self):
        self.update['status'] = 'CLOSED_REVIEWED'
        self.update.update({key: True for key in CLOSURE_CHECKS})
        with self.assertRaisesRegex(ValueError, 'CLOSURE_NOT_SUBSTANTIATED'):
            self.evaluate()
        self.source.update(role='official_disposition')
        with self.assertRaisesRegex(ValueError, 'DISPOSITION_REQUIRES_OFFICIAL'):
            self.evaluate()

    def test_later_resolution_does_not_clear_an_earlier_cutoff(self):
        later = copy.deepcopy(self.update)
        later.update(status='CLOSED_REVIEWED', first_recorded_at='2026-10-24T09:00:00+08:00',
                     checked_at='2026-10-24T09:05:00+08:00')
        # Future revisions are not used, even if their later evidence is incomplete.
        self.doc['events'][0]['updates'].append(later)
        self.assertTrue(self.evaluate()['blocks_recommendation'])
        with self.assertRaisesRegex(ValueError, 'CLOSURE_NOT_SUBSTANTIATED'):
            self.evaluate('2026-10-24T12:00:00+08:00')

    def test_duplicate_events_and_reversed_revisions_are_rejected(self):
        self.doc['events'].append(copy.deepcopy(self.doc['events'][0]))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            self.evaluate()
        self.doc['events'].pop()
        self.doc['events'][0]['updates'].append(copy.deepcopy(self.update))
        with self.assertRaisesRegex(ValueError, 'APPEND_ORDERED'):
            self.evaluate()


class GovernanceDecisions(unittest.TestCase):
    def review(self):
        return dict(status=BLOCK, blocks_recommendation=True,
                    material_open_event_ids=['SYNTHETIC_EVENT'], events=[])

    def passes(self):
        return {name: dict(status='PASS', issuer='SYNTHETIC_A', financial_period='2026-Q2',
            sources=[dict(url='https://issuer.example.com/original', sha256='a'*64,
                          origin_authenticated=True, available_at='2026-10-17T09:00:00+08:00')],
            method='SYNTHETIC_TEST_ONLY', available_at='2026-10-17T09:00:00+08:00',
            checked_at='2026-10-17T10:00:00+08:00', expires_at='2027-01-01T00:00:00+08:00',
            stress_verified=True) for name in GATES}

    def test_old_thirteen_passes_cannot_override_known_material_case(self):
        gates = self.passes()
        self.assertTrue(certify('SYNTHETIC_A', 50, 20, gates, ASOF, '2026-Q2')['formal_Aplus'])
        changed = reopen_quality_reviews(gates, self.review())
        decision = certify('SYNTHETIC_A', 50, 20, changed, ASOF, '2026-Q2')
        self.assertFalse(decision['formal_Aplus'])
        self.assertFalse(decision['formal_Aplusplus'])
        self.assertEqual(len(changed), 13)
        self.assertEqual(set(decision['gates_pending']), {'management_promises', 'auditor_scope'})
        self.assertEqual(gates['management_promises']['status'], 'PASS')

    def test_existing_failure_is_preserved_without_turning_an_indictment_into_fail(self):
        gates = self.passes()
        gates['auditor_scope']['status'] = 'FAIL'
        result = reopen_quality_reviews(gates, self.review())
        self.assertEqual(result['auditor_scope']['status'], 'FAIL')
        self.assertEqual(result['management_promises']['status'], 'PENDING')

    def test_resolution_needs_new_event_specific_gate_review_not_old_pass_revival(self):
        review = dict(blocks_recommendation=False, events=[dict(event_id='SYNTHETIC_EVENT',
            materiality='MAJOR', status='CLOSED_REVIEWED', checked_at=CHECKED)])
        gates = self.passes()
        self.assertEqual(reopen_quality_reviews(gates, review)['auditor_scope']['status'], 'PENDING')
        for name in ('management_promises', 'auditor_scope'):
            gates[name].update(checked_at=CHECKED, governance_event_ids=['SYNTHETIC_EVENT'])
        self.assertEqual(reopen_quality_reviews(gates, review)['auditor_scope']['status'], 'PASS')

    def test_estimation_preserves_operating_scenarios_and_discloses_block(self):
        data = FakeData()
        before = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        data.governance_reviews = {'SYNTHETIC_A': self.review()}
        after = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        for name in ('base', 'bear', 'bull'):
            self.assertEqual(before[name], after[name])
        self.assertTrue(after['rankable'])  # An arithmetic research rank is not a recommendation.
        self.assertTrue(after['recommendation_blocked'])
        self.assertEqual(after['rating'], '重大治理待查')
        self.assertTrue(public_row(after)['recommendation_blocked'])
        self.assertEqual(after['gates']['management_promises']['reason'], BLOCK)

    def test_reports_show_case_and_keep_other_issuer_unaffected(self):
        data = FakeData()
        data.governance_reviews = {'SYNTHETIC_A': self.review()}
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.tw_v880_run.MarketData', return_value=data), patch(
                'scripts.tw_v880_run.fit_accounting', return_value=CAL), contextlib.redirect_stdout(io.StringIO()):
                result = run(directory, ASOF, '2027-12-31', directory)
            self.assertEqual(result['governance_blocked_count'], 1)
            text = (Path(directory) / 'latest_research.md').read_text()
            self.assertIn('重大治理待查', text)
            self.assertIn('起訴不等於定罪', text)
            other = next(x for x in result['all_model_rows'] if x['code'] == 'SYNTHETIC_B')
            self.assertFalse(other['recommendation_blocked'])

    def test_portfolio_rejects_block_even_with_stale_formal_true(self):
        candidate = dict(code='SYNTHETIC_A', market='TEST', industry='TEST', formal_Aplus=True,
            execution_review=dict(spread_and_exit_verified=True, median20_turnover_ntd=100000000),
            common_risk_tags=['TEST_RISK'], reviewed_stress_loss_fraction=.3)
        self.assertTrue(constrained_portfolio([candidate], 10000000, POLICY)['positions'])
        for flags in ({'recommendation_blocked': True}, {'governance_review': self.review()}):
            out = constrained_portfolio([dict(candidate, **flags)], 10000000, POLICY)
            self.assertFalse(out['positions'])
            self.assertIn(BLOCK, out['excluded'][0]['reasons'])
