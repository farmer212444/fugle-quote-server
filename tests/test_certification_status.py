import copy
import unittest
from tw_model_v880.certification_status import summarize_certification
from tw_model_v880.evidence import GATES


class CertificationStatusTests(unittest.TestCase):
    def test_price_drop_never_completes_missing_evidence_or_proves_no_opportunities(self):
        rows=[dict(rankable=True,base=dict(price_upside_pct=58.1),formal_Aplus=False,
                   gates={g:dict(status='PASS') for g in GATES})]
        original=copy.deepcopy(rows)
        status=summarize_certification(rows,dict(performance=None),{})
        self.assertEqual(status['price_only_Aplus_threshold_count'],1)
        self.assertEqual(status['fully_decided_issuers'],0)
        self.assertEqual(status['recorded_formal_Aplus_count'],0)
        self.assertEqual(status['status'],'CERTIFICATION_INCOMPLETE')
        self.assertFalse(status['zero_formal_is_proof_of_no_market_opportunities'])
        self.assertEqual(rows,original)

    def test_effective_pass_fail_and_unknown_are_separate_and_reconcile(self):
        rows=[dict(certification=dict(gates_passed=list(GATES))),
              dict(certification=dict(gates_failed=[GATES[0]],gates_pending=list(GATES[1:]))),{}]
        status=summarize_certification(rows,dict(performance=None),dict(equity_source_may_be_stale=True))
        self.assertEqual(status['fully_decided_issuers'],1)
        self.assertEqual(status['gate_counts'][GATES[0]],dict(PASS=1,FAIL=1,PENDING=1))
        self.assertEqual(status['gate_counts'][GATES[1]],dict(PASS=1,FAIL=0,PENDING=2))
        self.assertIn('REFERENCE_CLOSE_MAY_BE_STALE',status['blocking_reasons'])
        self.assertIn('PIT_RETURN_BACKTEST_INCOMPLETE',status['blocking_reasons'])
        for counts in status['gate_counts'].values():self.assertEqual(sum(counts.values()),3)

    def test_conflicting_decisions_and_empty_universe_remain_incomplete(self):
        row=dict(certification=dict(gates_passed=list(GATES),gates_failed=[GATES[0]]))
        self.assertEqual(summarize_certification([row],{}, {})['fully_decided_issuers'],0)
        self.assertEqual(summarize_certification([],{}, {})['status'],'CERTIFICATION_INCOMPLETE')
