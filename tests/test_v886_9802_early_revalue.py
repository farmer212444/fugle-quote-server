import unittest
import hashlib
import json
import tempfile
from pathlib import Path
from scripts.v896_original_archive import collect
from scripts.v886_9802_early_revalue import num, revalue, issuer_press_source_status

class EarlyQ3Tests(unittest.TestCase):
    def publisher_source_fixture(self,root):
        root=Path(root)
        root.joinpath("issuer/9802").mkdir(parents=True)
        raw=b"%PDF-1.5\n"+b"official-company-news-pdf"*280+b"\n%%EOF\n"
        key="a76fdaea143f3b809835"
        url=("https://www.fulgentsun.com/img/News_Release/"
             "FY2026%203Q%20financial%20results%20CN.pdf")
        now="2026-10-20T12:03:53+00:00"
        source={
            "issuer":"9802","publisher":"鈺齊國際",
            "discovered":[{"id":key,"category":"news",
                           "site_display_date":"2026-10-20",
                           "title":"2026年第三季自結財報新聞稿",
                           "url":url}],
            "receipts":{key:{"versions":[{
                "sha256":hashlib.sha256(raw).hexdigest(),
                "bytes":len(raw),"source_url":url,
                "captured_at_utc":now}]}}
        }
        target=root/"issuer/9802/manifest.json"
        target.write_text(json.dumps(source),encoding="utf-8")
        captured=collect(root,"9802","2026-10-21",now,
                         fetcher=lambda issuer,url:raw)
        self.assertEqual(captured["records"],1)
        return target,source

    def test_real_issuer_press_source_discovery_is_not_report_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            path,source=self.publisher_source_fixture(root)
            research={"estimate_vintage":"2026-10-21T10:33:23+08:00"}
            result=issuer_press_source_status(research,root)
            self.assertEqual(result["status"],
                             "OFFICIAL_ISSUER_Q3_SELF_REPORTED_SOURCE_ARCHIVED")
            self.assertTrue(result["original_bytes_sha256_checked"])
            self.assertEqual(result["issuer_website_display_date"],"2026-10-20")
            self.assertFalse(result["certified_Aplus"])
            self.assertFalse(result["issuer_company_publication_PIT_verified"])
            self.assertEqual(result["formal_gate_PASSES_created"],0)
            self.assertTrue(result["issuer_Q3_press_numbers_not_yet_reconciled_with_signed_MOPS_income"])
            self.assertTrue(result["2027_eps_pe_and_base_unchanged"])

    def test_press_original_source_must_be_public_by_research_vintage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            path,source=self.publisher_source_fixture(root)
            with self.assertRaisesRegex(ValueError,"NOT_AVAILABLE_AT_RESEARCH_VINTAGE"):
                issuer_press_source_status(
                    {"estimate_vintage":"2026-10-20T18:00:00+08:00"},root)
            source["receipts"]["a76fdaea143f3b809835"]["versions"][0]["bytes"]+=1
            path.write_text(json.dumps(source),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"HASH_OR_SIZE_MISMATCH"):
                issuer_press_source_status(
                    {"estimate_vintage":"2026-10-21T10:33:23+08:00"},root)

    def test_missing_q3_original_is_pending_not_zero_profit(self):
        with tempfile.TemporaryDirectory() as d:
            result=issuer_press_source_status(
                {"estimate_vintage":"2026-10-21T10:33:23+08:00"},d)
            self.assertEqual(result["status"],"WAITING_ISSUER_Q3_ARCHIVED_ORIGINAL")
            self.assertFalse(result["certified_Aplus"])

    def test_numeric_validation(self):
        self.assertIsNone(num(None))
        self.assertIsNone(num(True))
        self.assertEqual(num("18.4"),18.4)

    def test_no_early_q3_needed_after_full_market_rollover(self):
        research=dict(model="V8.8.2",estimate_vintage="2026-10-19T18:00:00+08:00",
                      asof_price_date="2026-10-16")
        full=dict(model="V8.8.2",estimate_vintage=research["estimate_vintage"],
                  asof_price_date=research["asof_price_date"],
                  financial_last_quarter="2026-Q3")
        result=revalue(research,full,{}, {})
        self.assertEqual(result["status"],"QUARTER_ALREADY_IN_MAIN_MODEL")
        self.assertFalse(result["certified_Aplus"])

    def test_wrong_quarter_receipt_fails_closed(self):
        research=dict(model="V8.8.2",estimate_vintage="2026-10-19T18:00:00+08:00",
                      asof_price_date="2026-10-16")
        full=dict(model="V8.8.2",estimate_vintage=research["estimate_vintage"],
                  asof_price_date=research["asof_price_date"],
                  financial_last_quarter="2026-Q2")
        with self.assertRaisesRegex(ValueError,"RECEIPT_NOT_ADMISSIBLE"):
            revalue(research,full,{}, {})

    def test_synthetic_early_q3_revenue_and_gm_change_the_shadow_only(self):
        oldcase=dict(revenue_k=20000000,gross_margin=.178,opex_ratio=.095,
                     nonoperating_k=100000,tax_rate=.2,parent_fraction=1,
                     shares=200000000,pe=13,eps=7.04,target_price=91.52)
        issuer=dict(code="9802",market="TWSE",rankable=True,
                    financial_period="2026-Q2",reference_close=67.6,
                    target_date="2027-12-31",formal_Aplus=False,
                    formal_Aplusplus=False,bear=oldcase,base=oldcase,bull=oldcase)
        now="2026-10-19T18:00:00+08:00"
        research=dict(model="V8.8.2",estimate_vintage=now,
                      asof_price_date="2026-10-16",all_model_row_summary=[])
        full=dict(model="V8.8.2",estimate_vintage=now,
                  asof_price_date="2026-10-16",
                  financial_last_quarter="2026-Q2",all_model_rows=[issuer])
        h1=dict(code="9802",unit="NTD_thousands_except_EPS",
                year_to_date_values=True,revenue_ytd_k=1000,
                gross_profit_ytd_k=150,operating_profit_ytd_k=70)
        prior=dict(period="2026-Q2",market="TWSE",kind="income",rows=[h1])
        q3=dict(code="9802",market="TWSE",period="2026-Q3",
                unit="NTD_thousands_except_EPS",year_to_date_values=True,
                revenue_ytd_k=1600,gross_profit_ytd_k=260,
                operating_profit_ytd_k=146)
        receipt=dict(code="9802",market="TWSE",financial_period="2026-Q3",
                     source_url="https://mopsov.twse.com.tw/mops/web/ajax_t163sb04",
                     quarter_title_checked=True,issuer_filing_PIT_verified=False,
                     must_not_set_certification_gate_pass=True,
                     original_html_sha256="a"*64,
                     captured_at_utc="2026-10-19T09:00:00+00:00",
                     observed_income_row=q3,
                     new_quarter_gross_margin_pct=18.3333,
                     year_to_date_gross_margin_pct=16.25)
        new=revalue(research,full,receipt,prior)
        self.assertAlmostEqual(new["standalone_q3_gm_pct"],18.333,places=3)
        self.assertGreater(new["new"]["base"]["eps"],new["old"]["base"]["eps"])
        self.assertEqual(new["shadow_if_substituted_rank"],1)
        self.assertTrue(new["official_top10_unchanged"])
        self.assertFalse(new["certified_Aplus"])
        receipt["captured_at_utc"]="2026-10-21T09:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"FUTURE_RECEIPT"):
            revalue(research,full,receipt,prior)

if __name__=="__main__":unittest.main()
