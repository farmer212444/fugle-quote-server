"""Read the issuer's rounded 2026 Q3 condensed statements, not full notes.

Column counts, currencies, periods and accounting identities are checked before
the event can update a research estimate. Amounts in millions become NTD
thousands; the rounding allowance does not apply to other issuer adapters.
"""
import math
import re

RECIPE = '2330_2026Q3_CONDENSED_STATEMENTS_V1'
SOURCE_KIND = 'ISSUER_CONDENSED_FINANCIAL_STATEMENTS_UNAUDITED'
ISSUER = 'TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED AND SUBSIDIARIES'
FIELDS = {
    'revenue_k': 'Net Revenue',
    'cost_of_revenue_k': 'Cost of Revenue',
    'gross_profit_k': 'Gross Profit',
    'opex_k': 'Total Operating Expenses',
    'other_operating_k': 'Other Operating Income and Expenses',
    'operating_profit_k': 'Income from Operations',
    'associates_k': 'Share of Profits of Associates',
    'net_interest_k': 'Net Interest Income (Expenses)',
    'other_gains_k': 'Other Gains and Losses',
    'nonoperating_k': 'Total Non-operating Income and Expenses',
    'pretax_profit_k': 'Income before Income Tax',
    'tax_signed_k': 'Income Tax Expenses',
    'net_income_k': 'Net Income',
    'parent_net_income_k': 'Shareholders of the Parent',
}


def values(text, label, count):
    """A complete labelled row; never infer a missing NTD column from USD."""
    matches = list(re.finditer(r'^' + re.escape(label) + r'[ \t]*$', text,
                               re.MULTILINE | re.IGNORECASE))
    if len(matches) != 1:
        raise ValueError('TSMC_TABLE_LABEL_' + label)
    tail = text[matches[0].end():]
    end = re.search(r'^(?!NM[ \t]*$)[A-Za-z]', tail, re.MULTILINE)
    body = tail[:end.start()] if end else tail
    tokens = body.replace('$', '').split()
    if len(tokens) != count:
        raise ValueError('TSMC_TABLE_COLUMN_COUNT_' + label)
    result = []
    for token in tokens:
        if token in ('-', 'NM'):
            result.append(None)
        elif re.fullmatch(r'\(?-?[\d,]+(?:\.\d+)?\)?', token):
            value = float(token.replace(',', '').replace('(', '-').replace(')', ''))
            if not math.isfinite(value):
                raise ValueError('TSMC_NONFINITE_TABLE_NUMBER')
            result.append(value)
        else:
            raise ValueError('TSMC_TABLE_NUMBER_' + label)
    return result


def income(text, count, columns):
    rows = {key: values(text, label, count) for key, label in FIELDS.items()}
    cases = []
    for column in columns:
        facts = {key: row[column] * 1000 if row[column] is not None else None
                 for key, row in rows.items()}
        if any(value is None for value in facts.values()) or facts['revenue_k'] <= 0:
            raise ValueError('TSMC_REQUIRED_INCOME_FACT_MISSING')
        checks = (
            facts['revenue_k'] + facts['cost_of_revenue_k'] - facts['gross_profit_k'],
            facts['gross_profit_k'] + facts['opex_k'] + facts['other_operating_k'] - facts['operating_profit_k'],
            facts['associates_k'] + facts['net_interest_k'] + facts['other_gains_k'] - facts['nonoperating_k'],
            facts['operating_profit_k'] + facts['nonoperating_k'] - facts['pretax_profit_k'],
            facts['pretax_profit_k'] + facts['tax_signed_k'] - facts['net_income_k'],
        )
        if any(abs(error) > 2000 for error in checks):
            raise ValueError('TSMC_INCOME_RECONCILIATION')
        # Keep positive expense magnitude, with other operating gains separate.
        facts['opex_k'] *= -1
        cases.append(facts)
    return cases


