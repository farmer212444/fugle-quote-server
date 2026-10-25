"""A dated reset must affect dilution only after real, issuer-bound capture."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from scripts.refresh_v881_capital import capture_known_resets,KNOWN_TWD_RESETS
from tw_model_v880.capital import apply_capital_terms,parse_twd_reset
from tw_model_v880.math import share_scenarios


def announcement():
    # The structured anti-dilution layout has no parenthesized issuer ticker.
    # Zero placeholders are not evidence that the outstanding bond was redeemed.
    return ('<html><head><script>債券代碼：99991</script></head><body>'
            '<h1>高技:公告高技股份有限公司國內第一次無擔保轉換公司債'
            '(簡稱：高技一，代碼：54391)自115年07月28日起，轉換價格自300元調整為293.6元。</h1>'
            '<p>事實發生日起始日 : 20260728</p>'
            '<p>因應措施 : 因高技辦理除息作業，依據高技一發行及轉換辦法規定轉換價格應予以調整，'
            '故自115年07月28日起，轉換價格由300元調整為293.6元。</p>'
            '<p>現行已流通在外證券總額 : 0</p><p>債券代碼 : 54391</p>'
            '<p>本月底發行餘額 : 0</p>推薦新聞<p>債券代碼：99991</p></body></html>').encode()


class StructuredResetTests(unittest.TestCase):
    def test_title_body_date_and_bond_agree_without_issuer_ticker(self):
        result=parse_twd_reset(announcement(),'5439','54391')
        self.assertEqual(result,dict(conversion_price=293.6,previous_conversion_price=300,
                                    effective_at='2026-07-28T00:00:00+08:00'))

    def test_conflicting_body_or_wrong_instrument_cannot_supply_price(self):
        replacements=[('債券代碼 : 54391','債券代碼 : 54392'),
                      ('代碼：54391','代碼：54392'),
                      ('由300元調整為293.6元','由300元調整為280元'),
                      ('故自115年07月28日','故自115年07月29日'),
                      ('事實發生日起始日 : 20260728','事實發生日起始日 : 20260729')]
        for old,new in replacements:
            with self.subTest(change=old),self.assertRaises(ValueError):
                parse_twd_reset(announcement().replace(old.encode(),new.encode()),'5439','54391')
        with self.assertRaises(ValueError):parse_twd_reset(announcement(),'5438','54381')

    def test_hidden_or_related_news_are_not_a_reset(self):
        raw=announcement().decode().replace('<script>債券代碼：99991</script>','')
        for wrapped in ('<script>'+raw+'</script>','推薦新聞'+raw):
            with self.subTest(wrapped=wrapped[:12]),self.assertRaises(ValueError):
                parse_twd_reset(wrapped.encode(),'5439','54391')

    def test_invalid_effective_date_cannot_create_terms(self):
        raw=announcement().replace(b'07',b'13')
        with self.assertRaises(ValueError):parse_twd_reset(raw,'5439','54391')


class ResetCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'evidence/v880'
        self.evidence={'bonds':{'5439':[dict(code='54391',face=1_999_700_000,
                         currency='TWD',conversion_price=300,current_terms_verified=False)]}}
        self.response=MagicMock();self.response.__enter__.return_value=self.response
        self.response.status=200;self.response.geturl.return_value=KNOWN_TWD_RESETS[0]['url']
        self.response.read.return_value=announcement()
        self.ledger=self.out/'capital_terms/5439.json'

    def capture(self):
        with patch('scripts.refresh_v881_capital.urllib.request.urlopen',return_value=self.response):
            return capture_known_resets(self.evidence,self.out)

    def data(self):
        return SimpleNamespace(root=self.root,path=lambda p:self.root/p,
                               receipt=lambda *a:None,errors=[],evidence=copy.deepcopy(self.evidence))

    def test_capture_hash_clock_and_dilution_preserve_outstanding_face(self):
        before=copy.deepcopy(self.evidence);status=self.capture()
        self.assertEqual(status['captured_issuers'],['5439']);self.assertFalse(status['failed_sources'])
        self.assertEqual(self.evidence,before)  # Dated loader, not capture, applies terms.
        book=json.loads(self.ledger.read_text());source=book['sources'][0]
        self.assertEqual(gzip.decompress((self.root/source['path']).read_bytes()),announcement())
        self.assertEqual(source['sha256'],hashlib.sha256(announcement()).hexdigest())
        self.assertEqual(source['available_at'],source['fetched_at'])
        self.assertGreater(dt.datetime.fromisoformat(source['available_at']),
                           dt.datetime.fromisoformat(source['published_at']))
        data=self.data();apply_capital_terms(data,book['checked_at'])
        self.assertFalse(data.errors);bond=data.evidence['bonds']['5439'][0]
        self.assertEqual(bond['face'],1_999_700_000);self.assertEqual(bond['conversion_price'],293.6)
        shares=share_scenarios(92_975_752,[bond])
        self.assertAlmostEqual(shares['cb_additional_shares'],1_999_700_000/293.6)
        self.assertFalse(shares['fully_diluted_shares_certified']);self.assertFalse(book['formal_share_certification'])

    def test_capture_cannot_be_used_at_an_earlier_vintage(self):
        self.capture();book=json.loads(self.ledger.read_text());data=self.data()
        earlier=(dt.datetime.fromisoformat(book['checked_at'])-dt.timedelta(seconds=1)).isoformat()
        apply_capital_terms(data,earlier)
        self.assertEqual(data.evidence,self.evidence);self.assertTrue(data.errors)

    def test_existing_issuer_book_and_first_capture_never_overwritten(self):
        self.capture();first=self.ledger.read_bytes()
        with patch('scripts.refresh_v881_capital.urllib.request.urlopen') as fetch:
            result=capture_known_resets(self.evidence,self.out)
        fetch.assert_not_called();self.assertEqual(self.ledger.read_bytes(),first)
        self.assertEqual(result['existing_issuer_books_preserved'],['5439'])

    def test_fetch_failure_or_different_source_facts_cannot_create_ledger(self):
        for raw,url,status in [(b'blocked',KNOWN_TWD_RESETS[0]['url'],200),
                               (announcement(),'https://unrelated.invalid/',200),
                               (announcement(),KNOWN_TWD_RESETS[0]['url'],503),
                               (announcement().replace(b'293.6',b'290.0'),KNOWN_TWD_RESETS[0]['url'],200)]:
            with self.subTest(status=status,url=url):
                self.response.read.return_value=raw;self.response.geturl.return_value=url;self.response.status=status
                result=self.capture()
                self.assertTrue(result['failed_sources']);self.assertFalse(self.ledger.exists())
        with patch('scripts.refresh_v881_capital.urllib.request.urlopen',side_effect=OSError('outage')):
            self.assertTrue(capture_known_resets(self.evidence,self.out)['failed_sources'])

    def test_absent_or_redeemed_bond_does_not_reappear_from_a_reset_notice(self):
        self.evidence['bonds']={}
        with patch('scripts.refresh_v881_capital.urllib.request.urlopen') as fetch:
            capture_known_resets(self.evidence,self.out)
        fetch.assert_not_called();self.assertFalse(self.ledger.exists())


if __name__=='__main__':unittest.main()
