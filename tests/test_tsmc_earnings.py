import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tw_model_v880.events import load_earnings_events, pdf_text
from tw_model_v880.model import estimate
from tw_model_v880.tsmc_earnings import parse_tsmc, SOURCE_KIND
from tests import test_institutional_controls as fixtures

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'tw-market-data/evidence/v880/originals/2330'
ASOF = '2026-10-24T12:00:00+08:00'


class TsmcOriginalAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((ARCHIVE / 'manifest.json').read_text())
        cls.doc = cls.bundle['documents'][0]
        cls.pdf = ROOT / 'tw-market-data' / cls.doc['archive_path']
        cls.pages = pdf_text(cls.pdf)

    def test_archived_original_millions_ntd_income_and_cash_reconcile(self):
        self.assertEqual(hashlib.sha256(self.pdf.read_bytes()).hexdigest(), self.doc['sha256'])
        facts = parse_tsmc(self.pages)
        self.assertEqual(facts['current']['revenue_k'], 3_898_727_000)
        self.assertEqual(facts['single_quarter']['parent_net_income_k'], 763_064_000)
        self.assertEqual(facts['current']['diluted_eps'], 78.75)
        self.assertEqual(facts['cashflow']['single_quarter_ocf_k'], 919_776_000)
        self.assertEqual(facts['cashflow']['ocf_k'] + facts['cashflow']['ppe_cash_flow_signed_k'], 1_112_146_000)
        self.assertFalse(facts['full_notes_and_auditor_review_complete'])

    def test_wrong_company_period_unit_currency_order_and_missing_column_reject(self):
        cases = [(0, 'TAIWAN SEMICONDUCTOR', 'ANOTHER SEMICONDUCTOR'),
                 (2, '2026\n2025\nYoY', '2025\n2024\nYoY'),
                 (3, 'Millions of New Taiwan Dollars', 'Thousands of New Taiwan Dollars'),
                 (2, 'YoY\nUSD', 'YoY USD'),
                 (2, 'USD\nNTD\n %', 'NTD\nUSD\n %'),
                 (2, '3,898,727', '')]
        for index, old, new in cases:
            with self.subTest(old=old):
                bad = list(self.pages)
                self.assertIn(old, bad[index])
                bad[index] = bad[index].replace(old, new, 1)
                with self.assertRaises(ValueError):
                    parse_tsmc(bad)

    def test_operating_reconciliation_rejects_a_material_number_change(self):
        bad = list(self.pages)
        bad[2] = bad[2].replace('2,302,014', '2,402,014', 1)
        with self.assertRaisesRegex(ValueError, 'RECONCILIATION'):
            parse_tsmc(bad)

    def test_cash_purchase_does_not_read_the_disposal_line(self):
        bad = list(self.pages)
        bad[3] = bad[3].replace('(1,289,971)', '1,289,971', 1)
        with self.assertRaisesRegex(ValueError, 'PPE_CASHFLOW_SIGN'):
            parse_tsmc(bad)

    def archive(self, root):
        folder = root / 'evidence/v880/originals/2330'
        shutil.copytree(ARCHIVE, folder)
        return folder

    def test_capture_clock_and_later_full_quarter_control_availability(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self.archive(root)
            events, states = load_earnings_events(root, ASOF, '2026-Q2')
            self.assertEqual(events['2330']['source_kind'], SOURCE_KIND)
            self.assertEqual(events['2330']['available_at'], self.doc['captured_at_utc'])
            self.assertFalse(events['2330']['formal_quality_pass'])
            self.assertFalse(events['2330']['historical_issuer_publication_PIT_verified'])
            events, states = load_earnings_events(root, '2026-10-15T23:59:59+08:00', '2026-Q2')
            self.assertFalse(events)
            self.assertEqual(states['2330']['status'], 'FUTURE_CAPTURE_NOT_USED')
            events, states = load_earnings_events(root, ASOF, '2026-Q3')
            self.assertFalse(events)

    def test_changed_pdf_host_recipe_and_unsafe_path_isolate_issuer(self):
        for field, value in [('sha256', '0' * 64), ('source_url', 'https://example.invalid/FS.pdf'),
                             ('extraction_recipe', 'UNSUPPORTED'), ('archive_path', '../FS.pdf')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as t:
                root = Path(t)
                folder = self.archive(root)
                bundle = copy.deepcopy(self.bundle)
                bundle['documents'][0][field] = value
                (folder / 'manifest.json').write_text(json.dumps(bundle))
                events, states = load_earnings_events(root, ASOF, '2026-Q2')
                self.assertFalse(events)
                self.assertTrue(states['2330']['blocks_current_decision'])


class CondensedForecastIntegration(unittest.TestCase):
    def data(self):
        data, event = fixtures.EarningsForecastIntegration().data()
        event.update(source_kind=SOURCE_KIND, source_sha256='c' * 64,
                     disclosed_weighted_diluted_shares=100_000,
                     cashflow_period='2026-Q3',
                     cashflow=dict(ocf_k=20, ppe_cash_flow_signed_k=-10, cash_k=120,
                                   equipment_prepaid_signed_k=None,
                                   previous_ytd_ocf_k=-10, single_quarter_ocf_k=30))
        data.earnings_events = {'SYNTHETIC_A': event}
        return data, event

    def test_new_cash_period_and_nonoperating_policy_do_not_certify_full_notes(self):
        data, event = self.data()
        row = estimate(data, ('TEST', 'SYNTHETIC_A'), fixtures.CAL, fixtures.ASOF, '2027-12-31')
        self.assertEqual(row['cashflow_financial_period'], '2026-Q3')
        self.assertEqual(row['reviewed_financial_period'], '2026-Q2')
        self.assertEqual(row['liquidity']['fcf_after_ppe_k'], 10)
        self.assertEqual(row['base']['nonoperating_k'], 20)
        self.assertEqual(row['source_tier'], 'ISSUER_CONDENSED_ORIGINAL_STATEMENTS')
        self.assertFalse(row['formal_Aplus'])
        self.assertEqual(row['gates']['original_eight_quarter_statements']['status'], 'PENDING')

    def test_wrong_prior_cash_ytd_and_material_income_restatement_reject(self):
        data, event = self.data()
        event['cashflow']['previous_ytd_ocf_k'] = 2000
        with self.assertRaisesRegex(ValueError, 'CASHFLOW_NOT_RECONCILED'):
            estimate(data, ('TEST', 'SYNTHETIC_A'), fixtures.CAL, fixtures.ASOF, '2027-12-31')
        data, event = self.data()
        event['current']['parent_net_income_k'] += 1001
        with self.assertRaisesRegex(ValueError, 'RESTATEMENT_NOT_RECONCILED'):
            estimate(data, ('TEST', 'SYNTHETIC_A'), fixtures.CAL, fixtures.ASOF, '2027-12-31')


class SamePeriodReturnFeatures(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(ARCHIVE, self.root / 'evidence/v880/originals/2330')
        events, _ = load_earnings_events(self.root, ASOF, '2026-Q2')
        self.event = events['2330']
        self.row = dict(code='2330', market='TWSE', rankable=True,
                        financial_period='2026-Q3', cashflow_financial_period='2026-Q3',
                        price_date='2026-10-22', liquidity=dict(ocf_k=2_402_117_000),
                        fresh_earnings_update=dict(applied=True, event=self.event))

    def calculate(self):
        from scripts.return_model_search import feature_rows
        with patch('scripts.return_model_search.DailyTurnoverSnapshot'), \
             patch('scripts.return_model_search.liquidity_history', return_value=dict(last_date='2026-10-22', median20_turnover_ntd=1e9)), \
             patch('scripts.return_model_search.reviewed_momentum', return_value=None):
            return feature_rows(self.root, dict(all_model_rows=[self.row],
                                asof_price_date='2026-10-22', financial_last_quarter='2026-Q2'), ASOF)

    def test_issuer_q3_cfo_uses_q3_sales_without_marketwide_q3_file(self):
        rows, references, errors = self.calculate()
        self.assertFalse(errors)
        self.assertAlmostEqual(rows[0]['features']['ocf_to_sales'], 2_402_117 / 3_898_727)
        self.assertEqual(rows[0]['ocf_and_sales_period'], '2026-Q3')
        self.assertEqual(references[self.event['archive_path']], self.event['source_sha256'])

    def test_changed_original_leaves_cash_feature_missing_without_stale_denominator(self):
        (self.root / self.event['archive_path']).write_bytes(b'%PDF-tampered')
        rows, _, errors = self.calculate()
        self.assertIsNone(rows[0]['features']['ocf_to_sales'])
        self.assertTrue(rows[0]['recommendation_blocked'])
        self.assertEqual(errors[0]['feature'], 'ocf_to_sales')

    def test_cash_amount_from_another_source_or_period_is_not_mixed(self):
        self.row['liquidity']['ocf_k'] = 1_482_341_000
        rows, _, errors = self.calculate()
        self.assertIsNone(rows[0]['features']['ocf_to_sales'])
        self.assertTrue(rows[0]['recommendation_blocked'])
        self.assertIn('AMOUNT_MISMATCH', errors[0]['reason'])


if __name__ == '__main__':
    unittest.main()
