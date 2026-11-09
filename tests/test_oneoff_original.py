"""Synthetic PDF facts are controls, not financial evidence for real issuers."""
import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz

from scripts import oneoff_original_review as collector
from tests.test_integration_v880 import ASOF, CAL, FakeData
from tw_model_v880 import oneoff_original as source
from tw_model_v880.data import model_source_state
from tw_model_v880.model import estimate

CUT = '2026-11-09T07:00:00+08:00'


def fixture(root, *, code='2483', amount='125'):
    doc = fitz.open()
    cover = doc.new_page()
    cover.insert_text((40, 40), 'Stock Code: ' + code + ' SYNTHETIC CONTROL ONLY')
    cover.insert_text((40, 70), '114')
    cover.insert_text((40, 100), '300')
    note = doc.new_page()
    note.insert_text((40, 70), amount)
    raw = doc.tobytes()
    def field(page, text, expected):
        word = next(x for x in doc[page - 1].get_text('words') if x[4] == text)
        return dict(pdf_page=page, bbox=[word[0]-1, word[1]-1, word[2]+1, word[3]+1], expected_value=expected)
    case = dict(code=code, anchor_period='2025-Q4', source_url=source.URLS[code],
                pdf_sha256=source.sha(raw), pdf_pages=2, units='TWD_THOUSANDS',
                reviewed_at='2026-11-09T05:00:00+08:00', selected_page_visual_review=True,
                issuer_identity_mode='NATIVE_COVER_CODE_AND_SELECTED_PAGE_REVIEW',
                selected_gain_label='SYNTHETIC NONRECURRING GAIN', profit_effect_multiplier=1,
                facts=dict(fiscal_year_roc=field(1, '114', 114),
                           reported_fy_nonoperating_k=field(1, '300', 300),
                           selected_gain_amount=field(2, amount, -125 if amount.startswith('(') else 125)))
    doc.close()
    config = dict(schema=source.SCHEMA, formal_quality_pass=False, cases=[case])
    cp = root / source.CONFIG
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(config))
    packed = gzip.compress(raw, mtime=0)
    path = root / source.FOLDER / code / 'synthetic.pdf.gz'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(packed)
    receipt = dict(code=code, source_url=case['source_url'], pdf_sha256=case['pdf_sha256'],
                   gzip_sha256=source.sha(packed), archive_path=path.relative_to(root).as_posix(),
                   captured_at='2026-11-09T06:00:00+08:00')
    manifest = dict(schema=source.SCHEMA, config_sha256=source.sha(cp.read_bytes()),
                    captures=[receipt], formal_quality_pass=False)
    mp = root / source.FOLDER / 'manifest.json'
    mp.write_text(json.dumps(manifest))
    return raw, case, receipt, path, config, manifest


def multiple_fixture(root):
    raw, case, receipt, path, config, manifest = fixture(root)
    doc = fitz.open(stream=raw, filetype='pdf')
    page = doc[1]
    for y, value in [(100, '50'), (130, '(125)'), (160, '(50)'), (190, '25'), (220, '(25)')]:
        page.insert_text((40, y), value)
    def field(token, expected):
        w = next(w for w in page.get_text('words') if w[4] == token)
        return dict(pdf_page=2, bbox=[w[0]-1, w[1]-1, w[2]+1, w[3]+1], expected_value=expected)
    case['facts']['first'] = case['facts'].pop('selected_gain_amount')
    case['facts'].update(second=field('50', 50), first_cf=field('(125)', -125),
                         second_cf=field('(50)', -50), volatile=field('25', 25), volatile_cf=field('(25)', -25))
    case.pop('profit_effect_multiplier')
    case['gain_items'] = [dict(id='first', label='SYNTHETIC FIRST', fact_key='first', profit_effect_multiplier=1,
                               corroborating_fact_key='first_cf', corroborating_multiplier=-1),
                          dict(id='second', label='SYNTHETIC SECOND', fact_key='second', profit_effect_multiplier=1,
                               corroborating_fact_key='second_cf', corroborating_multiplier=-1)]
    case['remaining_volatile_items'] = [dict(id='volatile', label='SYNTHETIC UNRESOLVED RECURRENCE', fact_key='volatile',
                                            profit_effect_multiplier=1, corroborating_fact_key='volatile_cf', corroborating_multiplier=-1)]
    raw = doc.tobytes(); doc.close()
    case['pdf_sha256'] = source.sha(raw)
    packed = gzip.compress(raw, mtime=0); path.write_bytes(packed)
    receipt.update(pdf_sha256=source.sha(raw), gzip_sha256=source.sha(packed), review_case_sha256=source.case_sha(case))
    config['cases'] = [case]
    cp = root / source.CONFIG; cp.write_text(json.dumps(config))
    manifest.update(config_sha256=source.sha(cp.read_bytes()), captures=[receipt])
    (root / source.FOLDER / 'manifest.json').write_text(json.dumps(manifest))
    return raw, case, receipt, path, config, manifest


