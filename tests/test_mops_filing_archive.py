import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs,urlsplit

from scripts.mops_filing_archive import (
    HEADERS,parse_index,parse_resolver,upload_timestamp,collect,audit_archive,
    verify_version,index_url,official_url,store_original,
    native_identity,
)


PDF=b'%PDF-1.4\n'+b'A'*5200+b'\n%%EOF\n'
PREFLIGHT=dict(page_count=1,issuer_and_period_native_text_preflight=True,
               financial_numbers_and_notes_substantively_reviewed=False)


def index_fixture(code='6206',year=2025,correction='無'):
    rows=['<tr>'+''.join('<th>'+name+'</th>' for name in HEADERS)+'</tr>']
    for quarter in range(1,5):
        upload=(f'{year-1911}/{quarter*3+2:02d}/08 17:05:07' if quarter<4
                else f'{year+1-1911}/03/12 10:00:00')
        name=f'{year}0{quarter}_{code}_AI1.pdf'
        cells=[code,f'{year-1911} 年 第'+('一二三四'[quarter-1])+'季','財務報告書','','',
               'IFRSs合併財報','',f'''<a href='javascript:readfile2("A","{code}","{name}");'>{name}</a>''',
               str(len(PDF)),upload,correction]
        rows.append('<tr>'+''.join('<td>'+value+'</td>' for value in cells)+'</tr>')
    return ('<meta charset="utf-8"><table>'+''.join(rows)+'</table>').encode()


def source_fixture(calls,correction='無'):
    def source(url):
        calls.append(url);query=parse_qs(urlsplit(url).query)
        if query.get('step')==['1']:
            return index_fixture(query['co_id'][0],int(query['year'][0])+1911,correction)
        if query.get('step')==['9']:
            name=query['filename'][0]
            return f'''<meta charset="utf-8"><a href='/pdf/{name[:-4]}_20261022_164637.pdf'>{name}</a>'''.encode()
        return PDF
    return source


