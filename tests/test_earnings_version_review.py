import copy,datetime as dt,hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from tw_model_v880.data import MarketData,model_source_state
from tw_model_v880.events import load_earnings_events,pdf_text,parse_press,press_text_sha256

ROOT=Path(__file__).resolve().parents[1]/'tw-market-data'
ASOF='2026-10-25T12:00:00+08:00'
REVIEW='evidence/v880/earnings_version_reviews/9802_2026-Q3.json'
MANIFEST='evidence/v880/originals/9802/manifest.json'


class EarningsVersionReview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        bundle=json.loads((ROOT/MANIFEST).read_text())
        self.docs=[d for d in bundle['documents'] if d.get('title')=='2026年第三季自結財報新聞稿']
        self.assertEqual(len(self.docs),2)
        for doc in self.docs:
            target=self.root/doc['archive_path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/doc['archive_path'],target)
        self.review=json.loads((ROOT/REVIEW).read_text());(self.root/REVIEW).parent.mkdir(parents=True,exist_ok=True)
        self.save()
    def save(self):
        (self.root/MANIFEST).write_text(json.dumps(dict(issuer='9802',documents=self.docs)))
        (self.root/REVIEW).write_text(json.dumps(self.review))
    def load(self,asof=ASOF,reader=pdf_text,financial_period='2026-Q2'):
        return load_earnings_events(self.root,asof,financial_period,reader=reader)
    def blocked(self,**kwargs):
        events,states=self.load(**kwargs);self.assertNotIn('9802',events);self.assertTrue(states['9802']['blocks_current_decision']);return states['9802']

    def test_exact_two_originals_reconcile_with_dated_admission_and_no_quality_pass(self):
        pages=[pdf_text(self.root/d['archive_path']) for d in self.docs]
        self.assertEqual(press_text_sha256(pages[0]),press_text_sha256(pages[1]))
        self.assertEqual(parse_press(pages[0]),parse_press(pages[1]))
        events,states=self.load();event=events['9802']
        self.assertEqual(event['single_quarter']['basic_eps'],.68);self.assertEqual(event['current']['basic_eps'],2.46)
        self.assertEqual(event['available_at'],self.review['reviewed_at'])
        self.assertEqual(len(event['equivalent_originals']),2);self.assertFalse(event['formal_quality_pass'])
        self.assertFalse(event['historical_issuer_publication_PIT_verified']);self.assertFalse(states['9802']['blocks_current_decision'])
    def test_missing_review_keeps_conflicting_raw_versions_blocked(self):
        (self.root/REVIEW).unlink();self.assertIn('MULTIPLE_ORIGINAL',self.blocked()['reason'])
    def test_future_review_does_not_rewrite_earlier_decisions(self):
        cutoff=dt.datetime.fromisoformat(self.review['reviewed_at'])-dt.timedelta(microseconds=1)
        self.assertIn('REVIEW_FROM_FUTURE',self.blocked(asof=cutoff.isoformat())['reason'])
    def test_future_second_copy_does_not_overwrite_valid_first_event_state(self):
        events,states=self.load(asof='2026-10-21T12:00:00+08:00')
        self.assertIn('9802',events);self.assertEqual(states['9802']['status'],'NEW_ORIGINAL_EARNINGS_RECONCILED')
        self.assertNotIn('source_version_review',events['9802'])
    def test_unknown_third_copy_with_equal_text_and_figures_still_blocks(self):
        third=copy.deepcopy(self.docs[1]);target=self.root/'evidence/v880/originals/9802/unknown-copy.pdf'
        target.write_bytes((self.root/third['archive_path']).read_bytes()+b'\n%unreviewed PDF metadata copy\n')
        third.update(archive_path=target.relative_to(self.root).as_posix(),source_url='https://www.fulgentsun.com/img/News_Release/new.pdf',
                     sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size)
        self.assertEqual(parse_press(pdf_text(target)),parse_press(pdf_text(self.root/self.docs[1]['archive_path'])))
        self.docs.append(third);self.save();self.assertIn('UNREVIEWED_ORIGINAL_VERSION',self.blocked()['reason'])
    def test_known_hash_from_unreviewed_url_is_not_silently_admitted(self):
        self.docs[1]['source_url']='https://www.fulgentsun.com/img/News_Release/unreviewed.pdf';self.save()
        self.assertIn('UNREVIEWED_ORIGINAL_VERSION',self.blocked()['reason'])
    def test_changed_full_narrative_blocks_even_when_parsed_figures_equal(self):
        def reader(path):
            pages=pdf_text(path)
            if path.name==Path(self.docs[1]['archive_path']).name:pages[0]+=' 重大展望修訂'
            return pages
        self.assertIn('CONTENT_MISMATCH',self.blocked(reader=reader)['reason'])
    def test_changed_table_extraction_is_not_a_reviewed_forecast_override(self):
        def reader(path):
            pages=pdf_text(path)
            if path.name==Path(self.docs[1]['archive_path']).name:pages[1]=pages[1].replace('0.68','0.69')
            return pages
        self.assertIn('CONTENT_MISMATCH',self.blocked(reader=reader)['reason'])
    def test_companion_hash_failure_removes_whole_issuer_event(self):
        (self.root/self.docs[1]['archive_path']).write_bytes(b'%PDF-tampered')
        self.assertIn('ORIGINAL_BYTES_MISMATCH',self.blocked()['reason'])
    def test_review_identity_and_false_quality_claims_reject(self):
        original=copy.deepcopy(self.review)
        for key,value in [('issuer','6206'),('financial_period','2025-Q3'),('formal_quality_pass',True),
                          ('historical_issuer_publication_PIT_verified',True),('full_two_page_text_and_table_reviewed',False)]:
            with self.subTest(key=key):
                self.review=copy.deepcopy(original);self.review[key]=value;self.save();self.blocked()
    def test_order_independence_and_formal_quarter_supersedes_both_copies(self):
        first=self.load()[0]['9802']['event_sha256'];self.docs.reverse();self.save()
        self.assertEqual(self.load()[0]['9802']['event_sha256'],first)
        events,_=self.load(financial_period='2026-Q3');self.assertNotIn('9802',events)
    def test_review_and_all_originals_participate_in_cache_and_consumption_receipts(self):
        for name in ('prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json'):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
        before=model_source_state(self.root);self.review['review_note']='receipt update';self.save();after=model_source_state(self.root)
        self.assertNotEqual(before[REVIEW],after[REVIEW])
        for doc in self.docs:self.assertIn(doc['archive_path'],after)
        data=MarketData(ROOT,ASOF);paths={r['path'] for r in data.input_receipts}
        self.assertIn(REVIEW,paths)
        for doc in self.docs:self.assertIn(doc['archive_path'],paths)

if __name__=='__main__':unittest.main()
