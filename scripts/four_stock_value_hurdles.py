#!/usr/bin/env python3
"""Four-stock inverse 2027 EPS/PE hurdle audit. Research-only, no prediction.

This module deliberately does not use the historic model's Bear/Base/Bull
probabilities, imply future returns, or issue A+ certificates. It separates
post-close disclosures from signals that existed at the reference close.
"""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
from decimal import Decimal, ROUND_CEILING

REQUIRED_CODES = {"3231", "6285", "8299", "3260"}


def _when(value):
    x = dt.datetime.fromisoformat(value)
    if x.tzinfo is None or x.utcoffset() is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return x


def _positive(value, kind):
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{kind}_NOT_FINITE_POSITIVE")
    return float(value)


def evaluate(payload):
    if payload.get("schema") != "FOUR_STOCK_VALUE_INPUT_V1":
        raise ValueError("WRONG_SCHEMA")
    close = _when(payload["reference_close_at"])
    audited = _when(payload["audited_at"])
    if audited <= close:
        raise ValueError("AUDIT_MUST_FOLLOW_REFERENCE_CLOSE")
    stocks = payload["stocks"]
    if len(stocks) != 4 or {str(s["code"]) for s in stocks} != REQUIRED_CODES:
        raise ValueError("FOUR_EXPECTED_DISTINCT_STOCKS_REQUIRED")
    records = []
    for s in stocks:
        price = _positive(s["reference_close"], "PRICE")
        pe = _positive(s["illustrative_pe"], "PE")
        eps = _positive(s["latest_2026_ytd_eps"], "YTD_EPS")
        quarters = s["reported_quarters"]
        if type(quarters) is not int or quarters not in (2, 3):
            raise ValueError("REPORTING_PERIOD_MUST_BE_H1_OR_9M")
        published = _when(s["eps_published_at"])
        if published > audited:
            raise ValueError("FUTURE_EARNINGS_DISCLOSURE")
        if s["code"] == "3231" and quarters != 2:
            raise ValueError("3231_Q3_NOT_YET_VERIFIED")
        if not isinstance(s.get("sources"), list) or not s["sources"] or not all(x.startswith('https://') for x in s["sources"]):
            raise ValueError("SOURCES_REQUIRED")
        events = []
        for event in s.get("material_events", []):
            at = _when(event["published_at"])
            if at > audited:
                raise ValueError("FUTURE_EVENT_NOT_ALLOWED")
            if not event.get("source", "").startswith('https://'):
                raise ValueError("EVENT_SOURCE_REQUIRED")
            events.append(dict(description=event["description"], published_at=event["published_at"],
                               available_by_reference_close=at <= close, source=event["source"]))
        annualized_reference = eps * 4 / quarters
        eps_for_hurdles = {
            "breakeven": price / pe,
            "upside_30pct": price * 1.30 / pe,
            "upside_35pct": price * 1.35 / pe,
        }
        records.append(dict(code=s["code"],name=s["name"],priority=s["research_priority"],
                            reference_close=price,illustrative_pe=pe,
                            latest_2026_ytd_eps=eps,reported_quarters=quarters,
                            eps_published_at=s["eps_published_at"],
                            eps_available_by_reference_close=published <= close,
                            mechanical_2026_annualized_eps=round(annualized_reference, 3),
                            eps_hurdles_2027={k:round(v, 3) for k,v in eps_for_hurdles.items()},
                            eps_for_35pct_as_fraction_of_annualized_reference=round(eps_for_hurdles["upside_35pct"] / annualized_reference,4),
                            post_close_disclosures=[e for e in events if not e["available_by_reference_close"]],
                            events=events,
                            qualitative_focus=s["qualitative_focus"],sources=s["sources"],
                            forecast_2027_eps=None,calibrated_expected_return=None,
                            formal_Aplus_certified=False))
    ranks = [x['priority'] for x in records]
    if sorted(ranks) != [1,2,3,4]:
        raise ValueError("UNIQUE_RESEARCH_PRIORITY_1_TO_4_REQUIRED")
    records.sort(key=lambda x:x['priority'])
    return dict(schema="FOUR_STOCK_VALUE_HURDLES_V1",audited_at=payload['audited_at'],
                reference_close_at=payload['reference_close_at'],
                reference_close_is_executable_entry=False,
                same_session_after_close_disclosures_not_known_at_close=True,
                status="RESEARCH_ONLY_NOT_CERTIFIED",
                methodology="reverse 2027 EPS hurdle = reference close * (1 + scenario price upside) / illustrative PE; ignores dividends, dilution changes, costs and probabilities",
                eps_annualization_warning="Reported 2026 H1 or Q1-Q3 EPS multiplied by 4/quarters is mechanical only, NOT an FY2026 or 2027 forecast; quarter seasonality and dilution not normalized",
                hurdle_price_returns_are_not_expected_returns=True,
                scenario_probabilities=None,expected_net_return=None,
                formal_grade="NOT_CERTIFIED",stocks=records)