class OfficialFilings(unittest.TestCase):
    def test_flytech_chinese_digit_year_and_numeric_statement_date(self):
        import pymupdf
        doc=pymupdf.open()
        page=doc.new_page()
        page.insert_text((40,60),'股票代碼：6206\n飛捷科技股份有限公司及子公司\n合併財務報告暨會計師核閱報告\n民國一一五年及一一四年第二季\n115.6.30',fontname='china-t')
        raw=doc.tobytes();doc.close()
        row=dict(code='6206',financial_period='2026-Q2')
        self.assertTrue(native_identity(raw,row)['issuer_and_period_native_text_preflight'])
        with self.assertRaisesRegex(ValueError,'CURRENT_YEAR_MISMATCH'):
            native_identity(raw,dict(row,financial_period='2025-Q2'))
        with self.assertRaisesRegex(ValueError,'END_DATE_MISSING'):
            native_identity(raw,dict(row,financial_period='2026-Q1'))
        with self.assertRaisesRegex(ValueError,'ISSUER_MISSING'):
            native_identity(raw,dict(row,code='9802'))

    def test_index_upload_seconds_and_issuer_period_identity(self):
        rows=parse_index(index_fixture(),'6206',2025)
        self.assertEqual(rows[0]['official_upload_at'],'2025-05-08T17:05:07+08:00')
        self.assertEqual(rows[0]['financial_period'],'2025-Q1')
        self.assertEqual(rows[-1]['official_upload_at'],'2026-03-12T10:00:00+08:00')
        with self.assertRaisesRegex(ValueError,'OTHER_ISSUER'):
            parse_index(index_fixture('9802'),'6206',2025)
        with self.assertRaisesRegex(ValueError,'OTHER_ACCOUNTING_YEAR'):
            parse_index(index_fixture(),'6206',2024)

    def test_missing_or_reordered_upload_headers_are_not_guessed(self):
        raw=index_fixture().replace('上傳日期'.encode(),'文件日期'.encode())
        with self.assertRaisesRegex(ValueError,'HEADERS'):
            parse_index(raw,'6206',2025)
        with self.assertRaisesRegex(ValueError,'EXACT_UPLOAD'):
            upload_timestamp('114/05/08')

    def test_generated_download_time_never_replaces_the_official_upload_clock(self):
        row=parse_index(index_fixture(),'6206',2025)[0]
        resolver=source_fixture([])('https://doc.twse.com.tw/server-java/t57sb01?step=9&filename='+row['file_name'])
        url=parse_resolver(resolver,row)
        self.assertIn('20261022_164637',url)
        self.assertEqual(row['official_upload_at'],'2025-05-08T17:05:07+08:00')
        with self.assertRaisesRegex(ValueError,'OTHER_DOCUMENT'):
            parse_resolver(resolver.replace(b'202501_6206_AI1_',b'202501_9802_AI1_'),row)

    def test_budget_persists_exact_originals_and_reuses_the_first_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);calls=[];source=source_fixture(calls)
            first=collect(root,last='2025-Q1',max_documents=2,source=source,reader=lambda *_:PREFLIGHT,pause=0)
            self.assertEqual(first['new_document_versions'],2)
            before=audit_archive(root,lambda *_:PREFLIGHT)
            self.assertEqual({v['index_row']['code'] for v in before['versions']},{'6206','9802'})
            clocks={v['reference']['path']:v['captured_at_utc'] for v in before['versions']}
            second=collect(root,last='2025-Q1',max_documents=2,source=source,reader=lambda *_:PREFLIGHT,pause=0)
            self.assertEqual(second['new_document_versions'],2)
            after=audit_archive(root,lambda *_:PREFLIGHT)
            self.assertEqual(after['source_rejections'],[])
            self.assertEqual(len(after['versions']),4)
            for v in after['versions']:
                if v['reference']['path'] in clocks:
                    self.assertEqual(v['captured_at_utc'],clocks[v['reference']['path']])
                self.assertFalse(v['formal_gate_pass'])
                self.assertFalse(v['historical_revision_chain_independently_reviewed'])

    def test_pdf_bytes_and_declared_index_size_are_both_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            collect(root,codes=('6206',),last='2025-Q1',max_documents=1,
                    source=source_fixture([]),reader=lambda *_:PREFLIGHT,pause=0)
            version=audit_archive(root,lambda *_:PREFLIGHT)['versions'][0]
            (root/version['pdf_original']['path']).write_bytes(PDF+b'changed')
            report=audit_archive(root,lambda *_:PREFLIGHT)
            self.assertEqual(report['versions'],[])
            self.assertIn('HASH_OR_SIZE_MISMATCH',report['source_rejections'][0]['reason'])

    def test_changed_correction_status_is_preserved_as_a_new_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            collect(root,codes=('6206',),last='2025-Q1',max_documents=1,
                    source=source_fixture([]),reader=lambda *_:PREFLIGHT,pause=0)
            collect(root,codes=('6206',),last='2025-Q1',max_documents=1,
                    source=source_fixture([],correction='更正紀錄待核對'),reader=lambda *_:PREFLIGHT,pause=0)
            versions=audit_archive(root,lambda *_:PREFLIGHT)['versions']
            self.assertEqual(len(versions),2)
            self.assertEqual({v['index_row']['latest_reported_correction'] for v in versions},{'無','更正紀錄待核對'})

    def test_nonofficial_download_and_path_escape_are_rejected(self):
        self.assertFalse(official_url('https://doc.twse.com.tw.evil.invalid/pdf/a.pdf'))
        self.assertFalse(official_url('https://doc.twse.com.tw/pdf/../outside.pdf'))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'UNSAFE_PATH'):
                store_original(Path(tmp),'../outside',b'bad')

    def test_failed_identity_keeps_raw_bytes_and_does_not_monopolize_next_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def reader(_raw,_row):raise ValueError('NATIVE_IDENTITY_PENDING')
            first=collect(root,codes=('6206',),last='2025-Q1',max_documents=1,
                    source=source_fixture([]),reader=reader,pause=0)
            self.assertEqual(first['new_document_versions'],0)
            self.assertEqual(len(list((root/'filings/mops/originals/6206').glob('*.pdf'))),1)
            self.assertEqual(list((root/'filings/mops/6206').glob('*/receipt.json')),[])
            second=collect(root,codes=('6206',),last='2025-Q1',max_documents=1,
                    source=source_fixture([]),reader=lambda *_:PREFLIGHT,pause=0)
            self.assertEqual(second['new_document_versions'],1)
            self.assertEqual(audit_archive(root,lambda *_:PREFLIGHT)['versions'][0]['index_row']['financial_period'],'2024-Q4')

    def test_official_access_restriction_stops_all_remaining_requests(self):
        from urllib.error import HTTPError
        calls=[]
        def restricted(url):
            calls.append(url);raise HTTPError(url,403,'Forbidden',None,None)
        with tempfile.TemporaryDirectory() as tmp:
            report=collect(Path(tmp),source=restricted,reader=lambda *_:PREFLIGHT,pause=0)
            self.assertTrue(report['source_access_restricted'])
            self.assertEqual(len(calls),1)
            self.assertEqual(report['new_document_versions'],0)


if __name__=='__main__':unittest.main()
