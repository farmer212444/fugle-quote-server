"""No unverified secondary insider data may pass the issuer insider quality gate."""
import copy
import json
import unittest
from pathlib import Path

from scripts.tw_insider_shadow import EXPECTED, analyze_shadow, dedupe_primary_holder_rows


PATH = Path("tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_secondary_shadow.json")


class InsiderShadowTests(unittest.TestCase):
    def load(self):
        return json.loads(PATH.read_text(encoding="utf-8"))

    def test_all_six_month_windows_and_reported_totals(self):
        result = analyze_shadow(self.load(), EXPECTED)
        self.assertEqual(result["selected_issuer_count"], 6)
        self.assertEqual(result["data_status"], "SECONDARY_ONLY_NOT_MOPS_CERTIFIED")
        self.assertEqual(result["formal_Aplus_or_Aplusplus_promoted"], 0)
        self.assertFalse(result["automated_exit"])
        self.assertFalse(result["valuation_override"])
        self.assertEqual({r["code"]: r["secondary_six_month_net_lots"] for r in result["issuers"]}, EXPECTED)
        self.assertTrue(all(r["evidence_status"] == "SECONDARY_ONLY_PENDING_ORIGINAL"
                            and not r["formal_grade_changed"] for r in result["issuers"]))

    def test_other_reason_20000_lots_cannot_be_treated_as_market_selling(self):
        snapshot = self.load()
        ft = next(x for x in snapshot["records"] if x["code"] == "9910")
        self.assertEqual(sum(ft["market_buys"]) - sum(ft["market_sells"]), 5033)
        self.assertTrue(any("20,000" in warning for warning in ft["unresolved"]))

    def test_reject_missing_months_and_false_official_promotion(self):
        snapshot = self.load()
        snapshot["records"][0]["market_buys"].pop()
        with self.assertRaisesRegex(ValueError, "MONTHLY_WINDOW_INCOMPLETE"):
            analyze_shadow(snapshot, EXPECTED)
        snapshot = self.load()
        snapshot["official_mops_post_trade_originals_received"] = True
        with self.assertRaisesRegex(ValueError, "FALSE_OFFICIAL"):
            analyze_shadow(snapshot, EXPECTED)
        snapshot = self.load()
        snapshot["formal_aplus_changed"] = True
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_FORMAL"):
            analyze_shadow(snapshot, EXPECTED)

    def test_failed_identities_or_summary_changes_are_not_silently_accepted(self):
        snapshot = self.load()
        snapshot["records"][0]["market_buys"][0] += 1
        with self.assertRaisesRegex(ValueError, "SECONDARY_MONTHLY_NET_RECONCILIATION_FAILED"):
            analyze_shadow(snapshot, EXPECTED)
        snapshot = self.load()
        snapshot["records"][0]["source_url"] = "https://example.invalid/9802"
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_OR_MISMATCHED"):
            analyze_shadow(snapshot, EXPECTED)

    def holder(self, holder_key="LEGAL_1", account_class="LEGAL_ENTITY", role="董事",
               buy=231, other_loss=0, closing=1231):
        return dict(issuer="9802", month="2026-09", holder_account_key=holder_key,
                    account_class=account_class, role=role,
                    market_buy_lots=buy, market_sell_lots=0,
                    other_gain_lots=0, other_loss_lots=other_loss,
                    pledged_lots=0, released_lots=0,
                    opening_lots=1000, closing_lots=closing)

    def test_role_duplication_deduplicates_same_account_not_other_accounts(self):
        self_holder = self.holder()
        another_role = self.holder(role="大股東")
        spouse = self.holder(holder_key="SPOUSE_2", account_class="SPOUSE_MINORS",
                             role="配偶", buy=2, closing=1002)
        summary = dedupe_primary_holder_rows([self_holder, another_role, spouse])
        self.assertEqual(summary["unique_holder_accounts"], 2)
        self.assertEqual(summary["market_buy_lots"], 233)
        self.assertEqual(summary["market_net_lots"], 233)
        self.assertFalse(summary["rollforward_exceptions"])
        self.assertFalse(summary["official_original_receipt_verified"])

    def test_nonmarket_transfer_and_pledge_never_become_trade(self):
        a = self.holder(buy=0, other_loss=200, closing=800)
        a["pledged_lots"] = 500
        result = dedupe_primary_holder_rows([a])
        self.assertEqual(result["market_net_lots"], 0)
        self.assertEqual(result["nonmarket_net_lots"], -200)
        self.assertEqual(result["unique_holder_accounts"], 1)

    def test_reject_ambiguous_holder_and_conflicting_duplicate(self):
        a = self.holder()
        b = copy.deepcopy(a)
        b["holder_account_key"] = ""
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS_HOLDER"):
            dedupe_primary_holder_rows([b])
        b = copy.deepcopy(a)
        b["market_buy_lots"] = 100
        with self.assertRaisesRegex(ValueError, "CONFLICTING_DUPLICATED"):
            dedupe_primary_holder_rows([a,b])

    def test_rollforward_mismatch_kept_as_exception_not_gate_pass(self):
        a = self.holder(closing=1232)
        r = dedupe_primary_holder_rows([a])
        self.assertEqual(r["rollforward_exceptions"][0]["reason"], "HOLDINGS_ROLLFORWARD_MISMATCH")
        self.assertEqual(r["insider_quality_gate"], "PENDING_ORIGINAL_IDENTITY_AND_PIT_CERTIFICATION")


if __name__ == "__main__":
    unittest.main()
