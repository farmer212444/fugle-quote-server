#!/usr/bin/env python3
"""V8.9.6: 00905 official index-deletion PIT audit and early-risk research.

Do NOT retroactively trade the 2025-07-16 index notice at the 2025-06-30
selection data cutoff. The exact index factor Z-scores cannot be replicated
without the full historical eligible universe and issuer/PIT inputs.

This research never changes EPS, PE, Base/Bear/Bull, A+ gates, or holdings.
"""
import argparse
from datetime import datetime, date, timezone, timedelta
TAIPEI = timezone(timedelta(hours=8))
import json
import math
from pathlib import Path
import re

CODE = re.compile(r"[0-9]{4}\Z")
FACTOR_WEIGHTS = {"quality": 0.4, "value": 0.3, "momentum": 0.3}
SOURCE_LIMITATIONS = (
    "The official 00905 membership decision is not a retrospective June-30 trading signal.",
    "Even complete index membership changes do not disclose the cause for a specific deletion.",
    "The published factor methodology uses 40% quality, 30% value, 30% momentum; "
    "actual eligibility, ADTV, Z-scores and selection also require a contemporaneous issuer universe.",
    "Reported 2025Q1 margin and operating-profit gains contradict treating an EPS decline "
    "as proof that operating earnings had already deteriorated.",
    "Issuer Q2 2025 and later, changes effective after the as-of time, and hindsight price "
    "returns cannot enter a June-30-2025 decision.",
    "Rules PDF currently available does not itself prove the exact rule vintage applied in July 2025.",
    "No formal A+ grade, Base/EPS/PE estimate, transaction, calibrated likelihood or verified alpha is produced.",
)

def instant(value):
    """PIT timestamps must have an explicit timezone; date-only is ambiguous."""
    if not isinstance(value, str) or not value:
        raise ValueError("PIT_TIME_MISSING")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("PIT_TIME_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("PIT_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)

def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("PIT_DAY_INVALID")
    return date.fromisoformat(value)

def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("NUMBER_INVALID_OR_UNVERIFIED")
    return float(value)

def validate_case(item):
    if not isinstance(item, dict):
        raise ValueError("INDEX_CASE_NOT_OBJECT")
    if item.get("index_id") != "IX0137" or item.get("etf_code") != "00905":
        raise ValueError("INDEX_OR_ETF_ID_MISMATCH")
    source = str(item.get("official_notice_url") or "")
    rule = str(item.get("rule_document_url") or "")
    if not source.startswith("https://backend.taiwanindex.com.tw/") or not rule.startswith("https://backend.taiwanindex.com.tw/"):
        raise ValueError("OFFICIAL_DOCUMENT_SOURCE_MISSING")
    published = instant(item.get("announced_at"))
    effective = day(item.get("effective_date"))
    data_cutoff = day(item.get("index_data_cutoff"))
    if published.astimezone(TAIPEI).date() <= data_cutoff or effective <= published.astimezone(TAIPEI).date():
        raise ValueError("INDEX_EVENT_DATE_INCONSISTENT")
    if item.get("source_document_verified") is not True:
        raise ValueError("INDEX_NOTICE_NOT_CHECKED")
    if item.get("official_index_factor_scores_available") is not False:
        raise ValueError("OFFICIAL_FACTOR_SCORE_PROVENANCE_UNCLEAR")
    removed = item.get("removed")
    added = item.get("added")
    for group in (removed, added):
        if not isinstance(group, list) or not group or any(not CODE.fullmatch(str(code)) for code in group):
            raise ValueError("INDEX_MEMBERSHIP_LIST_INVALID")
        if len(group) != len(set(group)):
            raise ValueError("INDEX_MEMBERSHIP_DUPLICATE")
    if set(removed) & set(added):
        raise ValueError("INDEX_ADDED_REMOVED_OVERLAP")
    if len(removed) != 26 or len(added) != 44 or "9802" not in removed:
        raise ValueError("HISTORICAL_NOTICE_MEMBER_COUNT_MISMATCH")
    observation = item.get("issuer_observation")
    if not isinstance(observation, dict) or observation.get("code") != "9802":
        raise ValueError("ISSUER_OBSERVATION_MISSING")
    observed_at = instant(observation.get("available_at"))
    if observed_at >= published or observed_at.astimezone(TAIPEI).date() > data_cutoff:
        raise ValueError("ISSUER_FINANCIAL_POSTCUTOFF_OR_POSTNOTICE")
    if observation.get("period") != "2025-Q1" or not str(observation.get("source_url", "")).startswith("https://www.fulgentsun.com/"):
        raise ValueError("ISSUER_SOURCE_ID_OR_PERIOD_INVALID")
    for key in ("revenue_yoy_pct", "eps", "eps_prev_quarter", "eps_prev_year",
                "gross_margin_pct", "gross_margin_prev_year_pct",
                "operating_profit_yoy_pct", "parent_net_income_yoy_pct"):
        number(observation.get(key))
    return published, effective, data_cutoff, observed_at

