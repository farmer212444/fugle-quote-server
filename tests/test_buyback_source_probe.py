"""Pure parser tests; mock rows are not Taiwanese-market observations."""
import json
import unittest
from scripts.buyback_source_probe import parse_tai50, rocdate, mops_response_status

class SourceProbeTests(unittest.TestCase):
    def test_roc_year(self):
        self.assertEqual(rocdate("1090102"),"2020-01-02")
        self.assertEqual(rocdate("115/10/22"),"2026-10-22")

    def test_future_month_is_rejected(self):
        sample=[{"Date":f"11510{i:02d}","Taiwan50TotalReturnIndex":str(100+i)}
                for i in range(1,14)]
        _,status=parse_tai50(json.dumps(sample).encode(),2020,1)
        self.assertEqual(status,"DATE_OUTSIDE_QUERY_MONTH")

    def test_valid_index_fixture_not_called_audited(self):
        sample=[{"Date":f"10901{i:02d}","Taiwan50TotalReturnIndex":str(100+i)}
                for i in range(1,14)]
        rows,status=parse_tai50(json.dumps(sample).encode(),2020,1)
        self.assertEqual(len(rows),13)
        self.assertEqual(status,"RESPONSE_MONTH_PARSED_NOT_INDEPENDENTLY_AUDITED")

    def test_mops_error_and_challenge_not_events(self):
        self.assertEqual(mops_response_status(b"<html>error</html>",200),
                         "HTML_BUT_NO_IDENTIFIED_BUYBACK_TABLE")
        self.assertEqual(mops_response_status(b"<html>captcha</html>",200),
                         "CHALLENGE_OR_SITE_ERROR")
        self.assertEqual(mops_response_status("<table>庫藏</table>".encode(),200),
                         "HTML_TABLE_PRESENT_UNPARSED")

if __name__=="__main__":
    unittest.main()
