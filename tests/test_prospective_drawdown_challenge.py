"""Prospective drawdown challenge: never retrofit a 2026 crash signal."""
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prospective_drawdown_challenge import issue, verify, report, make, pr_archive_has_newer_dated_market_source

ASOF="2026-11-09"
FORMED="2026-11-09T18:55:31+08:00"
NOW=dt.datetime.fromisoformat("2026-11-10T08:45:00+08:00")
VALID_GIT_SHA="0123456789abcdef0123456789abcdef01234567"

def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def digest(blob):
    return hashlib.sha256(blob).hexdigest()

def prepare(root):
    quote=[dict(date=ASOF,market="TWSE",code="2317",close=239.0),
           dict(date=ASOF,market="TPEX",code="2724",close=None)]
    save(root/"prices/2026-11-09.json",quote)
    qblob=(root/"prices/2026-11-09.json").read_bytes()
    save(root/"prices/latest_manifest.json",
         dict(date=ASOF,normalized_sha256=digest(qblob),total=2))
    quality=dict(schema="V8A5_QUALITY_DECISION_RESEARCH_SHADOW",
                 asof_price_date=ASOF,estimate_vintage=FORMED)
    save(root/"rankings/v8a5_quality_decision_lane.json",quality)
    qhash=digest((root/"rankings/v8a5_quality_decision_lane.json").read_bytes())
    risks=[dict(code="2317",market="TWSE",status="PAUSE_SHARP_DRAWDOWN_RESEARCH",
                latest_close=239.0,provisional_pause=True,
                session_coverage={"20":False,"60":False}),
           dict(code="2724",market="TPEX",status="PENDING_MISSING_CURRENT_CLOSE",
                latest_close=None,provisional_pause=False,
                session_coverage={"20":False,"60":False})]
    risk=dict(schema="V8108_MARKETWIDE_DRAWDOWN_COVERAGE_V1",
         price_date=ASOF,estimate_vintage=FORMED,
         source_sha256={"quality":qhash,"dated_prices":{ASOF:digest(qblob)}},
         marketwide_snapshot_rows=2,
         formal_Aplus_added=0,trade_signals_created=0,
         calibrated_oos_strategy_improvement=False,
         corporate_actions_and_total_returns_verified=False,
         historical_issuer_capture_point_in_time_verified=False,
         issuers=risks)
    save(root/"rankings/latest_marketwide_drawdown_coverage.json",risk)

class ProspectiveRegistryTests(unittest.TestCase):
    def test_issue_then_rerun_keeps_first_timestamp_and_universe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            first=issue(root,NOW,VALID_GIT_SHA)
            self.assertEqual(first["status"],"FIRST_PROSPECTIVE_REGISTRATION_NO_OOS_RESULTS")
            path=Path(first["path"])
            previous=path.read_bytes()
            obj=verify(path)
            self.assertEqual(obj["issuer_count"],2)
            self.assertEqual(obj["risk_counts"]["PAUSE_SHARP_DRAWDOWN_RESEARCH"],1)
            self.assertEqual(obj["registered_at_utc"],NOW.astimezone(dt.timezone.utc).isoformat())
            self.assertEqual(obj["next_session_eligible_only_after"],
                             NOW.astimezone(dt.timezone.utc).isoformat())
            self.assertFalse(obj["official_historical_PIT_certified"])
            self.assertIsNone(obj["first_eligible_market_open"])
            self.assertEqual(obj["verified_future_returns"],0)
            later=NOW+dt.timedelta(hours=4)
            result=issue(root,later,VALID_GIT_SHA)
            self.assertEqual(result["status"],"ALREADY_FROZEN_FIRST_REGISTRATION_PRESERVED")
            self.assertEqual(path.read_bytes(),previous)
            self.assertEqual(report(root)["verified_forward_returns"],0)

    def test_pr_smoke_does_not_backregister_old_risk_after_new_market_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            self.assertFalse(pr_archive_has_newer_dated_market_source(root))
            manifest=root/"prices/latest_manifest.json"
            doc=json.loads(manifest.read_text())
            doc["date"]="2026-11-10"
            save(manifest,doc)
            self.assertTrue(pr_archive_has_newer_dated_market_source(root))
            with self.assertRaisesRegex(ValueError,"MARKET_PRICE_SOURCE_HASH_CONFLICT"):
                make(root,NOW)

    def test_pr_smoke_does_not_skip_market_behind_report_or_unparseable_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            path=root/"prices/latest_manifest.json"
            m=json.loads(path.read_text())
            m["date"]="2026-11-08"
            save(path,m)
            with self.assertRaisesRegex(ValueError,"PR_SMOKE_MARKET_BEHIND_RESEARCH"):
                pr_archive_has_newer_dated_market_source(root)
            m["date"]="11/10/2026"
            save(path,m)
            with self.assertRaisesRegex(ValueError,"PR_SMOKE_SOURCE_DATE_INVALID"):
                pr_archive_has_newer_dated_market_source(root)

    def test_tampering_frozen_risk_labels_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            f=Path(issue(root,NOW)["path"])
            obj=json.loads(f.read_text())
            obj["issuers"][0]["risk_state"]="NO_PROVISIONAL_PRICE_THRESHOLD_HIT_NOT_CERTIFIED_SAFE"
            save(f,obj)
            with self.assertRaisesRegex(ValueError,"CHANGED_COHORT"):
                issue(root,NOW+dt.timedelta(hours=1))

    def test_future_model_or_source_quote_not_admitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            with self.assertRaisesRegex(ValueError,"FUTURE_ESTIMATE"):
                issue(root,dt.datetime.fromisoformat("2026-11-09T14:00:00+08:00"))
            p=root/"prices/2026-11-09.json"
            quotes=json.loads(p.read_text())
            quotes[0]["close"]=250.0
            save(p,quotes)
            with self.assertRaisesRegex(ValueError,"MARKET_PRICE_SOURCE_HASH"):
                issue(root,NOW)

    def test_invalid_quality_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            p=root/"rankings/v8a5_quality_decision_lane.json"
            q=json.loads(p.read_text())
            q["unapproved_revision"]="later"
            save(p,q)
            with self.assertRaisesRegex(ValueError,"QUALITY_CONTENT_HASH_MISMATCH"):
                issue(root,NOW)

    def test_stale_first_registration_never_backdated_to_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            with self.assertRaisesRegex(ValueError,"STALE_FIRST_REGISTRATION"):
                issue(root,NOW+dt.timedelta(days=12))

    def test_unknown_universe_member_fails_instead_of_hiding_delisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root)
            risk=root/"rankings/latest_marketwide_drawdown_coverage.json"
            doc=json.loads(risk.read_text())
            doc["issuers"]=doc["issuers"][:-1]
            save(risk,doc)
            with self.assertRaisesRegex(ValueError,"MISSING_RISK_MEMBERS"):
                issue(root,NOW)

if __name__=="__main__":
    unittest.main()