def parse_tsmc(pages):
    if len(pages) != 4:
        raise ValueError('TSMC_PAGE_COUNT_CHANGED')
    for page in pages:
        if ISSUER not in page or not all(s in page for s in ('Millions of New Taiwan Dollars', '"NTD"', '"USD"', 'Unaudited')):
            raise ValueError('TSMC_ISSUER_UNIT_OR_SCOPE_MISMATCH')
    headers = (
        ('September 30, 2026', 'June 30, 2026', 'September 30, 2025'),
        ('For the Three Months Ended September 30, 2026, June 30, 2026 and September 30, 2025', '3Q 2026\n2Q 2026\n3Q 2025\nQoQ\nYoY'),
        ('For the Nine Months Ended September 30\n2026\n2025\nYoY',),
        ('Nine Months 2026\n3Q 2026\n2Q 2026\n3Q 2025',),
    )
    for page, required in zip(pages, headers):
        if not all(s in page for s in required):
            raise ValueError('TSMC_PERIOD_OR_COLUMN_ORDER_MISMATCH')
    for index, count in ((1, 5), (2, 3)):
        _, separator, tail = pages[index].partition('YoY\n')
        if not separator or 'Net Revenue' not in tail:
            raise ValueError('TSMC_CURRENCY_COLUMN_ORDER_MISMATCH')
        currency_header = tail.split('Net Revenue', 1)[0].split()
        if currency_header != ['USD'] + ['NTD', '%'] * count:
            raise ValueError('TSMC_CURRENCY_COLUMN_ORDER_MISMATCH')
    _, separator, tail = pages[3].partition('3Q 2025\n')
    if not separator or 'Cash Flows from Operating Activities:' not in tail:
        raise ValueError('TSMC_CURRENCY_COLUMN_ORDER_MISMATCH')
    cash_header = tail.split('Cash Flows from Operating Activities:', 1)[0].split()
    if cash_header != ['USD', 'NTD', 'NTD', 'NTD', 'NTD']:
        raise ValueError('TSMC_CURRENCY_COLUMN_ORDER_MISMATCH')
    single, previous_q2, prior_single = income(pages[1], 11, (1, 3, 5))
    current, prior = income(pages[2], 7, (1, 3))
    shares = values(pages[2], "Weighted Average Outstanding Shares - Diluted ('M)", 2)[0] * 1_000_000
    current['diluted_eps'] = values(pages[2], 'Earnings per Share - Diluted', 5)[1]
    if shares <= 0 or abs(current['parent_net_income_k'] * 1000 / shares - current['diluted_eps']) > .006:
        raise ValueError('TSMC_DILUTED_EPS_RECONCILIATION')
    cash_rows = {'ocf_k': values(pages[3], 'Net Cash Generated by Operating Activities', 5)}
    # This label occurs twice (acquisitions and disposals); constrain the table.
    cash_rows['ppe_cash_flow_signed_k'] = values(
        pages[3].split('Proceeds from Disposal or Redemption of:')[0],
        'Property, Plant and Equipment', 5)
    cash = {key: row[1] * 1000 for key, row in cash_rows.items()}
    cash['cash_k'] = values(pages[0], 'Cash and Cash Equivalents', 11)[1] * 1000
    cash['single_quarter_ocf_k'] = cash_rows['ocf_k'][2] * 1000
    cash['previous_ytd_ocf_k'] = cash['ocf_k'] - cash['single_quarter_ocf_k']
    cash['equipment_prepaid_signed_k'] = None
    if cash['ppe_cash_flow_signed_k'] > 0:
        raise ValueError('TSMC_PPE_CASHFLOW_SIGN_MISMATCH')
    return dict(current=current, prior=prior, single_quarter=single,
                previous_single_quarter=previous_q2, prior_single_quarter=prior_single,
                cashflow=cash, cashflow_period='2026-Q3',
                disclosed_weighted_diluted_shares=shares,
                reconciliation_tolerance_k=1000,
                reported_amount_resolution_k=1000,
                nonoperating_forecast_policy='PRIOR_FULL_YEAR_BASELINE_UNCHANGED_PENDING_COMPONENT_REVIEW',
                full_notes_and_auditor_review_complete=False)