def min_eps_2(value):
    """Ceiling: a displayed EPS hurdle must be sufficient, not just nearest."""
    return format(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_CEILING), '.2f')


def render(report):
    lines = ["# 2026-11-06 收盤四檔研究：2027 EPS × PE 反推門檻", "",
             "**研究狀態：不核發 A+、不產生機率加權期望報酬、不是當日可成交訊號。**", "",
             "股價參考日 2026-11-06；消息檢核時點：" + report['audited_at'] + "。", "",
             "本表的 PE 是明示假設、**不是**經同業及歷史PIT認證之合理本益比。對照的 EPS 為2026累計已揭露實績，不是2027預測。", "",
             "|研究優先序|股票|11/6收盤|2026已公告累計EPS|示範PE|2027保本EPS|+30%所需EPS|+35%所需EPS|",
             "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for s in report['stocks']:
        h=s['eps_hurdles_2027']
        lines.append(f"|{s['priority']}|{s['code']} {s['name']}|{s['reference_close']:.2f}|{s['latest_2026_ytd_eps']:.2f}（{s['reported_quarters']}季）|{s['illustrative_pe']:.0f}|{min_eps_2(h['breakeven'])}|{min_eps_2(h['upside_30pct'])}|{min_eps_2(h['upside_35pct'])}|")
    lines += ['', '## 逐檔確認前不可重押的事項','']
    for s in report['stocks']:
        lines.append(f"- **{s['code']} {s['name']}**：{s['qualitative_focus']}。{('公告時點晚於參考收盤，不能當作11/6收盤前訊號。' if not s['eps_available_by_reference_close'] else '')}")
        for e in s['post_close_disclosures']:
            lines.append(f"  - 盤後新增：{e['description']}，時間 {e['published_at']}；不能回填為當日可得。")
    lines += ['', '## 模型防呆', '',
              '- 所有2027 EPS、正確合理PE、機率和扣成本報酬率仍缺獨立完整認證；研究優先序不是預測勝率。',
              '- 2026累計 EPS 直接年化只為壓力測試對照，不能當作持續獲利；尤其群聯、威剛的記憶體高景氣具有循環性。',
              '- 參考收盤價不是買入成交價；若使用盤後公告，最早只能在後續可交易時段重新取得報價後評估。',
              '- 仍須查公司行動、股數稀釋、2027 EPS營運橋接、現金流／存貨、相符同業PE及真正的PIT樣本外驗證。',
              '- 不改變主模型 V8.10.8 原情境、13項品質認證及交易訊號。', '']
    return '\n'.join(lines)


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('input',type=Path)
    cli.add_argument('--json-out',type=Path,required=True)
    cli.add_argument('--md-out',type=Path,required=True)
    args=cli.parse_args()
    report=evaluate(json.loads(args.input.read_text(encoding='utf-8')))
    args.json_out.parent.mkdir(parents=True,exist_ok=True)
    args.md_out.parent.mkdir(parents=True,exist_ok=True)
    args.json_out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    args.md_out.write_text(render(report)+'\n',encoding='utf-8')
    print(f"RESEARCH_ONLY: {len(report['stocks'])} stocks; formal grade NOT_CERTIFIED")


if __name__ == '__main__':
    main()