class OneoffOriginalSources(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.raw, self.case, self.receipt, self.path, self.config, self.manifest = fixture(self.root)

    def test_original_amount_is_reparsed_and_does_not_certify_other_components(self):
        reviews, states, errors = source.load(self.root, CUT)
        self.assertFalse(errors)
        self.assertFalse(states)
        self.assertEqual(reviews['2483']['excluded_positive_gain_k'], 125)
        self.assertFalse(reviews['2483']['formal_quality_pass'])
        self.assertFalse(reviews['2483']['remaining_components_verified'])

    def test_tampered_bytes_quarantine_issuer_instead_of_reusing_old_baseline(self):
        self.path.write_bytes(self.path.read_bytes() + b'tampered')
        reviews, states, errors = source.load(self.root, CUT)
        self.assertFalse(reviews)
        self.assertTrue(states['2483']['blocks_current_decision'])
        self.assertIn('SHA_MISMATCH', errors[0]['error'])

    def test_changed_selected_value_and_wrong_fiscal_column_rejected(self):
        case = copy.deepcopy(self.case)
        case['facts']['selected_gain_amount']['expected_value'] = 126
        with self.assertRaisesRegex(ValueError, 'AMOUNT_CHANGED'):
            source.inspect_pdf(self.raw, case)
        case = copy.deepcopy(self.case)
        case['anchor_period'] = '2024-Q4'
        with self.assertRaisesRegex(ValueError, 'FISCAL_COLUMN'):
            source.inspect_pdf(self.raw, case)

    def test_cashflow_reconciliation_sign_is_reversed_once_without_loss_addback(self):
        raw, case, *_ = fixture(self.root, code='2331', amount='(125)')
        case['profit_effect_multiplier'] = -1
        self.assertEqual(source.inspect_pdf(raw, case)['excluded_positive_gain_k'], 125)
        case['profit_effect_multiplier'] = 1
        with self.assertRaisesRegex(ValueError, 'NO_LOSS_ADDBACK'):
            source.inspect_pdf(raw, case)

    def test_native_issuer_and_selected_box_bounds_fail_closed(self):
        case = copy.deepcopy(self.case)
        case['code'] = '6763'
        with self.assertRaisesRegex(ValueError, 'ISSUER_MISMATCH'):
            source.inspect_pdf(self.raw, case)
        case = copy.deepcopy(self.case)
        case['facts']['selected_gain_amount']['bbox'] = [-10, -10, 5, 5]
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_PAGE'):
            source.inspect_pdf(self.raw, case)

    def test_neighbouring_glyph_boxes_do_not_invert_positive_subtotal(self):
        class Page:
            rect = fitz.Rect(0, 0, 100, 100)
            def get_text(self, kind):
                if kind != 'words':
                    raise AssertionError('word geometry required')
                return [(10, 0, 20, 12, '('), (30, 0, 40, 12, ')'), (10, 10, 40, 20, '300')]
        self.assertEqual(source.number_in_box(Page(), dict(bbox=[9, 9, 41, 21], expected_value=300)), 300)

    def test_future_capture_or_later_review_cannot_leak_into_past_estimate(self):
        reviews, states, errors = source.load(self.root, '2026-11-09T05:30:00+08:00')
        self.assertFalse(reviews)
        self.assertFalse(errors)
        self.assertEqual(states['2483']['status'], 'ORIGINAL_CAPTURE_PENDING')
        self.assertTrue(states['2483']['blocks_current_decision'])

    def test_future_capture_and_absent_capture_have_the_same_historical_admission(self):
        cut='2026-11-09T05:30:00+08:00'
        before=source.load(self.root,cut)
        self.manifest['captures']=[]
        (self.root/source.FOLDER/'manifest.json').write_text(json.dumps(self.manifest))
        after=source.load(self.root,cut)
        self.assertEqual(before,after)

    def test_review_time_is_a_separate_availability_barrier(self):
        self.config['cases'][0]['reviewed_at'] = '2026-11-09T08:00:00+08:00'
        cp = self.root / source.CONFIG
        cp.write_text(json.dumps(self.config))
        self.manifest['config_sha256'] = source.sha(cp.read_bytes())
        (self.root / source.FOLDER / 'manifest.json').write_text(json.dumps(self.manifest))
        reviews, states, errors = source.load(self.root, CUT)
        self.assertFalse(reviews)
        self.assertFalse(errors)
        self.assertEqual(states['2483']['status'], 'SOURCE_AVAILABLE_AFTER_ESTIMATE')

    def test_external_host_or_false_certification_not_admitted(self):
        self.config['cases'][0]['source_url'] = 'https://example.invalid/research.pdf'
        (self.root / source.CONFIG).write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, 'NOT_ALLOWLISTED'):
            source.config(self.root)
        self.config['formal_quality_pass'] = True
        (self.root / source.CONFIG).write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, 'FALSE_CERTIFICATION'):
            source.config(self.root)

    def test_missing_archive_is_unknown_and_duplicate_capture_is_rejected(self):
        mp = self.root / source.FOLDER / 'manifest.json'
        mp.unlink()
        reviews, states, errors = source.load(self.root, CUT)
        self.assertFalse(reviews)
        self.assertFalse(errors)
        self.assertEqual(states['2483']['status'], 'ORIGINAL_CAPTURE_PENDING')
        self.assertTrue(states['2483']['blocks_current_decision'])
        self.manifest['captures'] *= 2
        mp.write_text(json.dumps(self.manifest))
        reviews, states, errors = source.load(self.root, CUT)
        self.assertFalse(reviews)
        self.assertTrue(states['2483']['blocks_current_decision'])

    def test_unsafe_archive_path_and_review_version_are_not_used(self):
        self.manifest['captures'][0]['archive_path'] = '../outside.pdf.gz'
        mp = self.root / source.FOLDER / 'manifest.json'
        mp.write_text(json.dumps(self.manifest))
        _, states, errors = source.load(self.root, CUT)
        self.assertTrue(states['2483']['blocks_current_decision'])
        self.assertIn('UNSAFE_PATH', errors[0]['error'])
        self.manifest['config_sha256'] = '0' * 64
        mp.write_text(json.dumps(self.manifest))
        _, states, errors = source.load(self.root, CUT)
        self.assertIn('VERSION_MISMATCH', errors[0]['error'])

    def test_capture_failure_keeps_last_manifest(self):
        mp = self.root / source.FOLDER / 'manifest.json'
        before = mp.read_bytes()
        with patch.object(sys, 'argv', ['oneoff', '--root', str(self.root)]), \
                patch.object(collector, 'capture', side_effect=ValueError('source unavailable')):
            self.assertEqual(collector.main(), 1)
        self.assertEqual(mp.read_bytes(), before)

    def test_html_error_body_cannot_be_archived_as_the_reviewed_pdf(self):
        before = set((self.root / source.FOLDER).rglob('*'))
        with patch.object(collector, 'fetch_bytes', return_value=b'<HTML>blocked</HTML>'):
            with self.assertRaisesRegex(ValueError, 'NOT_PDF_RESPONSE'):
                collector.capture(self.root, self.case, [])
        self.assertEqual(before, set((self.root / source.FOLDER).rglob('*')))

    def test_offline_verification_reports_missing_capture_and_review_binding_failure(self):
        report, status = collector.verify_offline(self.root, CUT)
        self.assertEqual(status, 0); self.assertEqual(report['verified_issuers'], ['2483'])
        mp = self.root / source.FOLDER / 'manifest.json'
        mp.unlink()
        report, status = collector.verify_offline(self.root, CUT)
        self.assertEqual(status, 1); self.assertEqual(report['states']['2483']['status'], 'ORIGINAL_CAPTURE_PENDING')
        self.manifest['config_sha256'] = '0'*64; mp.write_text(json.dumps(self.manifest))
        report, status = collector.verify_offline(self.root, CUT)
        self.assertEqual(status, 1); self.assertIn('VERSION_MISMATCH', report['errors'][0]['error'])

    def test_linked_archives_and_review_config_invalidate_model_cache(self):
        for name in ('prices/latest_manifest.json', 'fundamentals/latest_scan.json',
                     'latest_manifest.json', 'evidence/v880/manifest.json'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{}')
        before = model_source_state(self.root)
        self.path.write_bytes(self.path.read_bytes() + b'changed')
        self.assertNotEqual(before, model_source_state(self.root))

    def test_cli_starts_without_pythonpath_or_repository_working_directory(self):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        result = subprocess.run([sys.executable, str(Path(collector.__file__).resolve()), '--help'],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_distinct_disposals_are_added_once_and_remaining_valuation_gain_is_only_disclosed(self):
        multiple_fixture(self.root)
        reviews, states, errors = source.load(self.root, CUT)
        self.assertFalse(errors); self.assertFalse(states)
        review = reviews['2483']
        self.assertEqual(review['excluded_positive_gain_k'], 175)
        self.assertEqual([x['amount_k'] for x in review['excluded_gain_components']], [125, 50])
        self.assertEqual(review['remaining_volatile_positive_gain_k'], 25)
        self.assertFalse(review['remaining_components_verified'])

    def test_duplicate_ids_facts_or_numeric_rectangles_cannot_count_a_gain_twice(self):
        raw, original, *_ = multiple_fixture(self.root)
        for duplicate in ('id', 'fact_key', 'geometry', 'shifted_geometry', 'remaining_overlap'):
            case = copy.deepcopy(original)
            if duplicate == 'geometry':
                case['facts']['second'] = copy.deepcopy(case['facts']['first'])
            elif duplicate == 'shifted_geometry':
                case['facts']['second'] = copy.deepcopy(case['facts']['first'])
                case['facts']['second']['bbox'][0] -= .1
            elif duplicate == 'remaining_overlap':
                case['remaining_volatile_items'][0]['fact_key'] = 'first'
            else:
                case['gain_items'][1][duplicate] = case['gain_items'][0][duplicate]
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'DUPLICATE_SELECTED_COMPONENT'):
                source.inspect_pdf(raw, case)

    def test_no_selected_gain_and_reused_cashflow_evidence_are_rejected(self):
        raw, original, *_ = multiple_fixture(self.root)
        case = copy.deepcopy(original); case['gain_items'] = []
        with self.assertRaisesRegex(ValueError, 'ITEM_COUNT_INVALID'):
            source.inspect_pdf(raw, case)
        case = copy.deepcopy(original); case['gain_items'][1]['corroborating_fact_key'] = 'first_cf'
        with self.assertRaisesRegex(ValueError, 'CORROBORATION_REUSED'):
            source.inspect_pdf(raw, case)

    def test_each_gain_requires_matching_cashflow_sign_and_losses_are_not_added_back(self):
        raw, original, *_ = multiple_fixture(self.root)
        case = copy.deepcopy(original)
        case['gain_items'][0]['corroborating_multiplier'] = 1
        with self.assertRaisesRegex(ValueError, 'CORROBORATION_MISMATCH'):
            source.inspect_pdf(raw, case)
        case = copy.deepcopy(original); case['gain_items'][1]['profit_effect_multiplier'] = -1
        with self.assertRaisesRegex(ValueError, 'NO_LOSS_ADDBACK'):
            source.inspect_pdf(raw, case)

    def write_book(self, config, manifest):
        (self.root / source.CONFIG).write_text(json.dumps(config))
        (self.root / source.FOLDER / 'manifest.json').write_text(json.dumps(manifest))

    def future_case(self):
        case = copy.deepcopy(self.case)
        case.update(code='8110', source_url=source.URLS['8110'], reviewed_at='2026-11-09T08:00:00+08:00')
        return case

    def test_future_new_issuer_with_no_capture_never_invalidates_current_review(self):
        self.receipt['review_case_sha256'] = source.case_sha(self.case)
        self.manifest['captures'] = [self.receipt]
        self.config['cases'].append(self.future_case())
        self.write_book(self.config, self.manifest)
        reviews, states, errors = source.load(self.root, CUT)
        self.assertIn('2483', reviews); self.assertFalse(errors)
        self.assertEqual(states['8110']['status'], 'SOURCE_AVAILABLE_AFTER_ESTIMATE')
        self.assertFalse(states['8110']['blocks_current_decision'])
        reviews, states, errors = source.load(self.root, '2026-11-09T09:00:00+08:00')
        self.assertIn('2483', reviews); self.assertFalse(errors)
        self.assertTrue(states['8110']['blocks_current_decision'])

    def test_legacy_book_migration_accepts_only_exact_unchanged_cases(self):
        (self.root / source.LEGACY_CONFIG).write_bytes((self.root / source.CONFIG).read_bytes())
        self.config['cases'].append(self.future_case())
        self.write_book(self.config, self.manifest)
        reviews, _, errors = source.load(self.root, CUT)
        self.assertIn('2483', reviews); self.assertFalse(errors)
        self.config['cases'][0]['selected_gain_label'] = 'AMENDED REVIEW'
        self.write_book(self.config, self.manifest)
        reviews, states, errors = source.load(self.root, CUT)
        self.assertNotIn('2483', reviews); self.assertTrue(states['2483']['blocks_current_decision'])
        self.assertIn('VERSION_MISMATCH', errors[0]['error'])

    def test_tampered_legacy_book_cannot_grant_compatibility(self):
        (self.root / source.LEGACY_CONFIG).write_bytes((self.root / source.CONFIG).read_bytes() + b' ')
        self.config['cases'].append(self.future_case()); self.write_book(self.config, self.manifest)
        _, states, errors = source.load(self.root, CUT)
        self.assertTrue(states['2483']['blocks_current_decision'])
        self.assertIn('VERSION_MISMATCH', errors[0]['error'])

    def test_collector_reparses_before_binding_review_and_keeps_original_capture_clock(self):
        previous = dict(self.receipt, review_case_sha256='0'*64)
        with patch.object(collector, 'fetch_bytes', side_effect=AssertionError('original is already archived')):
            upgraded = collector.capture(self.root, self.case, [previous])
        self.assertEqual(upgraded['captured_at'], previous['captured_at'])
        self.assertEqual(upgraded['review_case_sha256'], source.case_sha(self.case))
        self.assertEqual(upgraded['gzip_sha256'], previous['gzip_sha256'])

    def test_one_changed_case_blocks_only_itself_and_legacy_config_participates_in_cache(self):
        first = copy.deepcopy(self.case); first_receipt = dict(self.receipt, review_case_sha256=source.case_sha(first))
        _, second, second_receipt, *_ = fixture(self.root, code='6763')
        second_receipt['review_case_sha256'] = source.case_sha(second)
        config = dict(schema=source.SCHEMA, formal_quality_pass=False, cases=[first, second])
        first['selected_gain_label'] = 'AMENDED REVIEW'
        manifest = dict(self.manifest, captures=[first_receipt, second_receipt])
        self.write_book(config, manifest)
        reviews, states, errors = source.load(self.root, CUT)
        self.assertIn('6763', reviews); self.assertNotIn('2483', reviews)
        self.assertEqual(len(errors), 1); self.assertTrue(states['2483']['blocks_current_decision'])
        for name in ('prices/latest_manifest.json', 'fundamentals/latest_scan.json', 'latest_manifest.json', 'evidence/v880/manifest.json'):
            p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{}')
        before = model_source_state(self.root)
        (self.root / source.LEGACY_CONFIG).write_text('{}')
        self.assertNotEqual(before, model_source_state(self.root))


class OneoffForecastAdmission(unittest.TestCase):
    def data(self):
        data = FakeData()
        code = 'SYNTHETIC_A'
        primary = data.evidence['primary'].pop(code)
        data.detailed_values = lambda key, period: primary['prior_full_year'] if period == '2025-Q4' else primary['values']
        review = dict(code=code, anchor_period='2025-Q4', reported_fy_nonoperating_k=20,
                      excluded_positive_gain_k=5, formal_quality_pass=False)
        data.oneoff_reviews = {code: review}
        return data

    def test_verified_gain_changes_only_nonoperating_input_and_keeps_gates_pending(self):
        data = self.data()
        with patch.object(data, 'oneoff_reviews', {}):
            before = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        after = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertEqual(after['base']['nonoperating_k'], before['base']['nonoperating_k'] - 5)
        for key in ('revenue_k', 'gross_margin', 'opex_ratio', 'tax_rate', 'parent_fraction', 'shares', 'pe'):
            self.assertEqual(before['base'][key], after['base'][key], key)
        adjustment = after['nonoperating_bridge']['oneoff_original_adjustment']
        self.assertAlmostEqual(adjustment['before_target_price_counterfactual'], before['base']['target_price'])
        self.assertEqual(after['gates']['nonoperating_components']['status'], 'PENDING')
        self.assertFalse(after['formal_Aplus'])

    def test_component_normalized_baseline_is_not_deducted_twice(self):
        data = FakeData()
        data.oneoff_reviews = self.data().oneoff_reviews
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertEqual(result['base']['nonoperating_k'], 20)
        self.assertFalse(result['nonoperating_bridge']['oneoff_original_adjustment']['applied'])

    def test_changed_anchor_does_not_subtract_old_gain_from_new_year(self):
        data = self.data()
        data.oneoff_reviews['SYNTHETIC_A']['anchor_period'] = '2024-Q4'
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertEqual(result['base']['nonoperating_k'], 20)
        self.assertFalse(result['nonoperating_bridge']['oneoff_original_adjustment']['applied'])

    def test_restatement_mismatch_and_invalid_source_never_restore_old_ranking(self):
        data = self.data()
        data.oneoff_reviews['SYNTHETIC_A']['reported_fy_nonoperating_k'] = 21.1
        with self.assertRaisesRegex(ValueError, 'RECONCILED'):
            estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        data.oneoff_review_states = {'SYNTHETIC_A': dict(blocks_current_decision=True)}
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertFalse(result['rankable'])

    def test_existing_failed_nonoperating_gate_is_not_weakened_to_pending(self):
        data = self.data()
        data.evidence['certificates']['SYNTHETIC_A'] = {'nonoperating_components': dict(status='FAIL')}
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertEqual(result['gates']['nonoperating_components']['status'], 'FAIL')

    def test_remaining_nonoperating_loss_is_not_floored_to_zero(self):
        data = self.data()
        data.oneoff_reviews['SYNTHETIC_A']['excluded_positive_gain_k'] = 25
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertEqual(result['base']['nonoperating_k'], -5)

    def test_pending_original_blocks_the_inflated_baseline_until_capture(self):
        data = self.data(); data.oneoff_reviews = {}
        data.oneoff_review_states = {'SYNTHETIC_A': dict(status='ORIGINAL_CAPTURE_PENDING', blocks_current_decision=True)}
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertFalse(result['rankable']); self.assertNotIn('base', result)
        self.assertIn('PENDING', result['status'])

    def test_remaining_volatile_gain_is_not_silently_deducted_or_certified(self):
        data = self.data(); data.oneoff_reviews['SYNTHETIC_A']['remaining_volatile_positive_gain_k'] = 3
        result = estimate(data, ('TEST', 'SYNTHETIC_A'), CAL, ASOF, '2027-12-31')
        self.assertEqual(result['base']['nonoperating_k'], 15)
        self.assertIn('REVIEWED_FAIR_VALUE_GAIN_REMAINS_IN_BASELINE_RECURRENCE_UNCERTIFIED', result['warning_flags'])
        self.assertFalse(result['formal_Aplus'])
