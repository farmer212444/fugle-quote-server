"""Synthetic source-intake controls; these fixtures are not financial evidence."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import fitz

from scripts import tsmc_original_statements as mod

STAMP=dt.datetime(2026,11,6,14,0,tzinfo=dt.timezone.utc)


def original(period,*,issuer='台灣積體電路製造股份有限公司',notes=True,raster=False):
    year,q=int(period[:4]),int(period[-1]);roc=year-1911
    header=f'民國{roc}及{roc-1}年度' if q==4 else f'民國{roc}及{roc-1}年第{q}季'
    doc=fitz.open()
    for _ in range(24):doc.new_page()
    if raster:
        pix=fitz.Pixmap(fitz.csRGB,(0,0,200,200),False);pix.clear_with(255)
        for i in (0,1):doc[i].insert_image(fitz.Rect(0,0,200,200),pixmap=pix)
    else:
        doc[0].insert_text((30,50),issuer+'及子公司\n合併財務報告暨會計師核閱報告\n'+header,fontname='china-t',fontsize=10)
        sections=mod.SECTIONS if notes else mod.SECTIONS[:-1]
        doc[1].insert_text((30,50),'\n'.join(sections),fontname='china-t',fontsize=10)
    raw=doc.tobytes();doc.close()
    return raw


class OriginalIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.periods=mod.quarter_window('2026-Q2')
        cls.pdfs={p:original(p) for p in cls.periods}

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.calls=[]
        self.specs={}
        for period in self.periods:
            y,q=period[:4],int(period[-1])
            label={1:y+'年度第一季',2:y+'年度上半年度',3:y+'年度前三季',4:y+'年'}[q]
            url=f'https://investor.tsmc.com/sites/ir/financial-report/{y}/TSMC%20{y}Q{q}%20Consolidated%20Financial%20Statements_C.pdf'
            self.specs[period]=(url,label)
        self.directory=''.join(f'<a href="{u}">{label}</a>' for u,label in self.specs.values()).encode()

    def fetch(self,url,limit):
        self.calls.append(url)
        if url==mod.DIRECTORY:return self.directory
        return self.pdfs[next(p for p,(u,_) in self.specs.items() if u==url)]

    def collect(self,**kw):
        return mod.collect(self.root,'2026-Q2',fetcher=kw.get('fetcher',self.fetch),clock=kw.get('clock',lambda:STAMP))

    def manifest(self):return json.loads((self.root/mod.MANIFEST).read_text())
    def save(self,m):mod.atomic_json(self.root/mod.MANIFEST,m)

    def test_complete_official_linked_window_remains_uncertified(self):
        result=self.collect();c=result['coverage']
        self.assertEqual(c['found_quarters'],self.periods)
        self.assertTrue(c['source_title_coverage_complete'])
        self.assertTrue(c['pdf_accounting_period_internal_identity_verified'])
        self.assertFalse(c['full_original_pdf_content_reviewed'])
        self.assertFalse(c['original_MOPS_PIT_verified'])
        self.assertFalse(c['formal_gate_pass']);self.assertEqual(result['formal_pass_count'],0)
        self.assertEqual(len(self.manifest()['documents']),8)

    def test_raster_cover_archived_as_pending_never_identified(self):
        raster=original('2025-Q4',raster=True)
        def fetch(url,limit):return raster if url==self.specs['2025-Q4'][0] else self.fetch(url,limit)
        result=self.collect(fetcher=fetch);c=result['coverage']
        self.assertEqual(len(c['found_quarters']),8)
        self.assertEqual(c['native_cover_identity_pending_quarters'],['2025-Q4'])
        self.assertFalse(c['pdf_accounting_period_internal_identity_verified'])
        self.assertFalse(c['formal_gate_pass'])

    def test_wrong_issuer_period_or_missing_notes_are_rejected(self):
        for raw in (original('2026-Q2',issuer='其他公司'),original('2025-Q2'),original('2026-Q2',notes=False)):
            with self.subTest(case=mod.digest(raw)):
                with self.assertRaises(ValueError):mod.pdf_identity(raw,'2026-Q2')

    def test_directory_labels_and_ambiguous_sources_rejected(self):
        with self.assertRaisesRegex(ValueError,'LABEL_PERIOD_MISMATCH'):
            mod.discover(self.directory.replace('2026年度上半年度'.encode(),'2025年度上半年度'.encode()),self.periods)
        url,label=self.specs['2026-Q2']
        extra=f'<a href="{url.replace("_C.pdf","_C_1.pdf")}">{label}</a>'.encode()
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_QUARTER_SOURCE'):
            mod.discover(self.directory+extra,self.periods)

    def test_untrusted_urls_and_paths(self):
        good=self.specs['2026-Q2'][0]
        for url in (good.replace('investor.tsmc.com','evil.example'),good+'?file=1',good.replace('/2026/','/2025/'),good.replace('https:','http:')):
            self.assertFalse(mod.pdf_url(url))
        for path in ('../escape','/tmp/escape'):
            with self.assertRaisesRegex(ValueError,'UNSAFE_PATH'):mod.safe(self.root,path)

    def test_bytes_metadata_and_false_certification_tampering_rejected(self):
        self.collect();valid=self.manifest();entry=valid['documents'][0]
        path=self.root/entry['archive_path'];raw=path.read_bytes();path.write_bytes(raw+b'tampered')
        with self.assertRaisesRegex(ValueError,'HASH_OR_SIZE_MISMATCH'):
            mod.validate_archive(self.root,'2026-Q2',STAMP)
        path.write_bytes(raw)
        altered=copy.deepcopy(valid);altered['documents'][0]['pdf_identity']['page_count']=999;self.save(altered)
        with self.assertRaisesRegex(ValueError,'METADATA_NOT_REPRODUCIBLE'):
            mod.validate_archive(self.root,'2026-Q2',STAMP)
        for field in ('formal_gate_pass','original_MOPS_PIT_verified','full_content_review_complete'):
            altered=copy.deepcopy(valid);altered[field]=True;self.save(altered)
            with self.assertRaisesRegex(ValueError,'FALSE_CERTIFICATION'):
                mod.validate_archive(self.root,'2026-Q2',STAMP)

    def test_directory_provenance_and_duplicate_receipts_required(self):
        self.collect();valid=self.manifest()
        altered=copy.deepcopy(valid);altered['documents'][0]['index_sha256']='0'*64;self.save(altered)
        with self.assertRaisesRegex(ValueError,'PROVENANCE_MISSING'):
            mod.validate_archive(self.root,'2026-Q2',STAMP)
        altered=copy.deepcopy(valid);altered['documents'].append(altered['documents'][0]);self.save(altered)
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ORIGINAL_VERSION'):
            mod.validate_archive(self.root,'2026-Q2',STAMP)

    def test_partial_unavailable_source_is_missing_and_retryable(self):
        def unavailable(url,limit):
            if url==self.specs['2025-Q4'][0]:raise OSError('network unavailable')
            return self.fetch(url,limit)
        result=self.collect(fetcher=unavailable)
        self.assertEqual(result['coverage']['missing_quarters'],['2025-Q4'])
        self.assertEqual(result['fetch_errors'][0]['period'],'2025-Q4')
        self.assertEqual(self.collect()['coverage']['missing_quarters'],[])

    def test_403_directory_uses_hash_verified_old_index_to_retry_missing_pdfs(self):
        first_missing=self.specs['2026-Q2'][0]
        def partial(url,limit):
            if url==first_missing:raise OSError('document temporarily unavailable')
            return self.fetch(url,limit)
        initial=self.collect(fetcher=partial)
        self.assertEqual(initial['coverage']['missing_quarters'],['2026-Q2'])
        def blocked_index(url,limit):
            if url==mod.DIRECTORY:raise OSError('HTTP 403 Forbidden')
            return self.fetch(url,limit)
        after=self.collect(fetcher=blocked_index,clock=lambda:STAMP+dt.timedelta(minutes=1))
        self.assertEqual(after['coverage']['found_quarters'],self.periods)
        self.assertTrue(after['coverage']['source_title_coverage_complete'])
        self.assertEqual(after['fetch_errors'][0]['period'],'DIRECTORY')
        self.assertEqual(after['fetch_errors'][0]['recovery'],
                         'SHA_VERIFIED_ARCHIVED_ISSUER_INDEX')
        self.assertEqual(len(self.manifest()['index_versions']),1)
        self.assertFalse(after['coverage']['formal_gate_pass'])
        self.assertFalse(after['coverage']['full_original_pdf_content_reviewed'])

    def test_repeated_full_403_denial_is_bounded_and_originals_remain_pending(self):
        def pdfs_blocked(url,limit):
            if url==mod.DIRECTORY:return self.directory
            raise OSError('HTTP 403 Forbidden')
        first=self.collect(fetcher=pdfs_blocked)
        self.assertEqual(len(first['coverage']['missing_quarters']),8)
        def everything_blocked(url,limit):
            raise OSError('HTTP 403 Forbidden')
        second=self.collect(fetcher=everything_blocked,
                            clock=lambda:STAMP+dt.timedelta(minutes=5))
        self.assertEqual(len(second['coverage']['missing_quarters']),8)
        calls=[]
        def later(url,limit):
            calls.append(url)
            return self.fetch(url,limit)
        skipped=self.collect(fetcher=later,
                             clock=lambda:STAMP+dt.timedelta(minutes=15))
        self.assertEqual(calls,[])
        self.assertEqual(skipped['http403_retry_deferred_quarters'],self.periods)
        self.assertFalse(skipped['coverage']['formal_gate_pass'])
        self.assertEqual(len(skipped['coverage']['missing_quarters']),8)
        self.assertEqual(len(self.manifest()['documents']),0)
        recovered=self.collect(fetcher=later,
                               clock=lambda:STAMP+dt.timedelta(hours=25,minutes=10))
        self.assertEqual(recovered['coverage']['missing_quarters'],[])
        self.assertTrue(recovered['coverage']['source_title_coverage_complete'])
        self.assertFalse(recovered['coverage']['formal_gate_pass'])
        self.assertFalse(recovered['coverage']['full_original_pdf_content_reviewed'])

    def test_published_403_deferred_state_does_not_fake_new_fetch_or_pass(self):
        deferred=dict(issuer='2330',records=0,
            coverage=dict(required_quarters=self.periods,
                          found_quarters=[],missing_quarters=self.periods,
                          native_cover_identity_verified_quarters=[]),
            fetch_errors=[dict(period='DIRECTORY',
                               error='HTTPError:HTTP Error 403: Forbidden')],
            formal_pass_count=0,documents=[],
            http403_retry_deferred_quarters=['2024-Q3','2026-Q2'],
            http403_retry_due_at_utc='2026-11-09T12:00:00+00:00')
        (self.root/'rankings').mkdir(exist_ok=True)
        with mock.patch.object(mod,'collect',return_value=deferred), mock.patch(
            'sys.argv',['tsmc_original_statements.py','--data-root',
                        str(self.root),'--last-quarter','2026-Q2']):
            mod.main()
        published=json.loads(
            (self.root/'rankings/tsmc_original_statements_intake.json').read_text())
        self.assertEqual(published['http403_retry_deferred_quarters'],
                         ['2024-Q3','2026-Q2'])
        self.assertEqual(published['http403_retry_due_at_utc'],
                         '2026-11-09T12:00:00+00:00')
        self.assertEqual(published['formal_pass_count'],0)
        self.assertEqual(published['coverage']['found_quarters'],[])
        readable=(self.root/'rankings/tsmc_original_statements_intake.md').read_text()
        self.assertIn('有界重試保護',readable)
        self.assertIn('未進行網路重試',readable)
        self.assertIn('2026-11-09T12:00:00+00:00',readable)

    def test_missing_official_pdf_lead_requires_sha_verified_issuer_index(self):
        blocked=self.specs['2025-Q4'][0]
        def partial(url,limit):
            if url==blocked:raise OSError('HTTP 403 Forbidden')
            return self.fetch(url,limit)
        result=self.collect(fetcher=partial)
        self.assertEqual(result['coverage']['missing_quarters'],['2025-Q4'])
        leads=mod.discover_missing_original_leads(
            self.root,'2026-Q2',STAMP+dt.timedelta(minutes=1))
        self.assertEqual(len(leads),1)
        lead=leads[0]
        self.assertEqual(lead['period'],'2025-Q4')
        self.assertEqual(lead['source_url'],blocked)
        self.assertIsNone(lead['original_pdf_sha256'])
        self.assertFalse(lead['original_pdf_archived'])
        self.assertFalse(lead['formal_gate_pass'])
        self.assertTrue(lead['source_link_is_not_formal_evidence'])
        self.assertEqual(len(lead['directory_index_sha256']),64)
        manifest=self.manifest()
        path=self.root/manifest['index_versions'][0]['archive_path']
        raw=path.read_bytes();path.write_bytes(raw+b'TAMPERED')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            mod.discover_missing_original_leads(
                self.root,'2026-Q2',STAMP+dt.timedelta(minutes=1))

    def test_source_leads_empty_when_originals_complete(self):
        result=self.collect()
        self.assertFalse(result['coverage']['missing_quarters'])
        self.assertEqual(mod.discover_missing_original_leads(
            self.root,'2026-Q2',STAMP+dt.timedelta(minutes=1)),[])

    def test_403_without_prior_issuer_index_cannot_fabricate_urls(self):
        def blocked_index(url,limit):
            raise OSError('HTTP 403 Forbidden')
        result=self.collect(fetcher=blocked_index)
        self.assertEqual(len(result['coverage']['missing_quarters']),8)
        self.assertEqual(result['fetch_errors'][0]['period'],'DIRECTORY')
        self.assertNotIn('recovery',result['fetch_errors'][0])
        self.assertFalse(result['coverage']['formal_gate_pass'])

    def test_directory_failure_preserves_archived_bytes_and_pending_state(self):
        self.collect();old=self.manifest()['documents']
        def unavailable(url,limit):raise OSError('offline')
        result=self.collect(fetcher=unavailable)
        self.assertEqual(result['records'],8)
        self.assertEqual(self.manifest()['documents'],old)
        self.assertEqual(result['fetch_errors'][0]['period'],'DIRECTORY')
        self.assertFalse(result['coverage']['formal_gate_pass'])

    def test_first_capture_preserved_and_future_records_invisible(self):
        self.collect();old=self.manifest()['documents'];self.calls=[]
        self.collect(clock=lambda:STAMP+dt.timedelta(days=1))
        self.assertEqual(self.manifest()['documents'],old)
        self.assertEqual(self.calls,[mod.DIRECTORY])
        past=mod.validate_archive(self.root,'2026-Q2',STAMP-dt.timedelta(seconds=1))
        self.assertEqual(past['records'],0)
        self.assertEqual(len(past['coverage']['missing_quarters']),8)

    def test_future_period_and_naive_capture_time_rejected(self):
        with self.assertRaisesRegex(ValueError,'FUTURE_STATEMENT_PERIOD'):
            mod.collect(self.root,'2027-Q1',fetcher=self.fetch,clock=lambda:STAMP)
        with self.assertRaisesRegex(ValueError,'TIMEZONE_REQUIRED'):
            self.collect(clock=lambda:STAMP.replace(tzinfo=None))

    def test_source_cache_tracks_nested_manifest_and_original_bytes(self):
        from tw_model_v880.data import model_source_state
        self.collect()
        for rel in ('prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json'):
            mod.atomic_json(self.root/rel,{})
        state=model_source_state(self.root)
        self.assertIn(mod.MANIFEST,state)
        original_path=self.manifest()['documents'][0]['archive_path']
        self.assertIn(original_path,state)
        path=self.root/original_path;path.write_bytes(path.read_bytes()+b'changed')
        self.assertNotEqual(state[original_path],model_source_state(self.root)[original_path])


if __name__=='__main__':unittest.main()
