"""V8.9.10 independently checks publicly presented cost-of-sales composition.

Issuer slide figures are NT$ million and rounded. They identify *reported*
materials, direct labor and manufacturing overhead burden; manufacturing
overhead mixes fixed and variable, and labor includes wage levels AND learning
costs. They do NOT establish factory yield, utilization, causality or Base GM.
"""
from datetime import datetime
import math
from pathlib import Path
import re
from urllib.parse import urlparse

HEX = re.compile(r"[a-f0-9]{64}\Z")
PERIODS = ("2025-Q2", "2026-Q2")
COSTS = ("direct_materials_million", "direct_labor_million", "manufacturing_overhead_million")
ALL = ("revenue_million", "gross_profit_million") + COSTS


def _timestamp(s):
    if not isinstance(s, str):
        raise ValueError("COST_EVIDENCE_TIME_MISSING")
    try:
        value = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("COST_EVIDENCE_TIME_INVALID") from e
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("COST_EVIDENCE_TIMEZONE_REQUIRED")
    return value


def _n(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError("COST_EVIDENCE_MISSING_OR_INVALID_NUMBER")
    return float(value)


def _validate_row(raw):
    if not isinstance(raw, dict) or set(raw) != set(ALL):
        raise ValueError("COST_DISCLOSED_FIELDS_INCOMPLETE")
    v = {k: _n(raw[k]) for k in ALL}
    rev = v["revenue_million"]
    if rev <= 0:
        raise ValueError("COST_REVENUE_ZERO")
    calculated = rev - sum(v[k] for k in COSTS)
    if abs(calculated - v["gross_profit_million"]) > 2.0:
        raise ValueError("COST_COGS_GROSS_RECONCILIATION_FAILED")
    if calculated < 0:
        raise ValueError("COST_COGS_NEGATIVE_GP")
    return v


def assess_disclosed_cogs(snapshot, *, asof, standardized_accounting=None):
    """Classify observed COGS *burdens*, not which cost driver is temporary.

    standard_accounting keyed by 2025-Q2/2026-Q2 has revenue_twd and
    gross_profit_twd from official Q2 YTD minus Q1 YTD, when available.
    """
    cutoff = _timestamp(asof)
    if not isinstance(snapshot, dict) or snapshot.get("issuer") != "9802":
        raise ValueError("COST_ISSUER_ID_INVALID")
    src = snapshot.get("source")
    if not isinstance(src, dict):
        raise ValueError("COST_OFFICIAL_SOURCE_MISSING")
    url = urlparse(str(src.get("issuer_publication_url", "")))
    if url.scheme != "https" or url.hostname not in ("mopsov.twse.com.tw", "www.fulgentsun.com"):
        raise ValueError("COST_SOURCE_NOT_ISSUER_OR_MOPS")
    if (src.get("reference_kind") != "USER_UPLOADED_ISSUER_PRESENTATION_PDF"
            or src.get("report_published_on") != "2026-09-17"
            or src.get("source_page_pdf_one_indexed") != 20
            or src.get("source_page_printed") != 23):
        raise ValueError("COST_SOURCE_PAGE_OR_DOC_ID_INVALID")
    if src.get("in_repository_original_pdf_archived") is not False:
        raise ValueError("COST_RAW_PDF_REPOSITORY_STATUS_UNTRUSTWORTHY")
    if src.get("source_pdf_bytes_verified_in_analysis") is not True:
        raise ValueError("COST_UNVERIFIED_SOURCE_BYTES")
    if not HEX.fullmatch(str(src.get("original_pdf_sha256", ""))):
        raise ValueError("COST_PDF_HASH_UNVERIFIED")
    if _timestamp(src.get("available_at_conservative")) > cutoff:
        raise ValueError("COST_SOURCE_NOT_YET_PUBLIC_AT_ASOF")
    values = snapshot.get("figures")
    if not isinstance(values, dict) or set(values) != set(PERIODS):
        raise ValueError("COST_PERIODS_INCOMPLETE")
    d = {p: _validate_row(values[p]) for p in PERIODS}
    mirror_checked = standardized_accounting is not None
    if mirror_checked:
        if set(standardized_accounting) != set(PERIODS):
            raise ValueError("COST_ACCOUNTING_PERIODS_MISMATCH")
        for p in PERIODS:
            item = standardized_accounting[p]
            for raw,account in (("revenue_million","revenue_twd"),
                                ("gross_profit_million","gross_profit_twd")):
                if not isinstance(item,dict):
                    raise ValueError("COST_ACCOUNTING_NOT_OBJECT")
                actual = _n(item.get(account))/1e6
                # Issuer slide rounds NT$1m; use ≤NT$2m for two separate
                # cumulative line-item roundings and prior accounting restates.
                if abs(actual - d[p][raw]) > 2:
                    raise ValueError("COST_OFFICIAL_QUARTER_ACCOUNTING_MISMATCH_"+p+"_"+raw)
    start,end = (d[p] for p in PERIODS)
    shares = {}
    offset = {}
    for key in COSTS:
        old = 100*start[key]/start["revenue_million"]
        new = 100*end[key]/end["revenue_million"]
        shares[key] = dict(prior_pct=round(old,4),current_pct=round(new,4),
                           burden_change_pp=round(new-old,4),
                           gm_contribution_pp=round(old-new,4))
        offset[key] = old-new
    prior_gm = 100*start["gross_profit_million"]/start["revenue_million"]
    current_gm = 100*end["gross_profit_million"]/end["revenue_million"]
    calc_delta = current_gm-prior_gm
    if abs(sum(offset.values())-calc_delta) > .1:
        raise ValueError("COST_DECOMPOSITION_NOT_BALANCED")
    mat_labor = shares["direct_materials_million"]["gm_contribution_pp"] + shares["direct_labor_million"]["gm_contribution_pp"]
    overhead = shares["manufacturing_overhead_million"]["gm_contribution_pp"]
    return dict(issuer="9802",period_current=PERIODS[1],period_prior=PERIODS[0],
        status="PUBLISHED_CONSOLIDATED_COGS_SPLIT_NOT_PLANT_CAUSALITY",
        original_source_sha256=src["original_pdf_sha256"],
        original_pdf_archived_in_repository=False,
        source_pdf_verified_in_analysis=True,
        source_url=src["issuer_publication_url"],
        financial_publication_date=src["report_published_on"],
        source_pdf_page=src["source_page_pdf_one_indexed"],
        source_printed_page=src["source_page_printed"],
        figures_unit="TWD_MILLIONS_ROUNDED",
        burdens=shares,
        displayed_gross_margin_prior_pct=round(prior_gm,4),
        displayed_gross_margin_current_pct=round(current_gm,4),
        displayed_gross_margin_change_pp=round(calc_delta,4),
        materials_plus_labor_gm_effect_pp=round(mat_labor,4),
        manufacturing_overhead_gm_effect_pp=round(overhead,4),
        reconciled_to_standardized_q2_accounting=mirror_checked,
        issuer_note="Materials + labor burden grew, overhead-to-revenue fell; "
                    "gross margin decline cannot be attributed wholly to depreciation.",
        overhead_contains_mixed_fixed_and_variable_costs=True,
        direct_labor_contains_possible_new_factory_training=True,
        factory_yield_actual_verified=False,
        factory_utilization_actual_verified=False,
        segment_asp_and_product_mix_verified=False,
        wage_and_learning_driver_split_verified=False,
        price_material_cost_driver_split_verified=False,
        plant_ramp_causally_proven=False,
        recovery_time_estimated=False,base_gm_override_allowed=False,
        formal_a_plus_changed=False,model_eps_pe_target_changed=False)


def render_disclosed_cogs(result):
    p = result["burdens"]
    lines = ["## 9802｜2026/9/17法說成本結構拆解（已取得投資人簡報原始PDF）", "",
        f"來源：{result['source_url']}，PDF第{result['source_pdf_page']}頁／簡報第{result['source_printed_page']}頁；"
        f"原PDF SHA256：{result['original_source_sha256']}。",
        "**原PDF在用戶提供的文件中已核對，但尚未隨GitHub原始資料庫保存，不能宣稱在CI端完成原PDF二次查驗。**",
        "金額是百萬元整數的公司展示值，報告比率可能與精確財報相差約0.01–0.04pp。",
        "",
        "|銷貨成本項目|2025 Q2占營收|2026 Q2占營收|毛利率影響|",
        "|---|---:|---:|---:|"]
    for label,key in (("直接材料","direct_materials_million"),("直接人工","direct_labor_million"),
                      ("製造費用（固定＋變動）","manufacturing_overhead_million")):
        x=p[key]
        lines.append(f"|{label}|{x['prior_pct']:.2f}%|{x['current_pct']:.2f}%|{x['gm_contribution_pp']:+.2f}pp|")
    lines += ["",f"- **材料與人工合計毛利影響：約 {result['materials_plus_labor_gm_effect_pp']:+.2f}pp**。",
        f"- **製造費用占營收比率改善、抵銷：約 {result['manufacturing_overhead_gm_effect_pp']:+.2f}pp**。",
        f"- 四捨五入資料推算單季毛利變化 {result['displayed_gross_margin_change_pp']:+.2f}pp；公司精確毛利率為2025Q2 **18.49%**、2026Q2 **13.94%**（-4.55pp）。",
        "- 『製造費用』不是純固定折舊；其比率下降不能證明新廠折舊減少。直接人工比率上升，也可能包含新廠員工訓練與良率下降，不代表全部是永久性工資壓力。",
        "- 原簡報『各國產能變化圖』以新台幣億元表示且呈現產出分布，**不是各廠可用產能、開工率或利用率**。不得以65.9%越南占比冒充65.9%產能利用率。",
        "- **尚缺產能利用率、廠別人力與鞋雙成本、ASP／產品組合／良率、固定折舊與庫存轉列原件，因此不提高2027 Base EPS/PE，也不發出A+或Exit。**",""]
    return "\n".join(lines)
