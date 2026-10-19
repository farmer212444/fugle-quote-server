import unittest
from scripts.v886_9802_early_revalue import num, revalue

class EarlyQ3Tests(unittest.TestCase):
    def test_numeric_validation(self):
        self.assertIsNone(num(None))
        self.assertIsNone(num(True))
        self.assertEqual(num("18.4"),18.4)

    def test_no_early_q3_needed_after_full_market_rollover(self):
        research=dict(model="V8.8.2",estimate_vintage="2026-10-19T18:00:00+08:00",
                      asof_price_date="2026-10-16")
        full=dict(model="V8.8.2",estimate_vintage=research["estimate_vintage"],
                  asof_price_date=research["asof_price_date"],
                  financial_last_quarter="2026-Q3")
        result=revalue(research,full,{}, {})
        self.assertEqual(result["status"],"QUARTER_ALREADY_IN_MAIN_MODEL")
        self.assertFalse(result["certified_Aplus"])

    def test_wrong_quarter_receipt_fails_closed(self):
        research=dict(model="V8.8.2",estimate_vintage="2026-10-19T18:00:00+08:00",
                      asof_price_date="2026-10-16")
        full=dict(model="V8.8.2",estimate_vintage=research["estimate_vintage"],
                  asof_price_date=research["asof_price_date"],
                  financial_last_quarter="2026-Q2")
        with self.assertRaisesRegex(ValueError,"RECEIPT_NOT_ADMISSIBLE"):
            revalue(research,full,{}, {})
if __name__=="__main__":unittest.main()
