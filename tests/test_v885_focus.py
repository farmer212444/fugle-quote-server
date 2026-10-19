import unittest
from unittest.mock import patch
from scripts import v884_evidence_probe as mod

class FocusSelectionTest(unittest.TestCase):
    def test_focus_adds_issuer_without_duplicate_or_certification(self):
        codes=['1111','2222','3333']
        jobs=[dict(code=c,market='TWSE',name=c,research_upside_pct=100-i,
                   evidence_state='PENDING_NOT_CERTIFIED',formal_Aplus=False,
                   pending_gates=[]) for i,c in enumerate(codes)]
        research=dict(model='V8.8.2',estimate_vintage='vintage',asof_price_date='2026-10-16',
                      data_scope=dict(model_rows=3),formal_Aplus_count=0)
        dispatch=dict(model='V8.8.2',vintage='vintage',price_date='2026-10-16',
                      tracked_issuer_count=3,all_issuer_jobs=jobs)
        fake_fin=dict(normalized_income_8q_count=0,normalized_cashflow_8q_count=0,
                      latest_primary_key_numbers_checked=False)
        fake_cap=dict(unverified_bond_terms=[])
        fake_liq=dict(twenty_day=None)
        with patch.object(mod,'financial_probe',return_value=fake_fin), \\
             patch.object(mod,'capital_probe',return_value=fake_cap), \\
             patch.object(mod,'liquidity_probe',return_value=fake_liq):
            out=mod.probe(research,dispatch,object(),[],[],top=1,focus_codes=['3333','1111'])
        self.assertEqual([r['code'] for r in out['top_priority_evidence']],['1111','3333'])
        self.assertEqual(out['newly_certified_Aplus'],0)
        self.assertTrue(all(not r['ready_for_formal_certification'] for r in out['top_priority_evidence']))

if __name__=='__main__': unittest.main()
