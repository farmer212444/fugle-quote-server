import copy
import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import tw_fundamentals as collector
from tests.test_integration_v880 import FakeData,CAL,ASOF
from tw_model_v880.model import estimate


class HistoricalFinancialBackfill(unittest.TestCase):
    def test_historical_scan_retains_current_manifest_and_an_extra_training_quarter(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);fin=root/'fundamentals';fin.mkdir();manifest=fin/'latest_scan.json'
            manifest.write_text('{"last_eligible_quarter":"2026-Q2"}\n');original=manifest.read_bytes()
            body='<html>公開資訊觀測站上市公司第三季資料</html>'.encode()
            rows=[dict(code=str(1000+i),name='SYNTHETIC',basic_eps_ytd=1) for i in range(100)]
            with patch.object(collector,'FIN',fin),patch.object(collector,'RAW',root/'raw'),\
                 patch.object(collector,'download',return_value=body),patch.object(collector,'parse',return_value=rows),\
                 patch.object(collector.time,'sleep'):
                report=collector.scan(dt.date(2024,12,31),1,archive_only=True,extra_training_quarters=1)
            self.assertEqual(manifest.read_bytes(),original)
            self.assertEqual(report['required_periods'][0],'2022-Q3')
            self.assertEqual(report['required_periods'][-1],'2024-Q3')
            self.assertEqual(report['new_batches_this_run'],1)
            self.assertEqual(report['missing_batches'],35)
            self.assertEqual(report['admitted_historical_PIT_batches'],0)
            self.assertTrue((fin/'historical_readiness/2024-12-31.json').exists())
            saved=json.loads((fin/'2024-Q3/TWSE_income.json').read_text())
            self.assertFalse(saved['original_retrieval']['original_publication_and_revision_PIT_verified'])
            original_path=Path(saved['original_retrieval']['raw_path'])
            self.assertEqual(gzip.decompress(original_path.read_bytes()),body)

    def test_explicit_wrong_venue_or_quarter_is_rejected_but_year_is_never_forged(self):
        with tempfile.TemporaryDirectory() as t,patch.object(collector,'FIN',Path(t)):
            for text in ['公開資訊觀測站上櫃公司第三季資料','公開資訊觀測站上市公司第二季資料']:
                with self.assertRaisesRegex(ValueError,'NOT_CONFIRMED'):
                    collector.archive_response(text.encode(),2024,3,'TWSE','income',ASOF)
            receipt=collector.archive_response('公開資訊觀測站上市公司第三季資料'.encode(),2024,3,'TWSE','income',ASOF)
            self.assertTrue(receipt['venue_and_quarter_header_verified'])
            self.assertFalse(receipt['fiscal_year_in_response_verified'])
            self.assertFalse(receipt['original_publication_and_revision_PIT_verified'])

    def test_older_training_data_and_future_rows_cannot_change_eight_quarter_forecast(self):
        data=FakeData();key=('TEST','SYNTHETIC_A')
        original=estimate(data,key,CAL,ASOF,'2027-12-31')
        for period,row in data.history[key].items():
            if period not in data.required_periods:
                row.update(revenue_ytd_k=99999999,gross_profit_ytd_k=88888888,operating_profit_ytd_k=77777777)
        changed=estimate(data,key,CAL,ASOF,'2027-12-31')
        for k in ('base','bear','bull','formal_Aplus','formal_Aplusplus'):
            self.assertEqual(original[k],changed[k])

    def test_final_offline_refresh_counts_shared_batches_for_both_targets(self):
        with tempfile.TemporaryDirectory() as t:
            fin=Path(t)/'fundamentals';fin.mkdir()
            manifest=fin/'latest_scan.json';manifest.write_text('{"current":true}')
            rows=[dict(code=str(1000+i)) for i in range(100)]
            with patch.object(collector,'FIN',fin),patch.object(collector,'download',side_effect=AssertionError('Offline')):
                first=collector.scan(dt.date(2024,12,31),0,True,archive_only=True,extra_training_quarters=1)
                shared=fin/'2024-Q3/TWSE_income.json';shared.parent.mkdir(parents=True)
                shared.write_text(json.dumps(dict(period='2024-Q3',market='TWSE',kind='income',rows=rows)))
                second=collector.scan(dt.date(2025,12,31),0,True,archive_only=True,extra_training_quarters=1)
                final=collector.scan(dt.date(2024,12,31),0,True,archive_only=True,extra_training_quarters=1)
            self.assertEqual(first['verified_batches'],0)
            self.assertEqual(second['verified_batches'],1)
            self.assertEqual(final['verified_batches'],1)
            self.assertEqual(final['loaded_batch_keys'],['2024-Q3/TWSE/income'])
            self.assertEqual(len(final['missing_batch_keys']),35)
            self.assertEqual(manifest.read_text(),'{"current":true}')
            self.assertEqual(final['admitted_historical_PIT_batches'],0)


if __name__=='__main__':unittest.main()
