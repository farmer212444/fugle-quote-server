"""Reconcile preserved MOPS general-industry YTD income, never forecast EPS.

This adapter reads factual shared snapshots without importing V8 estimates,
scores or gates. Normalized-byte integrity is not original-source authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re

from alphamax.core import ContractError
from alphamax.earnings_bridge import _time


FIELDS = {
    "revenue_twd": "營業收入", "cost_of_revenue_twd": "營業成本",
    "gross_profit_twd": "營業毛利（毛損）", "net_gross_profit_twd": "營業毛利（毛損）淨額",
    "operating_expenses_twd": "營業費用", "operating_profit_twd": "營業利益（損失）",
    "net_nonoperating_income_twd": "營業外收入及支出", "pretax_profit_twd": "稅前淨利（淨損）",
    "tax_expense_twd": "所得稅費用（利益）", "net_profit_twd": "本期淨利（淨損）",
    "parent_profit_twd": "淨利（淨損）歸屬於母公司業主",
    "noncontrolling_profit_twd": "淨利（淨損）歸屬於非控制權益",
}
UNITS = {"money": "TWD_thousands", "eps": "TWD_per_share", "period_basis": "year_to_date"}


def _decimal(value, field):
    if type(value) not in (str, int, float) or isinstance(value, bool):
        raise ContractError("INVALID_REPORTED_NUMBER:" + field)
    if isinstance(value, str) and not value.strip():
        raise ContractError("MISSING_REPORTED_NUMBER:" + field)
    try:
        number = Decimal(str(value).replace(",", ""))
    except InvalidOperation as exc:
        raise ContractError("INVALID_REPORTED_NUMBER:" + field) from exc
    if not number.is_finite() or not isfinite(float(number)):
        raise ContractError("NONFINITE_REPORTED_NUMBER:" + field)
    return number


def reconcile_income(row, *, units):
    """Use declared source units. No annualization or share-count inference."""
    if units != UNITS:
        raise ContractError("EXPLICIT_SUPPORTED_REPORTED_UNITS_REQUIRED")
    if not isinstance(row, dict) or not isinstance(row.get("公司代號"), str):
        raise ContractError("ISSUER_ID_REQUIRED")
    if not re.fullmatch(r"\d{2,3}", str(row.get("年度", ""))) or str(row.get("季別")) not in "1234" or len(str(row.get("季別"))) != 1:
        raise ContractError("REPORTED_PERIOD_REQUIRED")
    year, quarter = int(row["年度"]) + 1911, int(row["季別"])
    amounts = {name: _decimal(row.get(key), key) * 1000 for name, key in FIELDS.items()}
    eps = _decimal(row.get("基本每股盈餘（元）"), "基本每股盈餘（元）")
    other_raw = row.get("其他收益及費損淨額")
    other_observed = other_raw is not None and str(other_raw).strip() != ""
    other = (_decimal(other_raw, "其他收益及費損淨額") * 1000 if other_observed else
             amounts["operating_profit_twd"] - amounts["net_gross_profit_twd"] + amounts["operating_expenses_twd"])
    discontinued_raw = row.get("停業單位損益")
    discontinued_observed = discontinued_raw is not None and str(discontinued_raw).strip() != ""
    discontinued = (_decimal(discontinued_raw, "停業單位損益") * 1000 if discontinued_observed else Decimal(0))
    residuals = {
        "revenue_less_cost_to_gross_profit": amounts["revenue_twd"] - amounts["cost_of_revenue_twd"] - amounts["gross_profit_twd"],
        "operating_profit_including_other_operating_income": amounts["net_gross_profit_twd"] - amounts["operating_expenses_twd"] + other - amounts["operating_profit_twd"],
        "operating_plus_nonoperating_to_pretax": amounts["operating_profit_twd"] + amounts["net_nonoperating_income_twd"] - amounts["pretax_profit_twd"],
        "pretax_less_tax_plus_discontinued_to_net": amounts["pretax_profit_twd"] - amounts["tax_expense_twd"] + discontinued - amounts["net_profit_twd"],
        "parent_plus_noncontrolling_to_net": amounts["parent_profit_twd"] + amounts["noncontrolling_profit_twd"] - amounts["net_profit_twd"],
    }
    checks = {k: abs(v) <= 1000 for k, v in residuals.items()}
    revenue = amounts["revenue_twd"]
    inputs = {
        "revenue_twd": float(revenue),
        "gross_margin": float(amounts["net_gross_profit_twd"] / revenue) if revenue > 0 else None,
        "operating_expenses_twd": float(amounts["operating_expenses_twd"]),
        "other_operating_income_twd": float(other),
        "net_nonoperating_income_twd": float(amounts["net_nonoperating_income_twd"]),
        "effective_tax_rate": float(amounts["tax_expense_twd"] / amounts["pretax_profit_twd"]) if amounts["pretax_profit_twd"] > 0 else None,
        "noncontrolling_profit_twd": float(amounts["noncontrolling_profit_twd"]),
        "diluted_shares": None, "exit_pe": None, "net_dividends_per_share_twd": None,
    }
    return {
        "code": row["公司代號"], "name": row.get("公司名稱"), "fiscal_period": f"{year}Q{quarter}",
        "period_basis": "year_to_date", "covered_months": quarter * 3,
        "source_batch_date": row.get("出表日期"),
        "status": "RECONCILED_REPORTED_FACTS_ONLY" if all(checks.values()) else "REVIEW_STATEMENT_RESIDUALS",
        "reported_amounts_twd": {k: float(v) for k, v in amounts.items()},
        "reported_basic_eps_twd": float(eps), "calculated_diluted_eps_twd": None,
        "operating_inputs_for_same_reported_period_only": inputs,
        "other_operating_income_basis": "SEPARATELY_REPORTED" if other_observed else "ALGEBRAIC_RESIDUAL_NOT_SEPARATELY_REPORTED",
        "discontinued_profit_basis": "SEPARATELY_REPORTED" if discontinued_observed else "BLANK_NOT_SEPARATELY_REPORTED_ZERO_USED_FOR_RECONCILIATION_ONLY",
        "checks": checks, "residuals_twd": {k: float(v) for k, v in residuals.items()},
        "independent_operating_line_check": other_observed,
        "bridge_ready_for_forecast": False, "buy_signal": False,
        "blockers": ["ACTUAL_DILUTED_WEIGHTED_AVERAGE_SHARES_NOT_IN_SUMMARY", "FORWARD_OPERATING_ASSUMPTIONS_NOT_ESTIMATED", "COMPLETE_STATEMENTS_AND_NOTES_NOT_REVIEWED"],
    }


def reported_income_snapshot(root, *, codes, source_commit, units, asof=None):
    """Validate an immutable normalized capture, isolating per-issuer gaps."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit or ""):
        raise ContractError("PINNED_SOURCE_COMMIT_REQUIRED")
    if units != UNITS:
        raise ContractError("EXPLICIT_SUPPORTED_REPORTED_UNITS_REQUIRED")
    if (not isinstance(codes, (list, tuple)) or not codes
            or any(not isinstance(c, str) or not re.fullmatch(r"\d{4}", c) for c in codes)
            or len(codes) != len(set(codes))):
        raise ContractError("UNIQUE_FOUR_DIGIT_FOCUS_CODES_REQUIRED")
    asof = datetime.now(timezone.utc) if asof is None else _time(asof)
    if asof > datetime.now(timezone.utc):
        raise ContractError("ASOF_IN_FUTURE")
    root = Path(root).resolve()
    manifest_path = root / "tw-market-data/financial/latest_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise ContractError("INVALID_FINANCIAL_MANIFEST")
    captured = _time(manifest.get("captured_utc"))
    if captured > asof:
        raise ContractError("SNAPSHOT_NOT_CAPTURED_AT_ASOF")
    sources = [s for s in manifest.get("sources", []) if s.get("kind") == "TWSE_income"]
    if len(sources) != 1:
        raise ContractError("UNIQUE_TWSE_GENERAL_INCOME_SOURCE_REQUIRED")
    source = sources[0]
    relative = source.get("path")
    if (not isinstance(relative, str) or not relative.startswith("tw-market-data/financial/")
            or not relative.endswith(".json") or ".." in Path(relative).parts):
        raise ContractError("UNSAFE_FINANCIAL_SNAPSHOT_PATH")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ContractError("FINANCIAL_SOURCE_ESCAPES_ROOT")
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != source.get("normalized_sha256"):
        raise ContractError("NORMALIZED_FINANCIAL_BYTES_HASH_MISMATCH")
    if source.get("url") != "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci":
        raise ContractError("UNEXPECTED_INCOME_SOURCE_URL")
    rows = json.loads(raw)
    if not isinstance(rows, list) or len(rows) != source.get("issuer_rows"):
        raise ContractError("FINANCIAL_ROW_COUNT_MISMATCH")
    results = []
    for code in codes:
        matches = [r for r in rows if isinstance(r, dict) and r.get("公司代號") == code]
        if len(matches) != 1:
            results.append({"code": code, "status": "ISSUER_NOT_IN_SNAPSHOT" if not matches else "DUPLICATE_ISSUER_ROWS", "buy_signal": False})
            continue
        try:
            result = reconcile_income(matches[0], units=units)
            if result["fiscal_period"] != source.get("period"):
                raise ContractError("ISSUER_FISCAL_PERIOD_MISMATCH")
            batch = str(matches[0].get("出表日期", ""))
            if not re.fullmatch(r"\d{7}", batch):
                raise ContractError("INVALID_SOURCE_BATCH_DATE")
            batch_date = datetime(int(batch[:3]) + 1911, int(batch[3:5]), int(batch[5:7])).date()
            # An ROC batch date is a Taipei calendar day, not a publication timestamp.
            from datetime import timedelta
            if batch_date > captured.astimezone(timezone(timedelta(hours=8))).date():
                raise ContractError("BATCH_DATE_AFTER_CAPTURE_TAIPEI_DAY")
            results.append(result)
        except (ContractError, ValueError, TypeError) as exc:
            results.append({"code": code, "status": "INVALID_REPORTED_FACTS", "reason": str(exc), "buy_signal": False})
    count = sum(r["status"] == "RECONCILED_REPORTED_FACTS_ONLY" for r in results)
    return {
        "status": "RESEARCH_REPORTED_FACTS_ONLY" if count == len(codes) else "RESEARCH_REPORTED_FACTS_PARTIAL",
        "asof": asof.isoformat(), "source_commit": source_commit,
        "source_capture_declared_at": captured.isoformat(), "source_period": source.get("period"),
        "manifest_sha256": sha256(manifest_bytes).hexdigest(), "normalized_file_sha256": digest,
        "source_url": source["url"], "source_path": relative, "source_row_count": len(rows),
        "declared_units": units, "source_original_bytes_authenticated": False,
        "issuer_publication_timestamps_verified": False,
        "requested_count": len(codes), "reconciled_count": count, "issuers": results,
        "source": {"commit": source_commit, "declared_capture_at": captured.isoformat(),
                   "manifest_sha256": sha256(manifest_bytes).hexdigest(),
                   "normalized_path": relative, "normalized_sha256": digest,
                   "declared_original_url": source.get("url"),
                   "declared_original_sha256": source.get("sha256_original"),
                   "original_bytes_independently_verified": False, "declared_units": dict(units)},
        "buy_signal": False, "investment_certified": False, "expected_net_return_12m": None,
        "note": "Normalized-byte checks and arithmetic do not authenticate originals, issuer filing clocks, diluted shares, forward assumptions or investment eligibility. Focus-company coverage is not whole-market coverage.",
    }
