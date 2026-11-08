"""Bounded transport recovery never bypasses original-source validation."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch
import urllib.error
import urllib.request

from scripts import early_bulk_earnings as intake


class Response(io.BytesIO):
    status = 200

    def geturl(self):
        return intake.URLS['TWSE']


class EarlyBulkTransportTests(unittest.TestCase):
    def request(self):
        return urllib.request.Request(intake.URLS['TWSE'])

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_transient_502_recovers_without_changing_original_bytes(self, opened, sleep):
        opened.side_effect = [urllib.error.HTTPError(self.request().full_url, 502, 'gateway', {}, None),
                              Response(b'original bytes')]
        self.assertEqual(intake.fetch_bytes(self.request(), 5, 20), b'origi')
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(opened.call_args.kwargs, {'timeout': 20})
        sleep.assert_called_once_with(1)

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_repeated_transient_errors_stop_after_three_attempts(self, opened, sleep):
        opened.side_effect = urllib.error.HTTPError(self.request().full_url, 503, 'gateway', {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            intake.fetch_bytes(self.request(), 100, 25)
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_forbidden_and_source_identity_fail_without_retry(self, opened, sleep):
        opened.side_effect = urllib.error.HTTPError(self.request().full_url, 403, 'forbidden', {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            intake.fetch_bytes(self.request(), 100, 20)
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()
        opened.reset_mock(side_effect=True)
        opened.return_value = Response(b'wrong endpoint')
        with self.assertRaisesRegex(ValueError, 'REDIRECT_INVALID'):
            intake.fetch_bytes(self.request(), 100, 20, expected_url='https://example.invalid/')
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_timeouts_and_url_errors_share_the_same_attempt_budget(self, opened, sleep):
        opened.side_effect = [TimeoutError('timeout'), urllib.error.URLError('connection reset'), Response(b'ok')]
        self.assertEqual(intake.fetch_bytes(self.request(), 100, 20), b'ok')
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_short_retry_after_is_respected(self, opened, sleep):
        opened.side_effect = [urllib.error.HTTPError(self.request().full_url, 429, 'rate limited',
                              {'Retry-After': '4'}, None), Response(b'ok')]
        self.assertEqual(intake.fetch_bytes(self.request(), 100, 20), b'ok')
        sleep.assert_called_once_with(4)

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_long_server_cooldown_is_not_cut_short(self, opened, sleep):
        opened.side_effect = urllib.error.HTTPError(self.request().full_url, 429, 'rate limited',
                                                   {'Retry-After': '3600'}, None)
        with self.assertRaises(urllib.error.HTTPError):
            intake.fetch_bytes(self.request(), 100, 20)
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()

    @patch.object(intake.time, 'sleep')
    @patch.object(intake.urllib.request, 'urlopen')
    def test_invalid_body_is_not_retried_or_archived(self, opened, sleep):
        opened.return_value = Response(b'not a financial table')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                intake.capture(Path(folder), 'TWSE')
            self.assertEqual(list(Path(folder).rglob('*')), [])
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()
