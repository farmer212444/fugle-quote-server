"""Evidence-first Munger inversion audit; never a trade or an A+ certifier.

Consumes already-published institutional and 13-gate reports. It cannot
alter projected EPS, PE, base rankings, strategy parameters or certificates.
"""
from __future__ import annotations

import math

GATES = (
    "original_eight_quarter_statements", "cash_and_working_capital",
    "nonoperating_components", "fully_diluted_shares", "matched_peers_and_cycle",
    "management_promises", "auditor_scope", "tradability", "forecast_bridge",
    "insider_claims", "dividend_window", "point_in_time",
    "out_of_sample_validation",
)
GATE_SET = frozenset(GATES)

# Research questions, NOT conclusions that something has already gone wrong.
INVERSION = (
    ("forecast_bridge", "What original orders, volume, mix and costs would DISPROVE 2027 Base EPS?"),
    ("matched_peers_and_cycle", "Would a normalized cycle and matched peers DISPROVE the assumed PE?"),
    ("cash_and_working_capital", "Could inventory and receivables fail to convert into cash?"),
    ("fully_diluted_shares", "Could announced or contingent new shares dilute EPS?"),
    ("management_promises", "Which dated management promises were not delivered?"),
    ("auditor_scope", "What audit qualifications or unreviewed subsidiaries could change earnings?"),
    ("point_in_time", "Would the claimed signal disappear using only information then available?"),
    ("out_of_sample_validation", "Does net performance fail against the benchmark after costs?"),
    ("tradability", "Could this position be exited at the stated size under stress?"),
)


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("MUNGER_INVALID_NUMBER_" + field.upper())
    return float(value)


def _identity(row):
    code, market = row.get("code"), row.get("market")
    if not isinstance(code, str) or not code or not isinstance(market, str) or not market:
        raise ValueError("MUNGER_MISSING_ISSUER_IDENTITY")
    return market, code


def _gate_snapshot(diag):
    passed = diag.get("formally_passed_gates")
    failed = diag.get("formally_failed_gates")
    pending = diag.get("still_pending_gates")
    if not all(isinstance(v, list) for v in (passed, failed, pending)):
        raise ValueError("MUNGER_MISSING_THIRTEEN_GATE_DECISIONS")
    all_gates = passed + failed + pending
    if len(all_gates) != len(GATES) or frozenset(all_gates) != GATE_SET:
        raise ValueError("MUNGER_INCOMPLETE_OR_DUPLICATED_THIRTEEN_GATES")
    stages = diag.get("gate_stage")
    if not isinstance(stages, dict) or frozenset(stages) != GATE_SET:
        raise ValueError("MUNGER_GATE_STAGE_INCOMPLETE")
    for gate in GATES:
        record = stages[gate]
        expected = "PASS" if gate in passed else "FAIL" if gate in failed else "PENDING"
        if not isinstance(record, dict) or record.get("decision") != expected or record.get("formal_pass") is not (expected == "PASS"):
            raise ValueError("MUNGER_GATE_DECISION_MISMATCH_" + gate)
    return passed, failed, pending


