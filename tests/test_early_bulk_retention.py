"""Late or invalid MOPS notices cannot overwrite an older, SHA-verified source."""
import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.early_bulk_earnings import MAX_LAST_GOOD_AGE_DAYS,verify_retained_last_good
from tw_model_v880.early_bulk import FOLDER,SCHEMA,URLS,sha

NOW=dt.datetime.fromisoformat("2026-11-12T06:00:00+00:00")
CAPTURED=dt.datetime.fromisoformat("2026-11-10T06:00:00+00:00")

def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")

def prepare(root):
    root=Path(root)
    raw=json.dumps([{"公司代號":"6206","年度":"115","季別":"3"}]).encode()
    zipped=gzip.compress(raw,mtime=0)
    rel=Path(FOLDER)/"TWSE"/(sha(raw)+".raw.gz")
    full=root/rel
    full.parent.mkdir(parents=True,exist_ok=True)
    full.write_bytes(zipped)
    receipt=dict(market="TWSE",source_url=URLS["TWSE"],
                 archive_path=rel.as_posix(),bytes=len(raw),
                 raw_sha256=sha(raw),gzip_sha256=sha(zipped),
                 captured_at=CAPTURED.isoformat())
    old=dict(schema=SCHEMA,
             requested_issuers=[dict(market="TWSE",code="6206")],
             captures=[receipt],announcements=[],formal_quality_pass=False,
             retrospective_PIT_verified=False)
    manifest=root/FOLDER/"manifest.json"
    save(manifest,old)
    return full,manifest

class StrictLastGoodSourceTests(unittest.TestCase):
    def test_original_manifest_is_reused_only_as_old_verified_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,manifest=prepare(root)
            previous=manifest.read_bytes()
            report=verify_retained_last_good(root,[dict(market="TWSE",code="6206")],NOW)
            self.assertEqual(report["verified_retained_receipts"],1)
            self.assertEqual(report["missing_latest_requested_issuers"],[])
            self.assertEqual(report["prior_manifest_sha256"],sha(previous))
            self.assertTrue(report["older_source_not_a_current_observation"] if
                "older_source_not_a_current_observation" in report else
                report["latest_observation_is_not_new"])
            self.assertFalse(report["formal_quality_pass"])
            self.assertFalse(report["model_PIT_or_Aplus_advanced"])
            self.assertEqual(previous,manifest.read_bytes())

    def test_new_issuer_is_reported_missing_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            r=verify_retained_last_good(root,[
                dict(market="TWSE",code="6206"),
                dict(market="TWSE",code="9802")],NOW)
            self.assertEqual(r["missing_latest_requested_issuers"],
                             [dict(market="TWSE",code="9802")])

    def test_tampered_original_archive_is_not_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive,manifest=prepare(root)
            archive.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                verify_retained_last_good(root,[dict(market="TWSE",code="6206")],NOW)

    def test_stale_old_receipts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            late=NOW+dt.timedelta(days=MAX_LAST_GOOD_AGE_DAYS+2)
            with self.assertRaisesRegex(ValueError,"SOURCE_TOO_OLD_OR_FUTURE"):
                verify_retained_last_good(root,[dict(market="TWSE",code="6206")],late)

    def test_no_or_untrusted_previous_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(ValueError,"MANIFEST_MISSING"):
                verify_retained_last_good(root,[dict(market="TWSE",code="6206")],NOW)
            _,manifest=prepare(root)
            old=json.loads(manifest.read_text());old["formal_quality_pass"]=True
            save(manifest,old)
            with self.assertRaisesRegex(ValueError,"MANIFEST_SCOPE_INVALID"):
                verify_retained_last_good(root,[dict(market="TWSE",code="6206")],NOW)

    def test_wrong_issuer_in_last_good_or_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            with self.assertRaisesRegex(ValueError,"DUPLICATED_ISSUER"):
                verify_retained_last_good(root,[
                    dict(market="TWSE",code="6206"),
                    dict(market="TWSE",code="6206")],NOW)
            with self.assertRaisesRegex(ValueError,"MARKET_SOURCE_MISSING"):
                verify_retained_last_good(root,[
                    dict(market="TPEX",code="6206")],NOW)

if __name__=="__main__":
    unittest.main()
