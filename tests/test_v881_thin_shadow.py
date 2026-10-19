import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.v881_thin_shadow import discover_shadow

class ThinShadowTests(unittest.TestCase):
    def setup_data(self):
        data=SimpleNamespace(
            history={("TWSE","1111"):{"2026-Q2":{"name":"modeled"}},
                     ("TPEX","2222"):{"2026-Q2":{"name":"thin"}},
                     ("TWSE","3333"):{"2026-Q2":{"name":"not thin"}}},
            period="2026-Q2",
            prices={
                ("TWSE","1111"):{"close":20,"volume_shares":1000000},
                ("TPEX","2222"):{"close":20,"volume_shares":50000},
                ("TWSE","3333"):{"close":20,"volume_shares":1000000}
            },
            revenue={"1111":{},"2222":{},"3333":{}},
            evidence={"master":{"1111":{},"2222":{},"3333":{}}})
        report={"estimate_vintage":"2026-10-19T14:00:00+08:00",
                "target_date":"2027-12-31",
                "all_model_row_summary":[{"code":"1111"}]}
        return data,report

    def test_separate_thin_lane_and_dont_reenter_primary(self):
        data,report=self.setup_data()
        with patch("scripts.v881_thin_shadow.estimate",
                   return_value={"code":"2222","rankable":False,"formal_Aplus":False,
                                 "formal_Aplusplus":False,"status":"PENDING"}) as fn:
            examined,eligible,rows,failures=discover_shadow(data,report,{"mock":1})
            self.assertEqual(examined,2)
            self.assertEqual(eligible,1)
            self.assertEqual(len(rows),1)
            self.assertEqual(len(failures),1)  # non-thin excluded for another reason
            self.assertEqual(fn.call_count,1)
            self.assertTrue(fn.call_args.kwargs["shadow_thin"])

    def test_any_certification_in_shadow_fails_closed(self):
        data,report=self.setup_data()
        with patch("scripts.v881_thin_shadow.estimate",
                   return_value={"code":"2222","rankable":True,"formal_Aplus":True}) as fn:
            _,_,rows,failures=discover_shadow(data,report,{"mock":1})
            self.assertEqual(rows,[])
            self.assertTrue(any("MUST_NEVER_BE_CERTIFIED" in f["reason"] for f in failures))

if __name__=="__main__":
    unittest.main()