def build(progress, institutional):
    """Pure review: failure to verify is PENDING, not an invented FAIL."""
    if progress.get("model") != institutional.get("model") or not progress.get("model"):
        raise ValueError("MUNGER_MODEL_VINTAGE_MISMATCH")
    for key in ("estimate_vintage", "asof_price_date"):
        if not progress.get(key) or progress.get(key) != institutional.get(key):
            raise ValueError("MUNGER_" + key.upper() + "_MISMATCH")
    if progress.get("formally_certified_Aplus_in_report") != institutional.get("formal_Aplus_count"):
        raise ValueError("MUNGER_CERTIFIED_COUNT_MISMATCH")
    if progress.get("decisions_from_hashed_effective_model_gates") is not True:
        raise ValueError("MUNGER_EFFECTIVE_MODEL_GATE_PROVENANCE_MISSING")
    focus = {}
    for review in institutional.get("issuer_reviews", []):
        key = _identity(review)
        if key in focus:
            raise ValueError("MUNGER_DUPLICATE_INSTITUTIONAL_ISSUER")
        focus[key] = review
    results = []
    seen = set()
    for diag in progress.get("issuer_diagnostics", []):
        key = _identity(diag)
        if key in seen:
            raise ValueError("MUNGER_DUPLICATE_GATE_ISSUER")
        seen.add(key)
        passed, failed, pending = _gate_snapshot(diag)
        special = focus.get(key)
        declared_plus = diag.get("formal_Aplus") is True
        if declared_plus and (len(passed) != len(GATES) or bool(failed or pending)):
            raise ValueError("MUNGER_UNSUPPORTED_FORMAL_A_PLUS")
        if special and bool(special.get("formal_Aplus")) != declared_plus:
            raise ValueError("MUNGER_INSTITUTIONAL_GATE_CERTIFICATION_MISMATCH")
        governance = (special or {}).get("governance_review") or {}
        blocked = bool((special or {}).get("recommendation_blocked") or governance.get("blocks_recommendation"))
        if blocked and declared_plus:
            raise ValueError("MUNGER_GOVERNANCE_BLOCKED_CERTIFICATION_CONFLICT")
        upside = diag.get("research_upside_pct")
        if upside is not None:
            upside = _number(upside, "upside")
        stress = None
        if special:
            stress = (special.get("valuation_diagnostics") or {}).get("eps_pe_each_minus20_upside_pct")
            if stress is not None:
                stress = _number(stress, "dual_stress")
        flags = []
        if blocked:
            flags.append("MATERIAL_GOVERNANCE_REVIEW_BLOCK")
        if stress is not None and stress < 0:
            flags.append("EPS_AND_PE_MINUS20_IMPLIES_NEGATIVE_PRICE_UPSIDE")
        if special and not (special.get("liquidity") or {}).get("spread_and_exit_verified"):
            flags.append("MULTI_SESSION_EXECUTION_NOT_CERTIFIED")
        if special and (special.get("risk_profile") or {}).get("status") != "REVIEWED_PROFILE_WITH_MATCHING_ORIGINAL_HASHES":
            flags.append("COMMON_RISK_AND_STRESS_PROFILE_MISSING")
        if special and (special.get("valuation_diagnostics") or {}).get("pe_is_matched_peer_certified") is not True:
            flags.append("MATCHED_PE_NOT_CERTIFIED")
        if special and (special.get("valuation_diagnostics") or {}).get("forward_annual_profit_bridge_verified") is not True:
            flags.append("ANNUAL_EPS_BRIDGE_NOT_CERTIFIED")
        pending_set = frozenset(pending)
        checks = [
            dict(gate=gate, question=question,
                 required_evidence=diag["gate_stage"][gate].get("required_evidence"),
                 model_gate_decision=diag["gate_stage"][gate]["decision"])
            for gate, question in INVERSION if gate in pending_set or gate in failed
        ][:3]
        status = ("GOVERNANCE_REVIEW_BLOCK" if blocked else
                  "FORMAL_GATE_FAILURE" if failed else
                  "SOURCE_REPORTED_A_PLUS" if declared_plus else
                  "HIGH_UPSIDE_RESEARCH_ONLY_UNCERTIFIED" if upside is not None and upside >= 30 else
                  "RESEARCH_ONLY_UNCERTIFIED")
        results.append(dict(code=key[1], market=key[0], name=diag.get("name"),
                            research_base_upside_pct=upside,
                            dual_minus20_upside_pct=stress,
                            status=status, formal_Aplus_already_reported=declared_plus,
                            reviewed_institutional_detail=bool(special),
                            passed_gate_count=len(passed), failed_gates=failed,
                            pending_gates=pending, evidence_to_disprove_thesis=checks,
                            research_red_flags=flags,
                            **{"new_certification_issued": False, "trade_signal": False}))
    if not results:
        raise ValueError("MUNGER_NO_ISSUER_GATE_DIAGNOSTICS")
    if not set(focus).issubset(seen):
        raise ValueError("MUNGER_FOCUS_ISSUER_NOT_IN_GATE_REPORT")
    expected = progress.get("model_evaluated_issuer_count")
    if expected != len(results):
        raise ValueError("MUNGER_EVALUATED_ISSUER_COUNT_MISMATCH")
    return dict(schema="V811_MUNGER_INVERSION_RESEARCH_ONLY_V1",
                model=progress["model"], estimate_vintage=progress["estimate_vintage"],
                asof_price_date=progress["asof_price_date"],
                total_tracked=progress.get("tracked_issuer_count"),
                evaluated_issuers=len(results),
                not_evaluated_issuers=progress.get("not_evaluated_issuer_count"),
                reported_formal_Aplus=progress["formally_certified_Aplus_in_report"],
                high_upside_uncertified=sum(x["status"] == "HIGH_UPSIDE_RESEARCH_ONLY_UNCERTIFIED" for x in results),
                institutional_detail_coverage=len(focus),
                reviewed_issuers=results,
                original_valuation_unchanged=True,
                official_13_gates_unchanged=True,
                scenario_probabilities_added=False,
                new_certificates_issued=0, trade_orders_created=0,
                comparative_outperformance_not_established=True)


