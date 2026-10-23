import copy
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.filing_vintages import filing_view,coverage_at
from tw_model_v880.execution import validate_cost_policy,COST_FIELDS
from tw_model_v880.validation_io import immutable_registration
from tw_model_v880.contracts import canonical_hash
from scripts.institutional_shadow import cost_policy_status,trial_spec


def version(period='2025-Q1',upload='2025-05-08T17:05:07+08:00',captured='2026-10-22T09:00:00+00:00',sha='a'*64,correction='無'):
    return dict(index_row=dict(code='6206',financial_period=period,official_upload_at=upload,
                latest_reported_correction=correction),captured_at_utc=captured,
                reference=dict(path='filings/receipt.json',sha256='c'*64),
                pdf_original=dict(path='filings/a.pdf',sha256=sha))


class FilingClocks(unittest.TestCase):
    def test_real_archive_cannot_be_backdated_to_its_official_upload_label(self):
        sources=[version()]
        real=filing_view(sources,'2025-05-10T00:00:00+08:00')
        self.assertEqual(real['documents'],[])
        historical=filing_view(sources,'2025-05-10T00:00:00+08:00',mode='official_upload_reconstruction')
        self.assertEqual(len(historical['documents']),1)
        self.assertTrue(historical['documents'][0]['reconstruction_candidate_only'])
        self.assertFalse(historical['full_model_input_PIT_complete'])

    def test_exact_seconds_and_fixed_lag_apply_across_timezones(self):
        sources=[version()]
        before=filing_view(sources,'2025-05-09T09:05:06+00:00',mode='official_upload_reconstruction')
        after=filing_view(sources,'2025-05-09T09:05:07+00:00',mode='official_upload_reconstruction')
        self.assertEqual(before['documents'],[])
        self.assertEqual(len(after['documents']),1)
        with self.assertRaisesRegex(ValueError,'TIMEZONE_REQUIRED'):
            filing_view(sources,'2025-05-09T09:05:07')

    def test_future_revision_is_never_used_before_its_upload(self):
        original=version()
        later=version(upload='2025-06-01T10:00:00+08:00',sha='b'*64)
        report=filing_view([original,later],'2025-05-15T00:00:00+08:00',mode='official_upload_reconstruction')
        self.assertEqual(report['documents'][0]['pdf_original']['sha256'],'a'*64)

    def test_conflicting_same_clock_bytes_are_not_arbitrarily_chosen(self):
        report=filing_view([version(),version(sha='b'*64)],'2026-10-24T00:00:00+08:00')
        self.assertEqual(report['documents'],[])
        self.assertIn('AMBIGUOUS_BYTES',report['rejected_versions'][0]['reason'])

    def test_latest_correction_does_not_fall_back_to_old_clean_observation(self):
        original=version(captured='2026-10-21T09:00:00+00:00')
        report=filing_view([original,version(correction='更正待核對')],'2026-10-24T00:00:00+08:00')
        self.assertEqual(report['documents'],[])
        self.assertIn('EXACT_REVISION_HISTORY',report['rejected_versions'][0]['reason'])

    def test_repeated_identical_archive_preserves_earliest_capture(self):
        original=version(captured='2026-10-21T09:00:00+00:00')
        report=filing_view([original,version()],'2026-10-24T00:00:00+08:00')
        self.assertEqual(report['documents'][0]['original_capture_at'],original['captured_at_utc'])

    def test_two_documents_cannot_be_misreported_as_eight_quarters(self):
        report=coverage_at([version(),version(period='2024-Q4')],
                          '2025-06-30T23:59:59+08:00',['6206','9802'])
        self.assertEqual(len(report['issuer_coverage'][0]['missing_required_periods']),6)
        self.assertFalse(report['issuer_coverage'][0]['eight_quarter_document_clock_coverage'])
        self.assertIsNone(report['issuer_coverage'][1]['last_available_period'])


class FixedResearchCosts(unittest.TestCase):
    def test_incomplete_or_impossible_exit_costs_never_become_fixed(self):
        self.assertFalse(cost_policy_status({})[0])
        self.assertFalse(cost_policy_status(None)[0])
        self.assertFalse(cost_policy_status(dict(dict.fromkeys(COST_FIELDS,0.),minimum_fee_ntd=-1))[0])
        with self.assertRaisesRegex(ValueError,'AGGREGATE_EXIT'):
            validate_cost_policy(dict(dict.fromkeys(COST_FIELDS,0.),sell_slippage_rate=.6,half_spread_rate=.6))

    def test_fixed_cost_status_still_waits_for_verified_outcomes(self):
        fixed,status=cost_policy_status(dict.fromkeys(COST_FIELDS,0.))
        self.assertTrue(fixed)
        self.assertEqual(status,'AWAITING_FUTURE_EXECUTION_AND_ACTION_REVIEWED_OUTCOME_SOURCES')

    def test_new_cost_policy_creates_new_trial_without_rewriting_null_cost_history(self):
        current=dict(strategy_variant_sha256='a'*64,target_date='2027-12-31')
        baseline=dict(strategy_variant_sha256='b'*64)
        config=dict(cost_policy=None,reference_capital_ntd=10000000,
                    risk_policy=dict(max_daily_participation=.05),
                    experiment_policy=dict(minimum_nonoverlapping_oos_periods=60))
        old=trial_spec(current,baseline,config)
        new=trial_spec(current,baseline,dict(config,cost_policy=dict.fromkeys(COST_FIELDS,0.)))
        self.assertNotEqual(old['trial_id'],new['trial_id'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=immutable_registration(root,old,'2026-10-22T09:00:00+00:00')
            immutable_registration(root,new,'2026-10-22T10:00:00+00:00')
            again=immutable_registration(root,old,'2026-10-23T10:00:00+00:00')
            self.assertEqual(first,again)
            self.assertIsNone(again['spec']['cost_policy'])


if __name__=='__main__':unittest.main()