def issuer_warning(observation):
    """Compare reported as-known issuer metrics, *not* official index factor scores."""
    rev = number(observation["revenue_yoy_pct"])
    eps = number(observation["eps"])
    q = number(observation["eps_prev_quarter"])
    y = number(observation["eps_prev_year"])
    op = number(observation["operating_profit_yoy_pct"])
    profit = number(observation["parent_net_income_yoy_pct"])
    gm = number(observation["gross_margin_pct"])
    old_gm = number(observation["gross_margin_prev_year_pct"])
    flags = []
    if rev > 20 and y > 0 and eps < y:
        flags.append("REVENUE_UP_EPS_YOY_DOWN")
    if eps < q:
        flags.append("EPS_QUARTERLY_MOMENTUM_DOWN")
    if op > 0 and profit < 0:
        flags.append("OPERATING_PROFIT_UP_BUT_PARENT_PROFIT_DOWN")
    if gm >= old_gm:
        flags.append("GROSS_MARGIN_NOT_YET_DETERIORATING")
    return dict(code=str(observation["code"]), period=observation["period"],
                revenue_yoy_pct=round(rev, 2),
                eps_yoy_pct=round((eps / y - 1) * 100, 2) if y else None,
                eps_qoq_pct=round((eps / q - 1) * 100, 2) if q else None,
                gross_margin_change_pp=round(gm - old_gm, 2),
                operating_profit_yoy_pct=round(op, 2),
                parent_net_income_yoy_pct=round(profit, 2),
                flags=flags, official_index_factor_score=None,
                full_index_ranking_reconstructed=False,
                issuer_raw_release_hash_verified=False,
                reason_for_00905_removal_confirmed=False)

def evaluate(item, asof):
    published, effective, cutoff, observed = validate_case(item)
    when = instant(asof)
    issuer_available = observed <= when
    event_known = published <= when
    event_effective = event_known and when.astimezone(TAIPEI).date() >= effective
    observation = issuer_warning(item["issuer_observation"]) if issuer_available else None
    if event_effective:
        event_status = "PUBLIC_INDEX_EXIT_EFFECTIVE"
    elif event_known:
        event_status = "PUBLIC_INDEX_EXIT_ANNOUNCED_NOT_YET_EFFECTIVE"
    else:
        event_status = "INDEX_EXIT_UNPUBLISHED_AT_ASOF"
    flags = list(observation["flags"]) if observation else []
    if event_known:
        flags.append("ETF_INDEX_EXIT_NOTICE_PUBLICLY_KNOWN")
    return dict(code="9802", etf_code="00905", index_id="IX0137", asof=asof,
                index_data_cutoff=cutoff.isoformat(),
                index_notice_announced_at=item["announced_at"] if event_known else None,
                effective_date=effective.isoformat() if event_known else None,
                membership_decision_known_at_asof=event_known,
                membership_exit_effective_at_asof=event_effective,
                issuer_observation_available_at_asof=issuer_available,
                issuer_evidence=observation,
                event_status=event_status, flags=flags,
                official_factor_weights=FACTOR_WEIGHTS,
                historical_2025_index_rule_vintage_verified=False,
                full_universe_market_cap_liquidity_verified=False,
                full_5year_financial_quality_inputs_verified=False,
                stock_price_momentum_adjusted_series_verified=False,
                full_universe_factor_zscores_verified=False,
                index_eligibility_rank_replicated=False,
                factor_causing_removal_determined=False,
                return_backtest_performance=None, trading_action=None,
                model_eps_or_pe_changed=False, formal_Aplus_changed=False)

