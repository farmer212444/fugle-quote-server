"""Hypothetical justified P/B sensitivity from forward ROE, not an A+ trade signal.

Under constant long-term ROE, terminal growth and clean-surplus/payout
conditions: justified P/B = (sustainable ROE - g)/(cost of equity - g).
2027 *one-year* EPS divided by 2026Q2 BVPS is NOT validated sustainable
ROE. Prices multiply CURRENT book, not measured 2027 future book.
"""
from __future__ import annotations
import json,math
from pathlib import Path

ROOT=Path("tw-market-data/research/footwear_pb_2016_2026")
FILE=ROOT/"2027_roe_pb_hypotheses.json"
OUT=ROOT/"2027_justified_pb_shadow.json"


def finite(value,label):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("INVALID_NUMERIC_"+label)
    return float(value)


def calculate(data):
    if (data.get("schema")!="V8107_FOOTWEAR_2027_ROE_JUSTIFIED_PB_HYPOTHESIS_V1"
        or data.get("compiled_asof")!="2026-10-24"
        or data.get("price_asof")!="2026-10-22"
        or data.get("bvps_asof_quarter")!="2026Q2"
        or data.get("book_value_not_2027_estimate") is not True
        or data.get("formal_Aplus_or_stock_order_changed") is not False
        or data.get("payout_and_book_value_in_2027_verified") is not False):
        raise ValueError("PIT_OR_FORMAL_ROE_FORECAST_CLAIM_MISSTATED")
    g=finite(data["g_forever_annual"],"terminal_growth")
    if not 0<=g<=.04: raise ValueError("INVALID_TERMINAL_GROWTH")
    output={}
    for item in data.get("stock_input",[]):
        code=item["code"]
        if code in output or code not in ("9904","6768","6965","9802","9910"):
            raise ValueError("DUPLICATE_OR_UNEXPECTED_FOOTWEAR_CODE")
        bv=finite(item["bvps"],"bvps")
        price=finite(item["price"],"price")
        eps=finite(item["base_2027_eps_hypothesis"],"eps")
        k=finite(item["cost_of_equity"],"equity_cost")
        exchange_pb=finite(item["official_2026_10_22_pb"],"twse_pb")
        if bv<=0 or price<=0 or not 0<=eps<40 or not .06<=k<=.25 or k<=g+.025:
            raise ValueError("EPS_BOOK_OR_KE_SANITY_CHECK")
        if abs(price/bv-exchange_pb)>.025:
            raise ValueError("REFERENCE_PB_NOT_CONSISTENT_WITH_BVPS_AND_CLOSE")
        if item["base_eps_PIT_verified"] is not False:
            raise ValueError("UNVERIFIED_2027_FORECAST_CANNOT_BE_CALLED_CERTIFIED")
        roi=eps/bv
        if roi<=g:
            fair_pb=None
            proxy_price=None
        else:
            fair_pb=(roi-g)/(k-g)
            proxy_price=fair_pb*bv
        # A market P/B implies sustainable franchise ROE only if the long-
        # term Gordon payout, clean-surplus and Ke assumptions are true.
        implied_roe=exchange_pb*(k-g)+g
        worst_k=k+.02
        best_k=max(g+.025,k-.02)
        downside_pb=(roi-g)/(worst_k-g) if roi>g else None
        upside_pb=(roi-g)/(best_k-g) if roi>g else None
        output[code]={
           "name":item["name"],
           "stock_price_close_2026_10_22":price,
           "BVPS_quarter_2026_Q2":bv,
           "official_TWSE_2026_10_22_PB":exchange_pb,
           "2027_subjective_base_EPS":eps,
           "EPS_estimate_origin":item["base_eps_origin"],
           "2027_EPS_over_2026Q2_BVPS_proxy_roe_pct":round(roi*100,2),
           "long_run_equity_cost_pct":round(k*100,2),
           "long_run_terminal_equity_growth_assumed_pct":round(g*100,2),
           "current_PB_implied_permanent_roe_pct":round(implied_roe*100,2),
           "justified_PB_if_2027_roe_persisted_indefinitely":round(fair_pb,3) if fair_pb else None,
           "illustrative_price_using_2026Q2_book_not_2027_future_book":round(proxy_price,2) if proxy_price else None,
           "PB_when_equity_cost_plus_2pp":round(downside_pb,3) if downside_pb else None,
           "PB_when_equity_cost_minus_2pp":round(upside_pb,3) if upside_pb else None,
           "2027_book_and_true_sustainable_ROE_independently_verified":False,
           "is_a_certified_2027_price_target":False,
           "formal_Aplus":False,
           "risk_note":item["remarks"]
        }
    if set(output)!={"9904","6768","6965","9802","9910"}:
        raise ValueError("FIVE_STOCK_UNIVERSE_INCOMPLETE")
    return {
      "schema":"V8107_FOOTWEAR_JUSTIFIED_PB_LONGRUN_EQUILIBRIUM_SHADOW",
      "model_vintage":"2026-10-24",
      "source_bvps_date":"2026Q2",
      "reference_close_date":"2026-10-22",
      "not_cash_dividend_discount_without_sustainable_payout_assumption":True,
      "not_true_2027_price_target_or_purchase_instruction":True,
      "not_2027_reported_ROE":True,
      "no_formal_Aplus":True,
      "verified_2027_total_return_against_0050":None,
      "issuer_2027_PB_research":output
    }


def main():
    data=json.loads(FILE.read_bytes())
    out=calculate(data)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        c:{"roe_proxy":v["2027_EPS_over_2026Q2_BVPS_proxy_roe_pct"],
           "implied_roe":v["current_PB_implied_permanent_roe_pct"],
           "PB_justified_if_perpetual":v["justified_PB_if_2027_roe_persisted_indefinitely"]}
        for c,v in out["issuer_2027_PB_research"].items()},ensure_ascii=False))


if __name__=="__main__":
    main()
