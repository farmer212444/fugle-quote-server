import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.history_archive import archive_original, verify_original, observed_ohlc,quote_source_ready


class HistoricalOriginals(unittest.TestCase):
    def test_missing_open_is_never_replaced_with_close(self):
        row = observed_ohlc({'date': '2025-01-02', 'close': 100}, '--', 101, 99)
        self.assertIsNone(row['open'])
        self.assertEqual(row['high'], 101)
        self.assertFalse(row['fillability_verified'])

    def test_immutable_original_reuse_preserves_actual_capture_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            url = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20250101&stockNo=6206'
            raw = b'{"date":"2025-01-02"}'
            first = archive_original(root, 'TWSE', '6206-2025-01', url, raw, [])
            again = archive_original(root, 'TWSE', '6206-2025-01', url, raw, [])
            self.assertEqual(first, again)
            self.assertEqual(verify_original(root, first), raw)
            self.assertFalse(first['issuer_publication_pit_verified'])
            self.assertFalse(first['contemporaneous_universe_verified'])

    def test_changed_bytes_are_distinct_versions_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            url = 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=114/01/02'
            one = archive_original(root, 'TPEX', '2025-01-02', url, b'{"v":1}', {})
            two = archive_original(root, 'TPEX', '2025-01-02', url, b'{"v":2}', {})
            self.assertNotEqual(one['archive_path'], two['archive_path'])
            self.assertEqual(verify_original(root, one), b'{"v":1}')
            (root / one['archive_path']).write_bytes(gzip.compress(b'{"v":9}'))
            with self.assertRaisesRegex(ValueError, 'BYTES_MISMATCH'):
                verify_original(root, one)

    def test_path_escape_and_false_publisher_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, 'INVALID_IDENTITY'):
                archive_original(root, 'TWSE', '6206-2025-01', 'https://example.invalid/', b'{}', [])
            with self.assertRaisesRegex(ValueError, 'UNSAFE_PATH'):
                verify_original(root, {'receipt_path': '../outside.json'})

    def test_corrupt_deflate_stream_is_rejected_without_escaping_the_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            url='https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=114/01/02'
            original=archive_original(root,'TPEX','2025-01-02',url,b'{"v":1}',{})
            path=root/original['archive_path']
            damaged=bytearray(path.read_bytes());damaged[10]=7
            path.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,'COMPRESSION_CORRUPT'):
                verify_original(root,original)
            record=dict(original_archive=original,original_response_sha256=original['original_response_sha256'],
                        row=dict(open=100,high=101,low=99))
            self.assertFalse(quote_source_ready(root,record))

    def test_shared_market_original_cache_does_not_hide_another_issuers_missing_open_field(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            url='https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=114/01/02'
            original=archive_original(root,'TPEX','2025-01-02',url,b'{"test":true}',{})
            record=dict(original_archive=original,original_response_sha256=original['original_response_sha256'],
                        row=dict(open=100,high=101,low=99))
            verified=set()
            self.assertTrue(quote_source_ready(root,record,verified))
            self.assertEqual(len(verified),1)
            record['row']={'close':100}
            self.assertFalse(quote_source_ready(root,record,verified))


if __name__ == '__main__':
    unittest.main()
