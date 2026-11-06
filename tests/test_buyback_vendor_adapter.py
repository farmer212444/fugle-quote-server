"""Pure synthetic fixtures: NO real prices or actual event-study results."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts import buyback_vendor_adapter as b


def make(**overrides):
    r = {
        "record_type":"BUYBACK","market":"TWSE","company_code":"1234",
        "company_name":"Fictional Company",
        "board_resolution_date":"2024-06-05","purpose":"EMPLOYEE_TRANSFER",
        "planned_shares":1000,"planned_start_date":"2024-06-06",
        "planned_end_date":"2024-08-05","completed":True,
        "executed_shares":800,"execution_rate_pct":80
    }
    r.update(overrides)
    return r


class VendorImportTests(unittest.TestCase):
    def test_completed_is_still_quarantined(self):
        rows, failures, skipped=b.normalize([make()],"a"*64)
        self.assertEqual(len(rows),1)
        self.assertEqual(failures,[])
        self.assertEqual(skipped,{})
        self.assertEqual(rows[0]["usable_as_announce_signal"],"false")
        self.assertEqual(rows[0]["usable_as_completion_signal"],"false")
        self.assertEqual(rows[0]["actual_disclosure_timestamp"],"")
        self.assertEqual(rows[0]["execution_rate_pct_at_capture"],80)

    def test_rejects_expost_incomplete(self):
        rows, failures, _=b.normalize([make(completed=False)],"a"*64)
        self.assertEqual(len(rows),0)
        self.assertIn("EX_POST_EXECUTION", failures[0]["reason"])

    def test_rejects_inconsistent_execution(self):
        rows, failures, _=b.normalize([make(executed_shares=400)],"a"*64)
        self.assertEqual(len(rows),0)
        self.assertIn("ARITHMETIC",failures[0]["reason"])

    def test_duplicates_and_out_of_window_cannot_inflate_count(self):
        rows, failures, skipped=b.normalize([make(),make(),make(
            board_resolution_date="2026-02-01"),make(market="PUBLIC")],"a"*64)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(failures),1)
        self.assertEqual(skipped["outside_2020_2025"],1)
        self.assertEqual(skipped["other_market"],1)

    def test_bad_then_valid_same_id_can_recover(self):
        rows, failures, skipped=b.normalize([make(executed_shares=300),make()],"a"*64)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(failures),1)

    def test_end_to_end_cannot_create_verified_backtest_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/"authorized_vendor_fixture.json"
            f.write_text(json.dumps([make()]),encoding="utf-8")
            target=Path(directory)/"out"
            report=b.run(f,target)
            self.assertEqual(report["candidates"],1)
            self.assertFalse(report["production_events_written"])
            self.assertFalse(report["source_provenance_verified"])
            self.assertEqual(report["verified_disclosure_timestamps"],0)
            self.assertTrue((target/"vendor_buyback_candidates_QUARANTINED.csv").is_file())
            self.assertFalse((target/"events_2020_2025.csv").exists())
            self.assertTrue(report["formal_a_plus_unchanged"])


if __name__=="__main__":
    unittest.main()
