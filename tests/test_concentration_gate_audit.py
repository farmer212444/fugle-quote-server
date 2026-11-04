import copy
import datetime as dt
import unittest
from types import SimpleNamespace

from scripts.concentration_gate_audit import (
    admitted_observations, issuance_sensitivity, next_quarter_revenue,
    quarter_cash, sensitivity,
)


class ConcentrationAuditTests(unittest.TestCase):
    def test_quarter_cash_uses_ytd_difference_and_does_not_double_count_q4(self):
        cash={f'2025-Q{q}':{'operating_cashflow_ytd_k':v}
              for q,v in ((1,10),(2,25),(3,45),(4,70))}
        self.assertEqual([quarter_cash(cash,f'2025-Q{q}') for q in range(1,5)],
                         [10,15,20,25])
        self.assertEqual(sum(quarter_cash(cash,f'2025-Q{q}') for q in range(1,5)),70)

    def test_missing_ytd_baseline_does_not_become_zero(self):
        cash={'2026-Q2':{'operating_cashflow_ytd_k':100}}
        self.assertIsNone(quarter_cash(cash,'2026-Q2'))
        cash['2026-Q1']={'operating_cashflow_ytd_k':True}
        self.assertIsNone(quarter_cash(cash,'2026-Q2'))

    def test_capital_raise_is_not_cash_already_received_or_a_new_fair_value(self):
        base=dict(parent_profit_k=1000000,shares=100000000,eps=10,pe=15)
        before=copy.deepcopy(base)
        r=issuance_sensitivity(base,80,100000000,8000000,62)
        self.assertEqual(r['gross_proceeds_ntd'],496000000)
        self.assertAlmostEqual(r['fixed_profit_eps'],1000000000/108000000)
        self.assertAlmostEqual(r['theoretical_ex_rights_price'],
                               (80*100000000+62*8000000)/108000000)
        self.assertFalse(r['is_already_issued'])
        self.assertFalse(r['is_fair_value'])
        self.assertFalse(r['actual_ex_rights_price_verified'])
        self.assertEqual(base,before)

    def test_existing_diluted_denominator_is_not_diluted_twice(self):
        # The model denominator already includes 10m potential CB shares.
        base=dict(parent_profit_k=1100000,shares=110000000,eps=10,pe=15)
        r=issuance_sensitivity(base,80,100000000,8000000,62)
        self.assertAlmostEqual(r['fixed_profit_eps'],1100000000/118000000)
        self.assertEqual(r['post_issue_common_shares_if_completed'],108000000)

    def observation(self):
        return dict(code='4771',kind='SPECIFIC_CASE_WITHDRAWN',
            published_on='2025-09-12',first_observed_at='2026-11-04T23:00:00+08:00',
            source_url='https://issuer.example/notice.pdf',source_tier='ISSUER_ORIGINAL_WEB_REVIEW')

    def test_old_publication_new_discovery_is_not_backdated_into_pit(self):
        book={'observations':[self.observation()]}
        self.assertEqual(admitted_observations(book,'4771','2026-11-04T22:59:59+08:00'),[])
        self.assertEqual(len(admitted_observations(book,'4771','2026-11-04T23:00:00+08:00')),1)
        self.assertEqual(admitted_observations(book,'2330','2026-11-04T23:00:00+08:00'),[])

    def test_unsupported_source_or_future_publication_is_not_admitted(self):
        for update in ({'source_tier':'ANONYMOUS_TARGET_PRICE'},
                       {'source_url':'http://issuer.example/notice'},
                       {'published_on':'2026-11-05'}):
            o={**self.observation(),**update}
            with self.assertRaises(ValueError):
                admitted_observations({'observations':[o]},'4771','2026-11-04T23:00:00+08:00')

    def test_sensitivity_has_no_probability_rating_or_downside_bound(self):
        base=dict(eps=10,pe=15,shares=100000000)
        r=sensitivity(base,100,.8,.8)
        self.assertAlmostEqual(r['price'],96)
        self.assertAlmostEqual(r['price_upside_pct'],-4)
        self.assertFalse(r['is_fair_value'])
        self.assertFalse(r['is_downside_bound'])
        self.assertNotIn('formal_Aplus',r)

    def test_next_quarter_revenue_subtracts_ytd_on_both_sides(self):
        key=('TWSE','6625')
        data=SimpleNamespace(period='2026-Q2',revenue_month='2026-09',
            revenue={'6625':dict(ytd_revenue_k=3243098,last_year_ytd_revenue_k=2966869)},
            history={key:{'2026-Q2':dict(revenue_ytd_k=2158509),
                          '2025-Q2':dict(revenue_ytd_k=1791454)}})
        r=next_quarter_revenue(data,key)
        self.assertEqual(r['current_quarter_revenue_k'],1084589)
        self.assertEqual(r['prior_quarter_revenue_k'],1175415)
        self.assertLess(r['yoy_pct'],0)
        self.assertTrue(r['revenue_growth_is_not_profit_growth'])
        data.revenue_month='2026-08'
        self.assertIsNone(next_quarter_revenue(data,key))


if __name__=='__main__':
    unittest.main()
