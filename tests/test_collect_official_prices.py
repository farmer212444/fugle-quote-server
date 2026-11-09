"""Exercise atomic publication, source originals and asynchronous feeds."""
import datetime as dt
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect_official_prices import capture, fetch_openapi, URLS
from scripts.v8a4_market_close_recovery import recover
from tests.test_v8a4_market_close_recovery import fixture


class Response(io.BytesIO):
    status = 200


def api_bytes(market, day, close='100.00'):
    date = str(int(day[:4]) - 1911) + day[5:7] + day[8:10]
    start = 1100 if market == 'TWSE' else 6000
    rows = []
    for code in range(start, start + 320):
        if market == 'TWSE':
            rows.append(dict(Date=date, Code=str(code), Name='SYNTHETIC', ClosingPrice=close,
                             OpeningPrice='95.00', TradeVolume='12000', TradeValue='1200000'))
        else:
            rows.append(dict(Date=date, SecuritiesCompanyCode=str(code), SecuritiesCompanyName='SYNTHETIC',
                             Close=close, Open='95.00', TradingShares='12000', TransactionAmount='1200000'))
    return json.dumps(rows).encode()


class OfficialPriceIntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'tw-market-data'
        self.raw = Path(temp.name) / 'raw'
        self.now = dt.datetime.fromisoformat('2026-11-09T16:30:00+08:00')

    def primary(self, dates=None, close='100.00'):
        dates = dates or dict(TWSE='2026-11-09', TPEX='2026-11-09')
        def fetch(market, url):
            with patch('scripts.collect_official_prices.urllib.request.urlopen',
                       return_value=Response(api_bytes(market, dates[market], close))):
                return fetch_openapi(market, url, self.raw)
        return fetch

    def collect(self, **kwargs):
        return capture(self.root, self.raw, now=self.now, fetch_fn=kwargs.pop('fetch_fn', self.primary()), **kwargs)

    def manifest(self):
        return json.loads((self.root / 'prices/latest_manifest.json').read_bytes())

    def test_same_session_both_sources_are_archived_before_manifest_and_not_execution_certified(self):
        result = self.collect()
        manifest = self.manifest()
        self.assertEqual((result['date'], result['rows']), ('2026-11-09', 640))
        self.assertEqual(manifest['path'], 'tw-market-data/prices/2026-11-09.json')
        prices = (self.root / 'prices/2026-11-09.json').read_bytes()
        self.assertEqual(hashlib.sha256(prices).hexdigest(), manifest['normalized_sha256'])
        receipt = json.loads((self.root / 'prices' / manifest['original_receipt_path']).read_bytes())
        self.assertFalse(receipt['fillability_verified'])
        for item in receipt['raw_archives'].values():
            raw = gzip.decompress((self.root / 'prices' / item['path']).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item['original_sha256'])
        self.assertEqual(json.loads(prices)[0]['open'], 95)
        self.assertEqual(result['formal_Aplus_added'], 0)

    def test_stale_twse_current_tpex_uses_exact_dated_fallback_without_mixing_sessions(self):
        calls = []
        def repair(market, day, old_date, raw_dir):
            calls.append((market, day, old_date))
            return recover(market, day, old_date, raw_dir, fetch=lambda _: fixture(market, day))
        result = self.collect(fetch_fn=self.primary(dict(TWSE='2026-11-06', TPEX='2026-11-09')),
                              recover_fn=repair)
        self.assertEqual(calls, [('TWSE', '2026-11-09', '2026-11-06')])
        self.assertEqual(result['dated_recovery_markets'], ['TWSE'])
        rows = json.loads((self.root / 'prices/2026-11-09.json').read_bytes())
        self.assertEqual({x['date'] for x in rows}, {'2026-11-09'})
        self.assertIn('date=20261109', self.manifest()['sources']['TWSE'])

    def test_second_market_recovery_failure_retains_all_last_good_published_prices(self):
        self.collect()
        before = {p: p.read_bytes() for p in (self.root / 'prices').rglob('*') if p.is_file()}
        self.now = dt.datetime.fromisoformat('2026-11-10T16:30:00+08:00')
        def repair(market, day, old_date, raw_dir):
            if market == 'TPEX':
                raise ValueError('TPEX_NOT_FINAL')
            return recover(market, day, old_date, raw_dir, fetch=lambda _: fixture(market, day))
        with self.assertRaisesRegex(ValueError, 'TPEX_NOT_FINAL'):
            self.collect(recover_fn=repair)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.root / 'prices').rglob('*') if p.is_file()})

    def test_unavailable_primary_reaches_official_fallback_without_imputing_quotes(self):
        def missing(market, url):
            raise OSError('unavailable')
        def repair(market, day, old_date, raw_dir):
            self.assertIsNone(old_date)
            return recover(market, day, old_date, raw_dir, fetch=lambda _: fixture(market, day))
        result = self.collect(fetch_fn=missing, recover_fn=repair)
        self.assertEqual(result['dated_recovery_markets'], ['TWSE', 'TPEX'])
        self.assertEqual(set(result['primary_errors']), {'TWSE', 'TPEX'})

    def test_source_digest_must_match_archived_raw_bytes_before_any_price_correction(self):
        self.collect()
        before = (self.root / 'prices/2026-11-09.json').read_bytes()
        manifest = (self.root / 'prices/latest_manifest.json').read_bytes()
        def bad_hash(market, url):
            rows, day, digest = self.primary(close='110.00')(market, url)
            return rows, day, 'a' * 64
        with self.assertRaisesRegex(ValueError, 'PRICE_ORIGINAL_SOURCE_BYTES_MISSING'):
            self.collect(fetch_fn=bad_hash)
        self.assertEqual((self.root / 'prices/2026-11-09.json').read_bytes(), before)
        self.assertEqual((self.root / 'prices/latest_manifest.json').read_bytes(), manifest)

    def test_same_date_correction_preserves_exact_prior_normalized_payload(self):
        self.collect()
        previous = (self.root / 'prices/2026-11-09.json').read_bytes()
        self.collect(fetch_fn=self.primary(close='110.00'))
        revision = self.root / 'prices/revisions/2026-11-09' / (hashlib.sha256(previous).hexdigest() + '.json')
        self.assertEqual(revision.read_bytes(), previous)
        self.assertEqual(json.loads((self.root / 'prices/2026-11-09.json').read_bytes())[0]['close'], 110)

    def test_identical_capture_reuses_original_receipt_and_manifest(self):
        self.collect()
        before = (self.root / 'prices/latest_manifest.json').read_bytes()
        result = self.collect()
        self.assertEqual(result['status'], 'LATEST_REFERENCE_UNCHANGED')
        self.assertEqual((self.root / 'prices/latest_manifest.json').read_bytes(), before)
        self.assertEqual(len(list((self.root / 'prices/originals/2026-11-09').glob('*.json'))), 1)

    def test_probe_can_observe_different_sessions_but_cannot_publish_or_recover(self):
        result = self.collect(probe_only=True, fetch_fn=self.primary(dict(TWSE='2026-11-06', TPEX='2026-11-09')),
                              recover_fn=lambda *args: self.fail('a probe cannot recover or publish'))
        self.assertEqual(result['status'], 'EARLY_PROBE_ONLY_NOT_PUBLISHED')
        self.assertFalse((self.root / 'prices').exists())

    def test_future_feed_or_published_date_regression_never_replaces_manifest(self):
        self.collect()
        before = (self.root / 'prices/latest_manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'AFTER_PUBLISHABLE_SESSION'):
            self.collect(fetch_fn=self.primary(dict(TWSE='2026-11-10', TPEX='2026-11-09')))
        self.assertEqual((self.root / 'prices/latest_manifest.json').read_bytes(), before)
        self.now = dt.datetime.fromisoformat('2026-11-06T16:30:00+08:00')
        with self.assertRaisesRegex(ValueError, 'EXCHANGE_DATE_REGRESSION'):
            self.collect(fetch_fn=self.primary(dict(TWSE='2026-11-06', TPEX='2026-11-06')))
        self.assertEqual((self.root / 'prices/latest_manifest.json').read_bytes(), before)

    def test_mixed_dates_and_duplicate_original_issuer_records_are_rejected(self):
        for field, value in [('Date', '1151106'), ('Code', '1101')]:
            with self.subTest(field=field):
                rows = json.loads(api_bytes('TWSE', '2026-11-09'))
                rows[0][field] = value
                with patch('scripts.collect_official_prices.urllib.request.urlopen', return_value=Response(json.dumps(rows).encode())):
                    with self.assertRaises(ValueError):
                        fetch_openapi('TWSE', URLS['TWSE'], self.raw)
        self.assertFalse((self.raw / 'twse.json').exists())

    def test_unaware_clock_rejected_before_network(self):
        self.now = dt.datetime(2026, 11, 9, 16, 30)
        with self.assertRaisesRegex(ValueError, 'TIMEZONE_REQUIRED'):
            self.collect(fetch_fn=lambda *args: self.fail('clock must be checked first'))

    def test_command_import_bootstrap_works_outside_repository(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/collect_official_prices.py'
        result = subprocess.run([sys.executable, str(script), '--help'], cwd=self.root.parent,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--probe-only', result.stdout)
