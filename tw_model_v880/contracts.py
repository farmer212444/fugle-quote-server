"""Issuer economic contracts and explicit, scoped review obligations."""
import hashlib
import json
import math
from pathlib import Path

from .evidence import GATES

FORECAST_CONTRACT = "V810_ECONOMIC_INPUTS_V1"
ECONOMIC_MODULES = ("model.py", "data.py", "math.py", "calibration.py", "capital.py",
                    "specialists.py", "margin_recovery.py", "events.py", "peers.py", "contracts.py")
OBLIGATIONS = {
    "original_eight_quarter_statements": ("ISSUER", "逐季原始四表、附註、重編及完整性核對", "財報／重編更新"),
    "cash_and_working_capital": ("ISSUER", "應收、存貨、應付、CAPEX與資金來源橋接", "新財報／資金事件"),
    "nonoperating_components": ("ISSUER", "經常性、匯兌、處分、評價與減損分解", "業外組成更新"),
    "fully_diluted_shares": ("ISSUER", "現有股數、CB最新條款、員工股份與分母勾稽", "增減資／CB條款更新"),
    "matched_peers_and_cycle": ("ISSUER", "商業模式相符同業、循環位置與倍數依據", "營運模式／循環假設改變"),
    "management_promises": ("ISSUER", "原始承諾、可驗證指標、時程與後續交付紀錄", "新承諾／驗證到期"),
    "auditor_scope": ("ISSUER", "完整核閱意見、保留範圍及重要性判斷", "新核閱／重大事項"),
    "tradability": ("EXECUTION", "多日成交、價差、參與率與清倉能力", "股價／成交條件改變"),
    "forecast_bridge": ("ISSUER", "量價、產能、稼動、成本、折舊及2027EPS推導", "經濟輸入／預測方法改變"),
    "insider_claims": ("ISSUER", "原始申報、身份、實際增減與公告可得時間", "新申報／說法變更"),
    "dividend_window": ("CORPORATE_ACTION", "除權息、支付、股數與估值適用期間", "公司行動公告／修正"),
    "point_in_time": ("SOURCE", "原始公告、修訂與首次可得時間", "來源修訂／可得時間更正"),
    "out_of_sample_validation": ("STRATEGY", "固定策略版本與適用子群的扣成本樣本外驗證", "策略／母體／交易規則改變"),
}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def economic_method_hash():
    folder = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in ECONOMIC_MODULES:
        h.update(name.encode() + b"\0" + (folder / name).read_bytes() + b"\0")
    pins=folder.parent/'requirements-model.txt'
    if pins.exists():h.update(b'requirements-model.txt\0'+pins.read_bytes()+b'\0')
    return h.hexdigest()


def forecast_binding(code, period, target_date, cases, event=None):
    # Prices/upside are recalculated daily; the issuer operating contract is
    # invalidated by economic inputs/method changes, not an unrelated quote date.
    keys = ("revenue_k", "gross_margin", "opex_ratio", "nonoperating_k", "tax_rate",
            "parent_fraction", "shares", "eps", "pe", "target_price", "valuation_method")
    inputs = dict(code=code, financial_period=period, target_date=target_date,
                  event_sha256=(event or {}).get("event_sha256"),
                  cases={name: {k: case.get(k) for k in keys} for name, case in cases.items()})
    return dict(forecast_contract_version=FORECAST_CONTRACT,
                forecast_input_sha256=canonical_hash(inputs),
                forecast_method_sha256=economic_method_hash(), target_date=target_date,
                invalidates_on="ECONOMIC_INPUT_OR_METHOD_CHANGE_NOT_REFERENCE_PRICE_DATE")


def matches_forecast(cert, binding, runtime_sha, price_date, target_date):
    if cert.get("forecast_contract_version") == FORECAST_CONTRACT:
        return all(cert.get(k) == binding[k] for k in
                   ("forecast_contract_version", "forecast_input_sha256", "forecast_method_sha256", "target_date"))
    # Existing certificates keep their original, stricter contract.
    return all(cert.get(k) == value for k, value in
               (("model_code_sha256", runtime_sha), ("reference_price_date", price_date), ("target_date", target_date)))


def review_work(row):
    """Thirteen specific obligations with source/issuer/strategy scopes.

    This records actual model decisions; it is not a substitute formal signer.
    Partial factual checks never become a whole-gate PASS.
    """
    result = []
    certification = row.get("certification", {})
    for name in GATES:
        scope, required, expiry = OBLIGATIONS[name]
        if name in certification.get("gates_passed", []):
            state = "PASS"
        elif name in certification.get("gates_failed", []):
            state = "FAIL"
        else:
            state = "PENDING"
        result.append(dict(gate=name, scope=scope, decision=state,
                           reason=row.get("gates", {}).get(name, {}).get("reason", "SOURCE_OR_REVIEW_MISSING"),
                           required_evidence=required, invalidates_on=expiry,
                           strategy_evidence_reusable_by_version=scope == "STRATEGY",
                           formal_pass=state == "PASS"))
    return result


def valuation_diagnostics(row):
    b = row.get("base") or {}
    price, pe = row.get("reference_close"), b.get("pe")
    required = ("revenue_k", "opex_ratio", "nonoperating_k", "tax_rate", "parent_fraction", "shares", "eps")
    if not all(isinstance(b.get(k), (int, float)) and not isinstance(b[k], bool) and math.isfinite(b[k]) for k in required):
        return dict(status="OPERATING_INPUTS_INCOMPLETE")
    if not price or not pe or min(b["revenue_k"], b["shares"], b["parent_fraction"], 1-b["tax_rate"]) <= 0:
        return dict(status="REVERSE_PE_VALUATION_NOT_APPLICABLE")
    def implied_margin(target):
        eps = target / pe
        pretax = eps*b["shares"]/1000 / ((1-b["tax_rate"])*b["parent_fraction"])
        return b["opex_ratio"] + (pretax-b["nonoperating_k"]) / b["revenue_k"]
    bear_price = (row.get("bear") or {}).get("target_price")
    return dict(status="RESEARCH_ASSUMPTION_SENSITIVITY_NOT_A_PROBABILITY",
                market_implied_eps_at_model_pe=price/pe,
                market_implied_gross_margin=implied_margin(price),
                gross_margin_required_for_30pct_upside=implied_margin(price*1.30),
                eps_gain_per_1pp_gross_margin=b["revenue_k"]*.01*(1-b["tax_rate"])*b["parent_fraction"]*1000/b["shares"],
                eps_pe_each_minus20_upside_pct=(b.get("target_price", 0)*.64/price-1)*100,
                bear_price_upside_pct=(bear_price/price-1)*100 if bear_price is not None else None,
                pe_is_matched_peer_certified=row.get("pe_bridge", {}).get("exact_matched_peer_review_complete", False),
                forward_annual_profit_bridge_verified=row.get("company_forecast_confirmed", False))