def render(report):
    """Focused due-diligence queue; never a stock recommendation ranking."""
    candidates = [r for r in report["reviewed_issuers"] if r["reviewed_institutional_detail"]]
    # Known blocking downside concerns first, rather than largest claimed upside.
    candidates.sort(key=lambda r: (
        0 if r["status"] == "GOVERNANCE_REVIEW_BLOCK" else 1,
        0 if "EPS_AND_PE_MINUS20_IMPLIES_NEGATIVE_PRICE_UPSIDE" in r["research_red_flags"] else 1,
        -len(r["research_red_flags"]),
        -(r["research_base_upside_pct"] or 0), r["code"]))
    def safe(value):
        return str(value).replace("|", "/").replace("\n", " ").replace("\r", " ")
    def pct(n):
        return "待驗" if n is None else f"{n:+.1f}%"
    lines = [
        "# 蒙格式反向驗證｜研究待辦（非買進名單）", "",
        f"模型 {safe(report['model'])}；估計 {safe(report['estimate_vintage'])}；價格日 {safe(report['asof_price_date'])}。", "",
        f"追蹤 {report['total_tracked']}、已評估 {report['evaluated_issuers']}、未進入判定 {report['not_evaluated_issuers']}；原有正式A+ {report['reported_formal_Aplus']}。", "",
        "**這不是新選股評分、勝率或重押推薦。沒有任何新認證；原EPS、PE、Base價差、A+門檻與部位均未改動。**", "",
        "## 深度覆核優先：先處理已識別的反證與下檔脆弱性", "",
        "|股票|Base價差|EPS/PE各-20%價差|既有正式PASS|狀態|已識別查核風險|",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in candidates[:30]:
        lines.append("|{code} {name}|{base}|{stress}|{passed}/13|{status}|{flags}|".format(
            code=safe(r["code"]), name=safe(r["name"] or ""),
            base=pct(r["research_base_upside_pct"]), stress=pct(r["dual_minus20_upside_pct"]),
            passed=r["passed_gate_count"], status=safe(r["status"]),
            flags=safe(", ".join(r["research_red_flags"][:3]) or "未發現已覆核訊號（不代表安全）")))
    lines.extend(["", "## 三項優先反向驗證問題（按既有13項缺口）", ""])
    for r in candidates[:12]:
        lines.append(f"### {safe(r['code'])} {safe(r['name'] or '')}")
        for check in r["evidence_to_disprove_thesis"]:
            lines.append(f"- {safe(check['gate'])}：{safe(check['question'])}；待核：{safe(check['required_evidence'] or '原始資料')}。")
    lines += ["", "## 使用邊界", "",
              "- 只從已發行的13項正式判定與機構研究讀取，不能自行把待驗改成通過或不通過。",
              "- 高漲幅是條件式價格差，不是經校準的未來報酬機率。",
              "- 尚未完整覆蓋的治理事件不能視為不存在；能力圈也需要獨立的人類研究確認。",
              "- 需要真正完成扣成本的樣本外結果，才可能推論模型對0050的優勢。",
              "- 本報告只列被既有機構研究挑選的深度覆核股票；不代表全市場盡職調查完成。", ""]
    return "\n".join(lines)
