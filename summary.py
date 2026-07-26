# -*- coding: utf-8 -*-
"""
Summary/aggregation builder — ported from expense_analysis/build_summary.py,
parameterised to take an in-memory list of transaction dicts (pulled live
from the database) instead of a static JSON file, so reports always reflect
whatever has been uploaded so far.
"""
import re
from collections import defaultdict, Counter

CATS = ['Groceries', 'Utility Bills', 'Loans', 'Hotel/Food', 'Other']
CURRENT_ACCOUNTS = ['HSBC Current Account', 'Halifax Current Account']

MONTH_NUM_TO_LABEL = {
    '01': 'Jan', '02': 'Feb', '03': 'Mar', '04': 'Apr', '05': 'May', '06': 'Jun',
    '07': 'Jul', '08': 'Aug', '09': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dec',
}

def month_label(m):
    y, mo = m.split('-')
    return f"{MONTH_NUM_TO_LABEL[mo]} {y[2:]}"

def year_bucket(m):
    return m[:4]

def build_summary(txns, months_order):
    monthly_cat = {m: {c: 0.0 for c in CATS} for m in months_order}
    monthly_income = {m: 0.0 for m in months_order}
    monthly_excluded = {m: 0.0 for m in months_order}
    monthly_account_spend = {m: defaultdict(float) for m in months_order}
    monthly_other_sub = {m: defaultdict(float) for m in months_order}

    monthly_ca_in = {m: 0.0 for m in months_order}
    monthly_ca_out = {m: 0.0 for m in months_order}

    monthly_dd = {m: defaultdict(float) for m in months_order}
    dd_payee_totals = Counter()
    dd_count = 0

    monthly_atm = {m: defaultdict(float) for m in months_order}
    atm_count = 0

    merchant_totals = Counter()
    subcat_totals = Counter()
    shopping_subcat_totals = Counter()
    account_totals = Counter()

    txn_detail = []

    for t in txns:
        m = t['month']
        if m not in monthly_cat:
            continue

        if t['account'] in CURRENT_ACCOUNTS:
            if t['dir'] == 'out':
                monthly_ca_out[m] += t['amount']
            else:
                monthly_ca_in[m] += t['amount']

        if t['dir'] == 'out' and t.get('is_dd') and t['account'] in CURRENT_ACCOUNTS:
            monthly_dd[m][t['account']] += t['amount']
            dd_payee_totals[t.get('canonical_merchant') or t['desc']] += t['amount']
            dd_count += 1

        if t['dir'] == 'out' and t.get('is_atm'):
            monthly_atm[m][t['account']] += t['amount']
            atm_count += 1

        if t['dir'] == 'out':
            if t['category'] in CATS:
                monthly_cat[m][t['category']] += t['amount']
                monthly_account_spend[m][t['account']] += t['amount']
                account_totals[t['account']] += t['amount']
                key = t.get('canonical_merchant') or re.sub(r'\s+', ' ', t['desc']).strip()
                merchant_totals[key] += t['amount']
                txn_detail.append({
                    'm': m, 'c': t['category'], 'a': round(t['amount'], 2),
                    'l': key[:40], 'd': t['date'], 'acc': t['account'],
                    'dd': bool(t.get('is_dd')), 'atm': bool(t.get('is_atm')),
                })
                if t['category'] == 'Other':
                    monthly_other_sub[m][t['subcategory']] += t['amount']
                    subcat_totals[t['subcategory']] += t['amount']
                    if t.get('shopping_subcategory'):
                        shopping_subcat_totals[t['shopping_subcategory']] += t['amount']
            else:
                monthly_excluded[m] += t['amount']
        else:
            if t['category'] == 'Income':
                monthly_income[m] += t['amount']
            elif t.get('is_refund') and t['category'] in CATS:
                cat = t['category']
                monthly_cat[m][cat] -= t['amount']
                monthly_account_spend[m][t['account']] -= t['amount']
                account_totals[t['account']] -= t['amount']
                key = t.get('canonical_merchant') or re.sub(r'\s+', ' ', t['desc']).strip()
                merchant_totals[key] -= t['amount']
                txn_detail.append({
                    'm': m, 'c': cat, 'a': round(-t['amount'], 2),
                    'l': key[:36] + ' (refund)', 'd': t['date'], 'acc': t['account'],
                    'dd': False, 'atm': False,
                })
                if cat == 'Other':
                    monthly_other_sub[m][t['subcategory']] -= t['amount']
                    subcat_totals[t['subcategory']] -= t['amount']
                    if t.get('shopping_subcategory'):
                        shopping_subcat_totals[t['shopping_subcategory']] -= t['amount']

    years_seen = []
    for m in months_order:
        y = year_bucket(m)
        if y not in years_seen:
            years_seen.append(y)
    year_span = {}
    MON3 = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    for y in years_seen:
        ms = [m for m in months_order if year_bucket(m) == y]
        mm = sorted(int(m[5:7]) for m in ms)
        year_span[y] = f"{MON3[mm[0]]}–{MON3[mm[-1]]} {y}" if len(mm) > 1 else f"{MON3[mm[0]]} {y}"

    yearly_category_spend = {y: {c: 0.0 for c in CATS} for y in years_seen}
    yearly_income = {y: 0.0 for y in years_seen}
    yearly_excluded = {y: 0.0 for y in years_seen}
    yearly_dd = {y: 0.0 for y in years_seen}
    yearly_atm = {y: 0.0 for y in years_seen}
    for m in months_order:
        y = year_bucket(m)
        for c in CATS:
            yearly_category_spend[y][c] += monthly_cat[m][c]
        yearly_income[y] += monthly_income[m]
        yearly_excluded[y] += monthly_excluded[m]
        yearly_dd[y] += sum(monthly_dd[m].values())
        yearly_atm[y] += sum(monthly_atm[m].values())

    summary = {
        'months': months_order,
        'month_labels': [month_label(m) for m in months_order],
        'categories': CATS,
        'monthly_category_spend': {m: monthly_cat[m] for m in months_order},
        'monthly_income': monthly_income,
        'monthly_excluded_transfers': monthly_excluded,
        'monthly_account_spend': {m: dict(monthly_account_spend[m]) for m in months_order},
        'monthly_other_subcategory': {m: dict(monthly_other_sub[m]) for m in months_order},
        'category_totals': {c: sum(monthly_cat[m][c] for m in months_order) for c in CATS},
        'other_subcategory_totals': dict(subcat_totals),
        'shopping_subcategory_totals': dict(shopping_subcat_totals),
        'account_totals': dict(account_totals),
        'top_merchants': merchant_totals.most_common(20),
        'total_income': sum(monthly_income.values()),
        'total_excluded': sum(monthly_excluded.values()),
        'total_spend': sum(sum(monthly_cat[m].values()) for m in months_order),

        'monthly_ca_in': monthly_ca_in,
        'monthly_ca_out': monthly_ca_out,
        'total_ca_in': sum(monthly_ca_in.values()),
        'total_ca_out': sum(monthly_ca_out.values()),

        'monthly_dd_total': {m: dict(monthly_dd[m]) for m in months_order},
        'monthly_dd_combined': {m: sum(monthly_dd[m].values()) for m in months_order},
        'dd_top_payees': dd_payee_totals.most_common(12),
        'total_dd': sum(sum(monthly_dd[m].values()) for m in months_order),
        'dd_count': dd_count,

        'monthly_atm_total': {m: dict(monthly_atm[m]) for m in months_order},
        'monthly_atm_combined': {m: sum(monthly_atm[m].values()) for m in months_order},
        'total_atm': sum(sum(monthly_atm[m].values()) for m in months_order),
        'atm_count': atm_count,

        'years': years_seen,
        'year_labels': [year_span[y] for y in years_seen],
        'yearly_category_spend': yearly_category_spend,
        'yearly_income': yearly_income,
        'yearly_excluded': yearly_excluded,
        'yearly_dd': yearly_dd,
        'yearly_atm': yearly_atm,
        'yearly_total_spend': {y: sum(yearly_category_spend[y].values()) for y in years_seen},

        'txn_detail': sorted(txn_detail, key=lambda x: (x['m'], -x['a'])),
    }
    return summary


def pick_report_ranges(all_months_sorted):
    """
    Given every distinct YYYY-MM month present in the DB (sorted ascending),
    decide the 3 report windows dynamically so reports keep making sense as
    new statements are uploaded month after month, instead of a hardcoded
    Jul2025-Jun2026 range.
    """
    ranges = {}
    if not all_months_sorted:
        return ranges
    last12 = all_months_sorted[-12:]
    ranges['all'] = {
        'key': 'all', 'label': 'Full history', 'months': all_months_sorted,
    }
    if len(all_months_sorted) > 12:
        ranges['last12'] = {'key': 'last12', 'label': 'Last 12 months', 'months': last12}
    recent6 = all_months_sorted[-6:]
    ranges['recent6'] = {
        'key': 'recent6', 'label': 'Most recent 6 months', 'months': recent6,
    }
    remaining = all_months_sorted[:-6]
    if remaining:
        prev6 = remaining[-6:]
        ranges['prev6'] = {'key': 'prev6', 'label': 'Previous 6 months', 'months': prev6}
    return ranges
