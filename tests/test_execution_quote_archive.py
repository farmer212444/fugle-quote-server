import gzip
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.execution_quote_archive import add_execution_fields,persist_price_originals


class QuoteArchive(unittest.TestCase):
    def test_close_is_not_a_substitute_for_missing_open(self):
        row=add_execution_fields(dict(date='2026-10-20',close=100),dict(ClosingPrice='100'),'TWSE')
        self.assertIsNone(row['open']);self.assertFalse(row['fillability_verified'])

    def test_observed_exchange_open_retained_without_asserting_fillability(self):
        for market,key in [('TWSE','OpeningPrice'),('TPEX','Open')]:
            row=add_execution_fields(dict(date='2026-10-20'),{key:'1,234.5'},market)
            self.assertEqual(row['open'],1234.5)
            self.assertFalse(row['fillability_verified'])

    def test_missing_negative_and_nonfinite_open_are_unavailable(self):
        for bad in ('--','nan','inf','-1',None,True):
            self.assertIsNone(add_execution_fields(dict(date='2026-10-20'),dict(Open=bad),'TPEX')['open'])

    def test_raw_sources_are_durable_reusable_and_not_execution_certificates(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);raw=root/'raw';raw.mkdir();out=root/'prices'
            payload=b'[{"synthetic":true}]';(raw/'market.json').write_bytes(payload)
            sha=hashlib.sha256(payload).hexdigest()
            path=persist_price_originals(out,raw,'2026-10-20','a'*64,{'TWSE':sha},{'TWSE':'https://example.invalid/synthetic'})
            receipt=json.loads(path.read_text());item=receipt['raw_archives']['TWSE']
            self.assertEqual(gzip.decompress((out/item['path']).read_bytes()),payload)
            self.assertFalse(receipt['fillability_verified'])
            again=persist_price_originals(out,raw,'2026-10-20','a'*64,{'TWSE':sha},{'TWSE':'https://example.invalid/synthetic'})
            self.assertEqual(json.loads(again.read_text()),receipt)

    def test_absent_original_bytes_do_not_make_a_success_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'BYTES_MISSING'):
                persist_price_originals(Path(t)/'prices',Path(t)/'missing','2026-10-20','a'*64,{'TWSE':'b'*64},{})

    def test_new_receipt_reuses_identical_original_in_legacy_gzip_without_rewriting(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);raw=root/'raw';raw.mkdir();out=root/'prices'
            payload=b'[{"synthetic":true}]';(raw/'market.json').write_bytes(payload)
            digest=hashlib.sha256(payload).hexdigest();sources={'TWSE':'https://example.invalid/synthetic'}
            first=persist_price_originals(out,raw,'2026-10-20','a'*64,{'TWSE':digest},sources)
            first_bytes=first.read_bytes()
            item=json.loads(first_bytes)['raw_archives']['TWSE'];archive=out/item['path']
            stream=io.BytesIO()
            with gzip.GzipFile(filename='prior-runtime.json',mode='wb',fileobj=stream,mtime=17,compresslevel=1) as gz:
                gz.write(payload)
            legacy=stream.getvalue();archive.write_bytes(legacy)
            self.assertNotEqual(legacy,gzip.compress(payload,mtime=0))
            second=persist_price_originals(out,raw,'2026-10-20','b'*64,{'TWSE':digest},sources)
            self.assertNotEqual(first,second)
            self.assertEqual(archive.read_bytes(),legacy)
            self.assertEqual(first.read_bytes(),first_bytes)
            self.assertEqual(json.loads(second.read_bytes())['raw_archives']['TWSE'],item)
            self.assertFalse(json.loads(second.read_bytes())['fillability_verified'])

    def test_new_receipt_rejects_corrupt_or_different_existing_original(self):
        for damaged in (b'not gzip',gzip.compress(b'[{"different":true}]',mtime=0)):
            with self.subTest(damaged=damaged),tempfile.TemporaryDirectory() as t:
                root=Path(t);raw=root/'raw';raw.mkdir();out=root/'prices'
                payload=b'[{"synthetic":true}]';(raw/'market.json').write_bytes(payload)
                digest=hashlib.sha256(payload).hexdigest();sources={'TWSE':'https://example.invalid/synthetic'}
                first=persist_price_originals(out,raw,'2026-10-20','a'*64,{'TWSE':digest},sources)
                item=json.loads(first.read_bytes())['raw_archives']['TWSE'];archive=out/item['path']
                archive.write_bytes(damaged)
                before={p:p.read_bytes() for p in (out/'originals').rglob('*') if p.is_file()}
                with self.assertRaisesRegex(ValueError,'PRICE_ORIGINAL_IMMUTABILITY_CONFLICT'):
                    persist_price_originals(out,raw,'2026-10-20','b'*64,{'TWSE':digest},sources)
                self.assertEqual(before,{p:p.read_bytes() for p in (out/'originals').rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
