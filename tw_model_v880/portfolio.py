"""Configurable long-only risk-budget research. Never creates trade orders."""
import math


def finite(value, *, positive=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (not positive or value > 0))


def validate_policy(policy):
    for name in ("max_stock_weight", "max_sector_weight", "max_common_risk_weight",
                 "max_portfolio_bear_loss", "max_daily_participation"):
        if not finite(policy.get(name), positive=True) or policy[name] > 1:
            raise ValueError("INVALID_RISK_POLICY_" + name)
    if not finite(policy.get("max_exit_sessions"), positive=True):
        raise ValueError("INVALID_EXIT_SESSION_LIMIT")
    return policy


def constrained_portfolio(candidates, capital_ntd, policy):
    """Greedy feasible research allocation in supplied, precommitted order.

    Bear scenarios are stress assumptions, not guaranteed maximum losses.
    A missing or positive Bear does not supply a zero-loss risk estimate.
    Only formally eligible, execution-reviewed candidates can receive weight.
    """
    validate_policy(policy)
    if not finite(capital_ntd, positive=True):
        raise ValueError("REFERENCE_CAPITAL_REQUIRED")
    if len({(c.get("market"), c.get("code")) for c in candidates}) != len(candidates):
        raise ValueError("DUPLICATE_PORTFOLIO_ISSUER")
    sectors, common = {}, {}
    positions, rejected = [], []
    invested = loss_budget_used = 0.0
    for row in candidates:
        code, sector = row.get("code"), row.get("industry")
        failures = []
        if row.get("formal_Aplus") is not True:
            failures.append("FORMAL_QUALITY_NOT_COMPLETE")
        execution = row.get("execution_review") or {}
        if execution.get("spread_and_exit_verified") is not True:
            failures.append("EXECUTION_REVIEW_MISSING")
        adv = execution.get("median20_turnover_ntd")
        if not finite(adv, positive=True):
            failures.append("MEDIAN20_TURNOVER_MISSING")
        if not sector:
            failures.append("SECTOR_EXPOSURE_UNKNOWN")
        tags = row.get("common_risk_tags")
        if not isinstance(tags, list) or not tags or any(not isinstance(t,str) or not t for t in tags):
            failures.append("COMMON_RISK_EXPOSURES_UNREVIEWED")
        loss = row.get("reviewed_stress_loss_fraction")
        if not finite(loss, positive=True) or loss > 1:
            failures.append("POSITIVE_REVIEWED_STRESS_LOSS_REQUIRED")
        if failures:
            rejected.append(dict(code=code, reasons=failures))
            continue
        capacity = adv*policy["max_daily_participation"]*policy["max_exit_sessions"] / capital_ntd
        remaining_loss = max(0, policy["max_portfolio_bear_loss"]-loss_budget_used)
        limits = [policy["max_stock_weight"], max(0, 1-invested), capacity,
                  max(0, policy["max_sector_weight"]-sectors.get(sector, 0)), remaining_loss/loss]
        limits.extend(max(0, policy["max_common_risk_weight"]-common.get(tag, 0)) for tag in set(tags))
        weight = min(limits)
        if weight <= 1e-12:
            rejected.append(dict(code=code, reasons=["PORTFOLIO_OR_EXIT_CAPACITY_EXHAUSTED"]))
            continue
        positions.append(dict(code=code, market=row.get("market"), weight=weight,
                              value_ntd=capital_ntd*weight, scenario_loss_contribution=weight*loss,
                              required_exit_sessions=capital_ntd*weight/(adv*policy["max_daily_participation"])))
        invested += weight
        loss_budget_used += weight*loss
        sectors[sector] = sectors.get(sector,0)+weight
        for tag in set(tags):
            common[tag] = common.get(tag,0)+weight
    return dict(positions=positions, excluded=rejected, cash_weight=max(0,1-invested),
                scenario_bear_loss=loss_budget_used, sector_weights=sectors,
                common_risk_weights=common, reference_capital_ntd=capital_ntd,
                policy_is_illustrative_research=True, actual_holdings_not_assumed=True,
                stress_scenario_is_not_a_loss_guarantee=True, trade_orders_created=0)


def reverse_execution_capacity(median_turnover, capital, participation=.05, sessions=5):
    if not finite(median_turnover, positive=True) or not finite(capital, positive=True):
        return None
    if not finite(participation, positive=True) or participation > 1 or not finite(sessions, positive=True):
        raise ValueError("INVALID_CAPACITY_POLICY")
    return min(1.0, median_turnover*participation*sessions/capital)
