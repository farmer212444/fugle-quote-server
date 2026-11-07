import json,tempfile,unittest
from pathlib import Path
from scripts.sec_api_intake import capture,run,summarize,url


def submission():
    recent={k:[v] for k,v in dict(accessionNumber='0001046179-24-000116',filingDate='2024-10-17',
        reportDate='2024-09-30',acceptanceDateTime='2024-10-17T10:13:36Z',form='6-K',primaryDocument='synthetic.htm').items()}
    return json.dumps(dict(cik='0001046179',name='SYNTHETIC ONLY',filings=dict(recent=recent,files=[]))).encode()


def facts():
    return json.dumps(dict(cik=1046179,entityName='SYNTHETIC ONLY',facts={'ifrs-full':{'Revenue':{
        'units':{'TWD':[dict(val=100,end='2024-09-30',filed='2024-10-17',accn='0001046179-24-000116')]}}}})).encode()


class OfficialApiIntake(unittest.TestCase):
    def test_identity_and_bounded_urls(self):
        self.assertTrue(url('1046179','submissions').startswith('https://data.sec.gov/'))
        with self.assertRaises(ValueError):url('../secret','submissions')
        with self.assertRaises(ValueError):url('1046179','unknown')
        with self.assertRaisesRegex(ValueError,'ISSUER'):summarize(submission(),'999','submissions')

    def test_filing_and_fact_counts_are_from_original_json(self):
        self.assertEqual(summarize(submission(),'1046179','submissions')['filing_records'],1)
        f=summarize(facts(),'1046179','companyfacts')
        self.assertEqual(f['fact_observations'],1);self.assertEqual(f['first_filed'],'2024-10-17')

    def test_partial_arrays_and_missing_units_are_rejected(self):
        d=json.loads(submission());d['filings']['recent']['form']=[]
        with self.assertRaisesRegex(ValueError,'ARRAY_LENGTH'):summarize(json.dumps(d).encode(),'1046179','submissions')
        d=json.loads(facts());d['facts']['ifrs-full']['Revenue']={}
        with self.assertRaisesRegex(ValueError,'UNITS'):summarize(json.dumps(d).encode(),'1046179','companyfacts')

    def test_immutable_cache_and_api_not_mislabelled_as_original_filing(self):
        with tempfile.TemporaryDirectory() as t:
            a=capture(t,'1046179','submissions',lambda _:submission())
            b=capture(t,'1046179','submissions',lambda _:submission())
            self.assertEqual(a,b);self.assertTrue(a['is_official_api_response_not_original_filing_document'])
            self.assertFalse(a['financial_PIT_admitted'])
            (Path(t)/a['archive_path']).write_bytes(b'changed')
            with self.assertRaises((ValueError,OSError)):capture(t,'1046179','submissions',lambda _:submission())

    def test_errors_do_not_make_financial_outcomes(self):
        with tempfile.TemporaryDirectory() as t:
            def denied(_):raise OSError('SYNTHETIC HTTP 403')
            r=run(t,['1046179'],denied)
            self.assertEqual(r['captured_api_responses'],0);self.assertEqual(len(r['errors']),2)
            self.assertEqual(r['calibrated_returns_created'],0)


if __name__=='__main__':unittest.main()