def build(item):
    """Freeze informative viewpoints without leaking the ex-post index decision."""
    checkpoints = [
        "2025-04-21T23:59:59+08:00", # even 2025Q1 earnings not yet in public view
        "2025-06-30T23:59:59+08:00", # index inputs frozen, exit not announced
        "2025-07-16T16:59:59+08:00", # one second before release
        "2025-07-16T17:00:00+08:00", # first confirmed public index decision
        "2025-07-17T09:00:00+08:00", # public effective session
    ]
    results = [evaluate(item, point) for point in checkpoints]
    if results[1]["membership_decision_known_at_asof"] or not results[3]["membership_decision_known_at_asof"]:
        raise ValueError("PIT_EVENT_DISCLOSURE_LEAKAGE")
    return dict(status="00905_2025_INDEX_EXIT_CASE_STUDY_RESEARCH_ONLY",
                data_event="00905_2025_07_16_OFFICIAL_INDEX_MEMBERSHIP_CHANGE",
                index_selection_cutoff=item["index_data_cutoff"],
                notice_url=item["official_notice_url"],
                rule_document_url=item["rule_document_url"],
                notice_source_verified=True, raw_pdf_archived=False,
                factor_attribution="NOT_POSSIBLE_WITHOUT_INDEX_UNIVERSE_ZSCORES",
                issuer_reference_source=item["issuer_observation"]["source_url"],
                weight_methodology=FACTOR_WEIGHTS, input_checkpoints=results,
                added_count=len(item["added"]), removed_count=len(item["removed"]),
                added_codes=item["added"], removed_codes=item["removed"],
                formal_Aplus_changed=False, base_target_price_changed=False,
                backtest_alpha_verified=False, no_auto_exit=True,
                limitations=list(SOURCE_LIMITATIONS))

def render(result):
    rows = [
        "# 00905於2025年7月剔除9802：PIT多因子風險檢查",
        "",
        "**研究性質：可驗證官方剔除事件；尚未重現00905在當時的每一檔因子分數，也尚未證明是哪一個因子導致剔除。**",
        "",
        "- 臺灣指數公司：審核資料截止2025-06-30，公告2025-07-16 17:00，2025-07-17起生效。",
        "- 當次新增44檔、刪除26檔；9802鈺齊為刪除之一。",
        "- 公告日期不能倒填到2025-06-30的選股回測；盤後17:00才是這份剔除公告能被交易策略看到的最早公開時點。",
        "- 指數2020版官方文件記載品質40%、價值30%、動能30%；實際歷史規則版本及個股Z分數尚未逐項還原。",
        "",
        "|PIT觀察點|2025Q1資訊已公開|00905剔除已公開|觀察身分|",
        "|---|---|---|---|",
    ]
    for row in result["input_checkpoints"]:
        rows.append(f"|{row['asof']}|{'是' if row['issuer_observation_available_at_asof'] else '否'}|"
                    f"{'是' if row['membership_decision_known_at_asof'] else '否'}|{row['event_status']}|")
    early = result["input_checkpoints"][1]["issuer_evidence"]
    if early:
        rows += ["", "## 2025-06-30時已知的9802訊號", "",
                 f"- 2025Q1營收同比：{early['revenue_yoy_pct']:+.2f}%；EPS同比：{early['eps_yoy_pct']:+.2f}%，環比：{early['eps_qoq_pct']:+.2f}%。",
                 f"- 毛利率同比：{early['gross_margin_change_pp']:+.2f}pp；本業營業利益同比：{early['operating_profit_yoy_pct']:+.2f}%；歸母純益同比：{early['parent_net_income_yoy_pct']:+.2f}%。",
                 f"- 證據旗標：{', '.join(early['flags'])}。",
                 "- **注意：本業營業利益明顯增長，所以不能把EPS下滑當成公司本業已衰退的證據。**",
                 "- 此處僅為事前可觀測的風險診斷，**不是成功預測00905會剔除9802的事前訊號績效**。"]
    rows += ["", "## 官方證據與侷限", "",
             f"- 00905編製規則：{result['rule_document_url']}",
             f"- 2025/7/16調整公告：{result['notice_url']}",
             f"- 鈺齊2025/4/22財報新聞稿：{result['issuer_reference_source']}",
             "- 以下項目仍阻擋歷史全市場排名及00905實際剔除原因判定：",
             *("- "+s for s in result["limitations"]), ""]
    return "\n".join(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="tw-market-data")
    args = ap.parse_args()
    root = Path(args.data_dir)
    path = root / "etf" / "index_reviews" / "2025-07-16_00905.json"
    item = json.loads(path.read_text(encoding="utf-8"))
    report = build(item)
    rank = root / "rankings"
    rank.mkdir(parents=True, exist_ok=True)
    (rank / "v896_00905_exit_pit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (rank / "v896_00905_exit_pit.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "early_warnings": len(report["input_checkpoints"][1]["issuer_evidence"]["flags"]),
                      "indexed_membership_disclosed_by_cutoff": False, "formal_grade_changes": 0}, ensure_ascii=False))

if __name__ == "__main__":
    main()
