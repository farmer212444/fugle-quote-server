import json
import tempfile
import unittest
from pathlib import Path

from scripts.tw_chip_capture import (
    TWSE_FIELDS, TPEX_FIELDS, TDCC_FIELDS, decode_tdcc, iso_date,
    number, parse_twse, parse_tpex, parse_tdcc, save_capture,
)

class OfficialChipTests(unittest.TestCase):
    def twse_fixture(self):
        fields = list(TWSE_FIELDS.values())
        rows = []
        for i in range(300):
            code = str(1100 + i)
            rows.append([code, "測試" + code, "1,000", "5", "100", "200", "1,305"])
        return {"stat": "OK", "date": "20261019", "fields": fields, "data": rows}

    def tpex_fixture(self):
        return [dict(Date="1151019", SecuritiesCompanyCode=str(6000+i),
                     **{TPEX_FIELDS["foreign"]: "1", TPEX_FIELDS["foreign_dealer"]: "0", TPEX_FIELDS["trust"]: "-2",
                        TPEX_FIELDS["dealer"]: "0", TPEX_FIELDS["total"]: "-1"})
                for i in range(300)]

    def tdcc_fixture(self):
        rows = []
        for i in range(300):
            code = str(3000 + i)
            for grade, shares, pct in ((12, 100, "1"), (13, 100, "1"),
                                       (14, 100, "1"), (15, 100, "1"),
                                       (16, 0, "0"), (17, 2500, "100")):
                rows.append({TDCC_FIELDS["date"]: "20261016", TDCC_FIELDS["code"]: code,
                             TDCC_FIELDS["grade"]: str(grade),
                             TDCC_FIELDS["holders"]: "3",
                             TDCC_FIELDS["shares"]: str(shares),
                             TDCC_FIELDS["pct"]: pct})
        return rows

    def test_dates_and_signed_values(self):
        self.assertEqual(iso_date("1151019"), "2026-10-19")
        self.assertEqual(iso_date("2026/10/19"), "2026-10-19")
        self.assertEqual(number("(2,000)"), -2000)
        with self.assertRaises(ValueError):
            number("--")

    def test_twse_by_named_fields_includes_foreign_dealer(self):
        day, rows = parse_twse(self.twse_fixture())
        self.assertEqual(day, "2026-10-19")
        self.assertEqual(len(rows), 300)
        self.assertEqual(rows[0]["official_total_net_shares"], 1305)
        self.assertTrue(rows[0]["components_reconciled"])

    def test_twse_schema_change_fails_closed(self):
        f = self.twse_fixture()
        f["fields"][2] = "外陸資欄位已改名"
        with self.assertRaisesRegex(ValueError, "MISSING_FIELD"):
            parse_twse(f)

    def test_twse_invalid_number_is_not_zero(self):
        f = self.twse_fixture()
        f["data"][0][2] = "--"
        with self.assertRaisesRegex(ValueError, "INVALID_NUMERIC_CELL"):
            parse_twse(f)

    def test_tpex_negative_signed_shares(self):
        day, rows = parse_tpex(self.tpex_fixture())
        self.assertEqual(day, "2026-10-19")
        self.assertEqual(rows[0]["trust_net_shares"], -2)
        self.assertTrue(rows[0]["components_reconciled"])

    def test_tpex_rejects_mixed_dates(self):
        f = self.tpex_fixture()
        f[0]["Date"] = "1151016"
        with self.assertRaisesRegex(ValueError, "MIXED_DATES"):
            parse_tpex(f)

    def test_tdcc_grade_aggregate_and_csv(self):
        day, rows = parse_tdcc(self.tdcc_fixture())
        self.assertEqual(day, "2026-10-16")
        self.assertEqual(len(rows), 300)
        self.assertEqual(rows[0]["level_12_15_pct"], 4.0)
        columns = list(TDCC_FIELDS.values())
        csv_text = ",".join(columns) + "\n" + ",".join(["20261016", "3000", "12", "3", "100", "1.0"])
        self.assertEqual(len(decode_tdcc(csv_text.encode())), 1)

    def test_tdcc_official_json_bom_date_field(self):
        payload = self.tdcc_fixture()
        for record in payload:
            record["\ufeff資料日期"] = record.pop("資料日期")
        day, result = parse_tdcc(payload)
        self.assertEqual(day, "2026-10-16")
        self.assertEqual(len(result), 300)

    def test_tdcc_missing_grades_cannot_be_synthetic(self):
        f = [r for r in self.tdcc_fixture() if r[TDCC_FIELDS["grade"]] != "17"]
        with self.assertRaisesRegex(ValueError, "COVERAGE_TOO_LOW"):
            parse_tdcc(f)

    def test_snapshot_bytes_are_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            args = (d, "institutional", "2026-10-19", "TWSE",
                    b"test original bytes", [{"code": "1101"}], "https://www.twse.com.tw", "2026-10-19T20:00:00+08:00")
            a = save_capture(*args)
            b = save_capture(*args)
            self.assertEqual(a["raw_sha256"], b["raw_sha256"])
            wrong = (*args[:4], b"changed original bytes", *args[5:])
            with self.assertRaisesRegex(ValueError, "ORIGINAL_BYTES_CHANGED"):
                save_capture(*wrong)

    def test_reparse_same_immutable_original_preserves_prior_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            args = (out, "institutional", "2026-10-16", "TPEX")
            raw = b"identical official source body"
            first = save_capture(*args, raw, [{"code": "1234", "dealer": None}],
                                 "https://www.tpex.org.tw/openapi/v1/test", "2026-10-19T14:00:00+08:00")
            second = save_capture(*args, raw, [{"code": "1234", "dealer": 0}],
                                  "https://www.tpex.org.tw/openapi/v1/test", "2026-10-19T14:10:00+08:00")
            self.assertEqual(first["raw_sha256"], second["raw_sha256"])
            self.assertEqual(first["normalized_sha256"], second["parser_reinterpretation_from_previous_sha256"])
            prior = out / "normalized_revisions" / "institutional" / "2026-10-16" / "TPEX" / (first["normalized_sha256"] + ".json")
            self.assertTrue(prior.is_file())
            self.assertIsNone(json.loads(prior.read_text())[0]["dealer"])
            latest = out / "institutional" / "2026-10-16" / "TPEX.json"
            self.assertEqual(json.loads(latest.read_text())[0]["dealer"], 0)

if __name__ == "__main__":
    unittest.main()
