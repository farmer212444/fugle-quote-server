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
        # A fixed pre-Q3 fixture tests actual consumption without depending on
        # the live latest_scan quarter or admitting future production snapshots.
        # Only the minimal market manifests are synthetic; both PDFs and the
        # dated version review are copied unchanged from the real archive.
        import gzip
        def write(name,obj):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            raw=json.dumps(obj).encode();path.write_bytes(raw)
            return hashlib.sha256(raw).hexdigest()
        price='prices/fixture.json'
        price_hash=write(price,[dict(market='TWSE',code='9802',date='2026-10-23')])
        write('prices/latest_manifest.json',dict(date='2026-10-23',path=price,normalized_sha256=price_hash))
        write('latest_manifest.json',dict(period='2026-09',shards=[]))
        raw=json.dumps(dict(snapshot_available_at='2026-10-23T00:00:00+08:00')).encode()
        packed=gzip.compress(raw,mtime=0)
        snapshot='evidence/v880/fixture.json.gz'
        (self.root/snapshot).write_bytes(packed)
        write('evidence/v880/manifest.json',dict(path=snapshot,gzip_sha256=hashlib.sha256(packed).hexdigest(),
                                                json_sha256=hashlib.sha256(raw).hexdigest()))
        write('fundamentals/latest_scan.json',dict(last_eligible_quarter='2026-Q2'))
        data=MarketData(self.root,ASOF);paths={r['path'] for r in data.input_receipts}
        self.assertIn('9802',data.earnings_events)
        self.assertIn(REVIEW,paths)
        for doc in self.docs:self.assertIn(doc['archive_path'],paths)
        # After the complete Q3 period supersedes the press event, keep the
        # sources in cache inventory but never claim they were consumed.
        write('fundamentals/latest_scan.json',dict(last_eligible_quarter='2026-Q3'))
        data=MarketData(self.root,ASOF);paths={r['path'] for r in data.input_receipts}
        self.assertNotIn('9802',data.earnings_events)
        self.assertNotIn(REVIEW,paths)
        self.assertIn(REVIEW,data.model_source_state)
        for doc in self.docs:
            self.assertNotIn(doc['archive_path'],paths)
            self.assertIn(doc['archive_path'],data.model_source_state)


class OfficialQuarterSeedFallbackTests(unittest.TestCase):
    def setUp(self):
        from tw_model_v880.data import archived_current_income
        self.load_seed=archived_current_income
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.path=self.root/'financial/2026Q3/TWSE_income.json'
        self.path.parent.mkdir(parents=True)
        self.manifest=self.root/'financial/latest_manifest.json'
        self.rows=[{'公司代號':'2330','年度':'115','季別':'3',
                    '營業收入':'100','營業毛利（毛損）淨額':'50',
                    '營業利益（損失）':'30','稅前淨利（淨損）':'28',
                    '本期淨利（淨損）':'22','淨利（淨損）歸屬於母公司業主':'20'}]
        self.doc=dict(schema='v879-quarterly-seed-v1',captured_utc='2026-11-26T01:00:00+00:00',
            sources=[dict(kind='TWSE_income',period='2026Q3',
                url='https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci',
                path='tw-market-data/financial/2026Q3/TWSE_income.json')])
        self.save()
    def save(self):
        raw=json.dumps(self.rows,ensure_ascii=False).encode()
        self.path.write_bytes(raw)
        self.doc['sources'][0].update(normalized_sha256=hashlib.sha256(raw).hexdigest(),issuer_rows=len(self.rows))
        self.manifest.write_text(json.dumps(self.doc))
    def load(self,period='2026-Q3',asof='2026-11-27T00:00:00+00:00'):
        return self.load_seed(self.root,period,asof,'TWSE')
    def test_current_quarter_seed_keeps_real_fields_and_rejects_stale_or_future(self):
        _,p,rows=self.load()
        self.assertEqual(p,self.path)
        self.assertEqual(rows,self.rows)
        self.assertIsNone(self.load(period='2026-Q2'))
        with self.assertRaisesRegex(ValueError,'CAPTURE_FROM_FUTURE'):
            self.load(asof='2026-11-25T00:00:00+00:00')
        self.path.write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError,'NORMALIZED_HASH_MISMATCH'):
            self.load()
    def test_mixed_quarter_duplicate_and_unapproved_source_are_rejected(self):
        self.rows.append(dict(self.rows[0]));self.save()
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ISSUER'):self.load()
        self.rows.pop();self.rows[0]['季別']='2';self.save()
        with self.assertRaisesRegex(ValueError,'ROW_PERIOD_MISMATCH'):self.load()
        self.rows[0]['季別']='3';self.doc['sources'][0]['url']='https://example.org/other';self.save()
        with self.assertRaisesRegex(ValueError,'SOURCE_OR_PATH_MISMATCH'):self.load()
    def test_seed_manifest_and_bytes_invalidate_model_cache(self):
        for name in ('prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
        before=model_source_state(self.root)
        self.assertIn('financial/latest_manifest.json',before)
        rel='financial/2026Q3/TWSE_income.json'
        self.assertIn(rel,before)
        self.rows[0]['稅前淨利（淨損）']='29';self.save()
        after=model_source_state(self.root)
        self.assertNotEqual(before[rel],after[rel])
        self.assertNotEqual(before['financial/latest_manifest.json'],after['financial/latest_manifest.json'])

if __name__=='__main__':unittest.main()
