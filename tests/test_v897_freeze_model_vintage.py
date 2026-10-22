"""Prospective frozen model vintage is auditable, not a historical PIT backfill."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v897_freeze_model_vintage import freeze, load_inputs, sha, verify_frozen_receipt

VINTAGE="2026-10-21T07:20:00+08:00"
NOW=dt.datetime.fromisoformat("2026-10-21T00:10:00+00:00")


class FrozenVintageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        (self.base/"VERSION").write_text("V8.8.2\n",encoding="utf-8")
        self.root=self.base/"tw-market-data"
        (self.root/"rankings").mkdir(parents=True)
        (self.root/"prices").mkdir(parents=True)
        (self.root/"fundamentals").mkdir(parents=True)
        (self.root/"evidence/v880").mkdir(parents=True)
        self.reference=b'[{"code":"1111","market":"TWSE","date":"2026-10-20","close":40}]\n'
        (self.root/"prices/2026-10-20.json").write_bytes(self.reference)
        self.sources={
            "prices/latest_manifest.json":{"date":"2026-10-20",
                "path":"tw-market-data/prices/2026-10-20.json",
                "normalized_sha256":sha(self.reference)},
            "fundamentals/latest_scan.json":{"last_eligible_quarter":"2026-Q2"},
            "latest_manifest.json":{"period":"2026-09"},
            "evidence/v880/manifest.json":{"json_sha256":"a"*64}}
        for name,obj in self.sources.items():
            (self.root/name).write_text(json.dumps(obj),encoding="utf-8")
        self.full={"estimate_vintage":VINTAGE,
                   "all_model_rows":[{"market":"TWSE","code":"1111"},
                                     {"market":"TWSE","code":"2222"}]}
        self.full_raw=json.dumps(self.full,separators=(",",":")).encode()
        self.full_gz=gzip.compress(self.full_raw,mtime=0)
        (self.root/"rankings/v880_full_results.json.gz").write_bytes(self.full_gz)
        self.research={
            "model":"V8.8.2","estimate_vintage":VINTAGE,
            "asof_price_date":"2026-10-20","revenue_month":"2026-09",
            "financial_last_quarter":"2026-Q2","target_date":"2027-12-31",
            "formal_Aplus_count":0,"model_code_sha256":"b"*64,
            "data_scope":{"model_rows":2},
            "full_results":{"path":"v880_full_results.json.gz",
                            "sha256":sha(self.full_gz),
                            "json_sha256":sha(self.full_raw)}
        }
        self.rewrite_research()

    def rewrite_research(self):
        (self.root/"rankings/latest_research.json").write_text(
            json.dumps(self.research),encoding="utf-8")

    def test_current_real_run_archive_contains_full_universe_and_exact_quotes(self):
        out=freeze(self.root,NOW,"V8.8.2","c"*40)
        self.assertEqual(out["status"],"FROZEN_NEW_VINTAGE_NOT_PIT_CERTIFIED")
        self.assertEqual(out["issuer_count"],2)
        receipt=verify_frozen_receipt(self.root/out["path"])
        self.assertEqual(receipt["model_repo_commit_before_generated_files"],"c"*40)
        self.assertFalse(receipt["out_of_sample_trading_backtest_verified"])
        self.assertFalse(receipt["historical_original_filing_PIT_verified"])
        self.assertEqual(receipt["issuer_market_reference_date"],"2026-10-20")
        self.assertEqual((self.root/out["path"]).parent.joinpath(
            "reference_prices.json").read_bytes(),self.reference)
        later=freeze(self.root,NOW,"V8.8.2","d"*40)
        self.assertEqual(later["status"],"VINTAGE_ALREADY_ARCHIVED")
        self.assertEqual(receipt,verify_frozen_receipt(self.root/later["path"]))

    def test_tampering_and_fake_review_claims_rejected(self):
        out=freeze(self.root,NOW,"V8.8.2")
        receipt_path=self.root/out["path"]
        folder=receipt_path.parent
        frozen_quote=folder/"reference_prices.json"
        frozen_quote.write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError,"FROZEN_VINTAGE_BYTES_TAMPERED"):
            verify_frozen_receipt(receipt_path)
        frozen_quote.write_bytes(self.reference)
        data=json.loads(receipt_path.read_text())
        data["formal_point_in_time_gate_pass"]=True
        receipt_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"FALSE_PIT_BACKTEST"):
            verify_frozen_receipt(receipt_path)

    def test_reject_future_vintage_and_cross_date_quotes(self):
        self.research["estimate_vintage"]="2026-10-22T07:20:00+08:00"
        self.rewrite_research()
        with self.assertRaisesRegex(ValueError,"MODEL_VINTAGE_FROM_FUTURE"):
            freeze(self.root,NOW,"V8.8.2")
        self.research["estimate_vintage"]=VINTAGE
        self.research["asof_price_date"]="2026-10-21"
        self.rewrite_research()
        with self.assertRaisesRegex(ValueError,"PRICE_MANIFEST_NOT_FROM_RESEARCH_VINTAGE"):
            freeze(self.root,NOW,"V8.8.2")

    def test_reject_full_universe_hash_or_model_version_mismatch(self):
        self.research["full_results"]["sha256"]="0"*64
        self.rewrite_research()
        with self.assertRaisesRegex(ValueError,"FULL_MARKET_RESEARCH_GZIP_HASH_MISMATCH"):
            freeze(self.root,NOW,"V8.8.2")
        self.research["full_results"]["sha256"]=sha(self.full_gz)
        self.rewrite_research()
        with self.assertRaisesRegex(ValueError,"RESEARCH_MODEL_DIFFERS_FROM_MAIN_VERSION"):
            freeze(self.root,NOW,"V8.8.3")

    def test_reject_future_price_path_and_changed_original_price_hash(self):
        data=json.loads((self.root/"prices/latest_manifest.json").read_text())
        data["path"]="../outside-quote.json"
        (self.root/"prices/latest_manifest.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"UNSAFE_FROZEN_INPUT_PATH"):
            load_inputs(self.root,NOW,"V8.8.2")
        data["path"]="tw-market-data/prices/2026-10-20.json"
        (self.root/"prices/latest_manifest.json").write_text(json.dumps(data))
        (self.root/"prices/2026-10-20.json").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"REFERENCE_QUOTE_ORIGINAL_SNAPSHOT_HASH_MISMATCH"):
            load_inputs(self.root,NOW,"V8.8.2")

    def test_receipt_cannot_change_model_identity_without_changing_frozen_payload(self):
        out=freeze(self.root,NOW,'V8.8.2');path=self.root/out['path']
        original=path.read_text()
        for key,value in (('model_code_sha256','c'*64),('strategy_variant_sha256','d'*64),
                          ('financial_last_quarter','2026-Q3'),('issuer_market_reference_date','2026-10-19')):
            with self.subTest(key=key):
                receipt=json.loads(original);receipt[key]=value;path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError,'FROZEN_MODEL_IDENTITY_MISMATCH'):
                    verify_frozen_receipt(path)
        path.write_text(original)

    def test_archive_clock_cannot_precede_estimate_creation(self):
        out=freeze(self.root,NOW,'V8.8.2');path=self.root/out['path']
        receipt=json.loads(path.read_text());receipt['archived_at_utc']='2026-10-20T00:00:00+00:00'
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'FROZEN_ARCHIVE_BEFORE_ESTIMATE'):
            verify_frozen_receipt(path)


if __name__=="__main__":
    unittest.main()
