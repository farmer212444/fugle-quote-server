"""Audit all 450 official TWSE source bodies, plus mutation tests."""
import copy
import gzip
import json
import unittest

from scripts.v8107_footwear_official_pb_archive_audit import ROOT,validate,verify_month


def archive_first(code="9802"):
    with gzip.open(ROOT/f"{code}_full_originals.json.gz","rb") as f:
        return json.load(f)["months"][0]


class VerifyFootwearPBArchiveTests(unittest.TestCase):
    def test_offline_full_originals_reparse_sha_and_totals(self):
        r=validate()
        self.assertEqual(r["source_body_sha256_verified_count"],450)
        self.assertEqual(r["unique_official_daily_pb_points_recomputed"],9050)
        self.assertTrue(r["complete_10y_is_only_for_9904_9802_9910"])
        self.assertTrue(r["IPO_censoring_no_prelisting_backfill"])
        self.assertFalse(r["original_MOPS_quarterly_notes_and_2027_ROE_audited"])
        self.assertTrue(r["no_source_to_2027_Aplus_automatic_promotion"])
        self.assertEqual(r["per_issuer"]["9802"]["latest_asof_pb"],.92)
        self.assertEqual(r["per_issuer"]["9904"]["latest_asof_pb"],.42)

    def test_archive_content_sha_mismatch_is_rejected(self):
        m=archive_first()
        m["sha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"ORIGINAL_BODY_SHA256_MISMATCH"):
            verify_month("9802",m)

    def test_modified_normalized_rows_never_override_original_source(self):
        m=archive_first()
        if m["rows"]:
            m["rows"][0]["pb"]=55.55
            with self.assertRaisesRegex(ValueError,"NORMALIZED_PB_NOT_IDENTICAL_TO_SOURCE_BYTES"):
                verify_month("9802",m)
        else:
            self.fail("Expected an observed PB in the first 2016-10 month")

    def test_false_issuer_reference_url_is_blocked(self):
        m=archive_first()
        m["url"]="https://example.invalid/"
        with self.assertRaisesRegex(ValueError,"MONTH_SOURCE_URL_NOT_OFFICIAL_TWSE"):
            verify_month("9802",m)

    def test_archive_has_reliable_month_source_identifiers(self):
        m=archive_first("9904")
        self.assertGreater(verify_month("9904",m),0)
        with self.assertRaisesRegex(ValueError,"NONOK_OR_MISMATCHED_ORIGINAL_MONTH"):
            verify_month("6768",m)


if __name__=="__main__":
    unittest.main()
