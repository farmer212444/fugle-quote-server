#!/usr/bin/env python3
"""V8.A6 TIP ETF-index constituent event watch, conservative research only.

An official INDEX constituent addition/deletion does not prove a fund trade.
Retrospective examples lack original at-the-time immutable capture: never
backfill them as live historical PIT signals or imply strategy win rates.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

TAIPEI = dt.timezone(dt.timedelta(hours=8))
SCHEMA = "V8A6_TIP_INDEX_CONSTITUENT_EVENT_LEDGER_V1"
SOURCE_LEVEL = "PRIMARY_OFFICIAL_NOTICE_TEXT_VISUALLY_CHECKED_NO_PDF_SHA256"
ALERT_DAYS = 120


def require(ok, message):
    if not ok:
        raise ValueError(message)


def parse_time(value):
    d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    require(d.tzinfo is not None, "UNZONED_SOURCE_TIMESTAMP")
    return d.astimezone(TAIPEI)


def source_url(url, kind):
    p = urlsplit(str(url))
    allowed = {"bulletin": ("taiwanindex.com.tw", r"/news/[0-9]+"),
               "pdf": ("backend.taiwanindex.com.tw",
                       r"/api/downloadFile/TechnicalNotices/[0-9]+/tw")}
    host, path_pattern = allowed[kind]
    require(p.scheme == "https" and p.netloc == host
            and re.fullmatch(path_pattern, p.path) is not None
            and not p.query and not p.fragment and not p.username,
            "ETF_SOURCE_NOT_EXACT_OFFICIAL_URL_" + kind)
    return url


def original_receipt(record, root, asof):
    """Re-hash actual captured notice PDF; false if none was archived."""
    observed = record.get("first_system_observed_at")
    if observed is None:
        require(record.get("original_pdf_sha256") is None
                and record.get("archive_path") is None,
                "ETF_MISSING_FIRST_OBSERVATION_WITH_FAKE_ARCHIVE")
        return False
    first = parse_time(observed)
    published = parse_time(record["published_at"])
    require(first >= published, "ETF_ORIGINAL_FIRST_SEEN_BACKDATED")
    if first > asof:
        return False
    stamp = record.get("original_pdf_sha256")
    rel = record.get("archive_path")
    require(isinstance(stamp, str) and re.fullmatch("[0-9a-f]{64}", stamp)
            and isinstance(rel, str), "ETF_ORIGINAL_ARCHIVE_RECEIPT_MISSING")
    part = Path(rel)
    require(not part.is_absolute() and ".." not in part.parts
            and part.parts[:3] == ("evidence", "v880", "etf_notices")
            and len(part.parts) == 4 and part.suffix.lower() == ".pdf",
            "ETF_ORIGINAL_ARCHIVE_PATH_UNSAFE")
    root = Path(root).resolve()
    dest = (root / part).resolve()
    require(dest.is_relative_to(root / "evidence/v880/etf_notices"),
            "ETF_ORIGINAL_ARCHIVE_ESCAPES_ROOT")
    raw = dest.read_bytes()
    require(500 <= len(raw) <= 8_000_000
            and raw.startswith(b"%PDF-") and b"%%EOF" in raw[-4096:]
            and hashlib.sha256(raw).hexdigest() == stamp,
            "ETF_ORIGINAL_NOTICE_PDF_HASH_MISMATCH")
    return True


def validate_ledger(ledger, root, asof):
    """Reject impossible, counterfeit, duplicated, or future-dated events."""
    require(ledger.get("schema") == SCHEMA
            and ledger.get("proof_of_actual_etf_trades") is False
            and ledger.get("historical_notice_publication_point_in_time_independently_certified") is False,
            "ETF_FALSE_OR_UNKNOWN_PUBLISHER_LEDGER")
    reference = dt.date.fromisoformat(ledger["events_retroactively_researched_on"])
    require(reference <= asof.date(), "ETF_RETROSPECTIVE_EVENT_LEDGER_NOT_YET_CREATED")
    items = ledger.get("events")
    require(isinstance(items, list) and len(items) <= 20000,
            "ETF_INDEX_EVENT_LEDGER_INVALID")
    keys = set()
    out = []
    for e in items:
        code, etf = str(e.get("stock_code")), str(e.get("etf_code"))
        require(re.fullmatch(r"[0-9]{4}", code) and re.fullmatch(r"[0-9]{5}", etf)
                and e.get("stock_market") in ("TWSE", "TPEX")
                and e.get("direction") in ("ADD", "DELETE")
                and e.get("source_level") == SOURCE_LEVEL
                and e.get("historical_PIT_original_independently_verified") is False,
                "ETF_EVENT_IDENTITY_OR_FALSE_CERTIFICATE")
        require(e.get("id") == f"TIP-{etf}-{code}-{e['effective_date'].replace('-', '')}-{e['direction']}",
                "ETF_EVENT_ID_INCONSISTENT")
        published = parse_time(e["published_at"])
        effective = dt.date.fromisoformat(e["effective_date"])
        ref = dt.date.fromisoformat(e["notice_reference_date"])
        require(ref <= published.date() < effective
                and (effective - published.date()).days <= 7,
                "ETF_PUBLISHED_EFFECTIVE_OR_REFERENCE_DATE_WRONG")
        source_url(e["bulletin_url"], "bulletin")
        source_url(e["primary_technical_notice_pdf"], "pdf")
        key = (etf, code, effective)
        require(key not in keys, "ETF_DUPLICATE_OR_CONFLICTING_COMPONENT_CHANGE")
        keys.add(key)
        # For a forward captured original, source bytes must be available
        # and hash-verifiable before any recent event can be called actionable.
        proven = original_receipt(e, root, asof)
        if published > asof:
            continue
        out.append({**e, "official_original_notice_bytes_checked_asof":proven})
    return sorted(out, key=lambda x:(x["published_at"],x["id"]))


def financial_downtrend(focus, asof):
    """2026Q3 self-report, admitted only from the following calendar day."""
    base = dict(status="UNAVAILABLE_OR_NOT_PIT_SAFE",gross_margin_yoy_change_pp=None,
                eps_yoy_change_pct=None,declining=False,
                source="SELF_REPORTED_NOT_SIGNED_QUARTERLY_STATEMENTS")
    if not focus or focus.get("code") != "9802" or focus.get("period") != "2026-Q3":
        return base
    day = dt.date.fromisoformat(focus["disclosed_at"])
    if day >= asof.date():
        return base  # no intraday announcement time; avoid same-day hindsight
    cur, prev = focus.get("q3_2026"), focus.get("q3_2025")
    if not isinstance(cur, dict) or not isinstance(prev, dict):
        return base
    try:
        rev, gross, eps = (float(cur[k]) for k in ("revenue", "gross_profit", "eps"))
        oldrev, oldgross, oldeps = (float(prev[k]) for k in ("revenue", "gross_profit", "eps"))
    except (TypeError, ValueError, KeyError):
        return base
    if (not all(math.isfinite(x) for x in (rev,gross,eps,oldrev,oldgross,oldeps))
            or rev <= 0 or oldrev <= 0 or oldeps <= 0):
        return base
    gm_delta = 100 * (gross / rev - oldgross / oldrev)
    eps_delta = 100 * (eps / oldeps - 1)
    return dict(status="PUBLISHED_SELF_REPORTED_FINANCIAL_SHADOW",
                gross_margin_yoy_change_pp=round(gm_delta, 2),
                eps_yoy_change_pct=round(eps_delta, 2),
                declining=gm_delta <= -2 and eps_delta <= -20,
                source=focus.get("source_url"),
                audited_full_notes_verified=False,
                original_filing_publication_PIT_independently_certified=False)


def chip_weakness(chip, code, asof_market):
    base=dict(status="CHIP_HISTORY_INCOMPLETE",big_holder_change_pp=None,
              recent_trust_retreat_observed=False,weakness_confirmed=False)
    if not chip or chip.get("asof_price_date") != asof_market:
        return base
    rows=chip.get("stocks")
    if not isinstance(rows,list):
        return base
    matches=[x for x in rows if x.get("code")==code]
    if len(matches)!=1:
        return base
    r=matches[0]
    weekly=r.get("tdcc_weekly_change_pp")
    flow=r.get("institutional_retreat_20d") or {}
    if (weekly is None or isinstance(weekly,bool)
            or not isinstance(weekly,(int,float)) or not math.isfinite(weekly)):
        weekly=None
    retreat=(flow.get("status") == "OBSERVED_RETREAT_REQUIRES_FUNDAMENTAL_REVIEW"
             and isinstance(flow.get("observation_end"),str)
             and flow["observation_end"] <= asof_market)
    return dict(status="SOME_CHIP_SOURCE_OBSERVED_NOT_CERTIFIED",
                big_holder_change_pp=weekly,
                tdcc_level_12_15_is_not_identified_insider=True,
                recent_trust_retreat_observed=retreat,
                weakness_confirmed=(weekly is not None and weekly <= -0.5) or retreat,
                chip_asof=asof_market,formal_insider_gate_unchanged=True)


def annotate_stock(events, stock_code, asof, asof_market, chip=None, focus=None):
    history=[e for e in events if e["stock_code"]==stock_code]
    added=sum(e["direction"]=="ADD" for e in history)
    removed=sum(e["direction"]=="DELETE" for e in history)
    latest=history[-1] if history else None
    # Only actually source-archived, recent and not subsequently re-added
    # removals qualify as a current signal. Historic 2025 events are context.
    active=[]
    for e in history:
        if e["direction"]!="DELETE":
            continue
        days=(asof.date()-dt.date.fromisoformat(e["effective_date"])).days
        if not (0 <= days <= ALERT_DAYS and e["official_original_notice_bytes_checked_asof"]):
            continue
        if any(x["direction"]=="ADD" and x["etf_code"]==e["etf_code"]
               and x["published_at"]>e["published_at"] for x in history):
            continue
        active.append(e)
    chips=chip_weakness(chip,stock_code,asof_market)
    fundamentals=financial_downtrend(focus,asof) if stock_code=="9802" else dict(
        status="NO_MATCHED_ORIGINAL_QUARTERLY_COMPARISON",
        declining=False)
    convergence=bool(active and chips["weakness_confirmed"] and fundamentals["declining"])
    state=("THREE_WAY_ETF_CHIP_EARNINGS_REVIEW_ONLY" if convergence else
           "RECENT_ARCHIVED_INDEX_DELETE_REQUIRES_INDEPENDENT_REVIEW" if active else
           "HISTORICAL_ETF_EVENT_CONTEXT_NOT_CURRENT_SIGNAL" if history else
           "NO_EVENTS_IN_PARTIAL_COVERAGE_NOT_PROOF_OF_HOLDINGS")
    return dict(stock_code=stock_code,asof_price_date=asof_market,
                event_history_count=len(history),adds=added,deletes=removed,
                last_event={k:latest.get(k) for k in (
                    "id","etf_code","direction","published_at","effective_date",
                    "primary_technical_notice_pdf")} if latest else None,
                history=history,live_archived_deletions_120d=len(active),
                current_alert_eligible_etfs=sorted({x["etf_code"] for x in active}),
                chip=chips,earnings=fundamentals,
                three_way_convergence_observed=convergence,
                research_review_status=state,
                retrospective_event_is_not_a_backtested_2025_signal=True,
                formal_13_gate_passes_added=0,formal_Aplus_added=0,
                EPS_PE_Base_unchanged=True,automated_trade_or_exit=False)


def build_report(ledger, research, chip, focus, root):
    vintage=parse_time(research["estimate_vintage"])
    asof_market=research["asof_price_date"]
    require(dt.date.fromisoformat(asof_market) <= vintage.date()
            and research.get("formal_Aplus_count",0) >= 0,
            "ETF_RESEARCH_PRICE_VINTAGE_INVALID")
    visible=validate_ledger(ledger,root,vintage)
    codes={"9802","6206"}
    ranked=research.get("top30_provisional",[])
    codes.update(r.get("code") for r in ranked if re.fullmatch(r"[0-9]{4}",str(r.get("code",""))))
    by_code={code:annotate_stock(visible,code,vintage,asof_market,chip,focus)
             for code in sorted(codes)}
    return dict(schema="V8A6_ETF_INDEX_ROTATION_RESEARCH_WATCH",
                model=research.get("model"),estimate_vintage=research["estimate_vintage"],
                asof_price_date=asof_market,
                historical_source_coverage_complete=False,
                documented_index_families=["00733","00905"],
                documented_company_codes=["9802"],
                selected_official_9802_events=len(visible),
                live_qualified_recent_deletions=sum(r["live_archived_deletions_120d"]
                    for r in by_code.values()),
                risk_review_candidates=[k for k,v in by_code.items() if
                                        v["three_way_convergence_observed"]],
                stocks=by_code,base_ranking_and_2027_model_unchanged=True,
                formal_Aplus_created=0,
                performance_or_win_rate_backtest_completed=False,
                limits=[
                    "Index additions/deletions are not executed ETF transactions.",
                    "Ledger currently documents selected 9802 changes in 00733 and 00905 only.",
                    "Historical official notice PDFs linked; original 2025 PIT bytes not archived when first released.",
                    "Old deletions >120 days cannot trigger new current sell warnings.",
                    "TDCC cohort movements do not identify individual institutions or insiders.",
                    "No sample-outcomes or counterfactual ETF signal hit-rate testing yet.",
                    "Missing history for 6206 or other tracked equities is coverage, not an absence of ETF ownership."
                ])


def markdown(report):
    focus=report["stocks"]["9802"]
    lines=[
        "# V8.A6 ETF成分股異動 × 籌碼 × 獲利交叉驗證（研究警示）","",
        f"模型時間：{report['estimate_vintage']}；官方股價基準：{report['asof_price_date']}。",
        "**不變更原Base、2027 EPS、PE、正式A+、13項品質門檻或Exit。**","",
        "|公告日（公布後才可見）|ETF|9802異動|生效日|證據層級|",
        "|---|---|---|---|---|"
    ]
    for e in focus["history"]:
        lines.append(
            f"|{e['published_at']}|{e['etf_code']} {e['etf_name']}|"
            f"{'剔除' if e['direction']=='DELETE' else '納入'}|{e['effective_date']}|"
            "官方指數技術通知（歷史回補，未保存當時PIT原件）|")
    lines += [
        "","## 9802目前結論","",
        f"研究分類：**{focus['research_review_status']}**。",
        f"歷史事件：剔除{focus['deletes']}次、納入{focus['adds']}次；"
        f"已歸檔且120日內可構成現時警訊的ETF剔除：**{focus['live_archived_deletions_120d']}次**。",
        "不能因2025年7月的剔除，便在2026年10月宣稱ETF今天剛出場。",
        f"集保／投信資料：{focus['chip']['status']}；"
        f"公司獲利：{focus['earnings']['status']}。",
        "三訊號同時核對僅作風險覆核，不經樣本外回測不得稱為有統計勝率的買賣規則。",
        "","## 限制",""
    ] + ["- "+v for v in report["limits"]]
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir", default="tw-market-data")
    a=p.parse_args()
    root=Path(a.data_dir)
    def read(relative):
        return json.loads((root/relative).read_text(encoding="utf-8"))
    ledger=read("evidence/v880/etf_index_constituent_events.json")
    research=read("rankings/latest_research.json")
    chip_path=root/"rankings/chip_coverage.json"
    chip=read("rankings/chip_coverage.json") if chip_path.exists() else None
    focus_path=root/"evidence/v880/issuer_reviews/9802_q3_20261020_self_report.json"
    focus=read("evidence/v880/issuer_reviews/9802_q3_20261020_self_report.json") if focus_path.exists() else None
    out=build_report(ledger,research,chip,focus,root)
    folder=root/"rankings"
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"v8a6_etf_rotation_watch.json").write_text(
        json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (folder/"v8a6_etf_rotation_watch.md").write_text(markdown(out),encoding="utf-8")
    print(json.dumps(dict(model=out["model"],asof=out["asof_price_date"],
        events=out["selected_official_9802_events"],
        recent_eligible_deletions=out["live_qualified_recent_deletions"],
        official_Aplus_added=out["formal_Aplus_created"],
        status_9802=out["stocks"]["9802"]["research_review_status"]),ensure_ascii=False))


if __name__=="__main__":
    main()
