import unittest
from scripts.shoe_revenue_monitor import normalize

class RevenueTests(unittest.TestCase):
    def row(self, month="11510", code="9802", revenue="1,234,567", yoy="25.5"):
        return {"公司代號": code, "資料年月": month, "當月營收": revenue, "去年同月增減(%)": yoy, "上月比較增減(%)": "3.0"}

    def test_roc_month(self):
        d = normalize([self.row()], "2026-10")
        self.assertEqual(d["9802"]["revenue_thousand_twd"], 1234567)
        self.assertEqual(d["9802"]["yoy_pct"], 25.5)

    def test_gregorian_month(self):
        self.assertIn("9802", normalize([self.row(month="202610")], "2026-10"))

    def test_wrong_month_rejected(self):
        self.assertEqual(normalize([self.row(month="11509")], "2026-10"), {})

    def test_missing_month_rejected(self):
        row = self.row()
        del row["資料年月"]
        self.assertEqual(normalize([row], "2026-10"), {})

    def test_invalid_numeric_rejected(self):
        self.assertEqual(normalize([self.row(revenue="--")], "2026-10"), {})

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            normalize([self.row(), self.row()], "2026-10")

    def test_negative_revenue_rejected(self):
        self.assertEqual(normalize([self.row(revenue="-1")], "2026-10"), {})

    def test_nonwatch_rejected(self):
        self.assertEqual(normalize([self.row(code="9999")], "2026-10"), {})

    def test_missing_yoy_rejected(self):
        self.assertEqual(normalize([self.row(yoy="")], "2026-10"), {})

if __name__ == "__main__":
    unittest.main()
