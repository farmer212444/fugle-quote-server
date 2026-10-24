"""Official BWIBBU PB source parsing, IPO cutoff and completeness regression."""
import datetime
import json
import unittest
from scripts.v8107_footwear_official_pb_history import (
    STOCKS,parsed_month,audit_one,month_range,BEGIN,END,pct
)

def fixture(month="2026-10",code="9802",pb="0.92"):
    return json.dumps({
      "stat":"OK",
      "date":month.replace("-","")+"01",
      "fields":["日期","殖利率(%)","股利年度","本益比","股價淨值比","財報年/季"],
      "data":[["115年10月22日","1.4","114","12.35",pb,"115/2"]],
    }).encode("utf-8")


class TestFootwearPBOriginalHistory(unittest.TestCase):
    def test_official_roc_date_and_filing_period(self):
        rows,stat=parsed_month("9802","2026-10",fixture())
        self.assertEqual(stat,"OK")
        self.assertEqual(rows,[{"date":"2026-10-22","pb":.92,"financial_quarter":"115/2"}])

    def test_missing_filing_period_is_not_silently_accepted(self):
        raw=json.loads(fixture())
        raw["fields"][-1]="不明欄位"
        with self.assertRaisesRegex(ValueError,"OFFICIAL_PB_COLUMN_SCHEMA_CHANGED"):
            parsed_month("9802","2026-10",json.dumps(raw).encode())

    def test_pit_month_year_check(self):
        with self.assertRaisesRegex(ValueError,"INCORRECT_MONTH_OR_DUPLICATE"):
            parsed_month("9802","2026-09",fixture())

    def test_non_ok_no_data_is_not_a_real_price(self):
        rows,stat=parsed_month("6965","2017-03",b'{"stat":"查無資料","data":[]}')
        self.assertEqual(rows,[])
        self.assertEqual(stat,"查無資料")
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_TWSE_STAT"):
            parsed_month("6965","2026-10",b'{"stat":"服務維護中","data":[]}')

    def test_unlisted_stocks_do_not_claim_ten_year_history(self):
        self.assertEqual(max(BEGIN,datetime.date.fromisoformat(STOCKS["6965"][1])),
                         datetime.date(2025,3,7))
        self.assertEqual(max(BEGIN,datetime.date.fromisoformat(STOCKS["6768"][1])),
                         datetime.date(2021,4,22))
        self.assertEqual(max(BEGIN,datetime.date.fromisoformat(STOCKS["9802"][1])),BEGIN)

    def test_three_probe_months_cannot_be_called_ten_year_median(self):
        a=[
            {"month":"2016-10","stat":"OK","rows":[]},
            {"month":"2026-10","stat":"OK","rows":[]}
        ]
        self.assertFalse(audit_one("9904",a,"full")["historical_extremes_and_median_certified"])
        self.assertFalse(audit_one("9904",a,"probe")["historical_extremes_and_median_certified"])
        self.assertEqual(audit_one("9904",a,"full")["asof_2026_10_22_pb"],None)

    def test_missing_months_are_explicit(self):
        a=[{"month":"2026-10","stat":"OK","rows":[
             {"date":"2026-10-22","pb":.42,"financial_quarter":"115/2"}
        ]}]
        r=audit_one("9904",a,"full")
        self.assertEqual(r["asof_2026_10_22_pb"],.42)
        self.assertFalse(r["historical_extremes_and_median_certified"])
        self.assertGreater(len(r["post_listing_missing_months"]),100)
        self.assertFalse(r["has_full_10_year_listing_history"] is False)

    def test_different_endpoint_not_allowed_in_row(self):
        raw=json.loads(fixture(pb="0"))
        with self.assertRaisesRegex(ValueError,"INVALID_PB_NUMBER"):
            parsed_month("9802","2026-10",json.dumps(raw).encode())
        raw=json.loads(fixture(pb="10000"))
        with self.assertRaisesRegex(ValueError,"INVALID_PB_NUMBER"):
            parsed_month("9802","2026-10",json.dumps(raw).encode())

    def test_window_month_count_and_percentiles(self):
        self.assertEqual(len(list(month_range(BEGIN,END))),121)
        self.assertAlmostEqual(pct([1,2,3,4,5],.25),2)
        self.assertAlmostEqual(pct([1,2,3,4,5],.5),3)

    def test_duplicate_day_rejected(self):
        raw=json.loads(fixture())
        raw["data"].append(raw["data"][0])
        with self.assertRaisesRegex(ValueError,"INCORRECT_MONTH_OR_DUPLICATE"):
            parsed_month("9802","2026-10",json.dumps(raw).encode())


if __name__=="__main__":
    unittest.main()
