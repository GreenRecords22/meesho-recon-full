
import pandas as pd, re
from difflib import SequenceMatcher
from collections import defaultdict
import numpy as np

def parse_amount(s):
    try:
        if pd.isna(s): return 0.0
        if isinstance(s, (int,float)): return float(s)
        txt = str(s)
        txt = txt.replace(",","").replace("Rs","").replace("INR","").replace("₹","").strip()
        m = re.search(r"[-+]?\d+(\.\d+)?", txt)
        return float(m.group()) if m else 0.0
    except:
        return 0.0

def similar(a,b):
    return SequenceMatcher(None, str(a), str(b)).ratio()

def fuzzy_match_orders_to_payments(orders_df, payments_df, order_id_col='__order_id__', amount_col_o='__order_amount__', payment_amount_col='__amount_received__', payment_id_col='__payment_orderid__', amount_tolerance=1.0):
    """
    Attempt to match orders to payments using:
    1) direct OrderID match (if present)
    2) amount + date proximity (if dates exist)
    3) fuzzy match on IDs if small differences
    Returns merged dataframe with 'match_type' describing how matched.
    """
    o = orders_df.copy()
    p = payments_df.copy()

    # ensure amounts parsed
    o[amount_col_o] = o[amount_col_o].apply(parse_amount) if amount_col_o in o.columns else 0.0
    p[payment_amount_col] = p[payment_amount_col].apply(parse_amount) if payment_amount_col in p.columns else 0.0

    # 1) direct merge by ID
    merged = pd.merge(o, p, left_on=order_id_col, right_on=payment_id_col, how='left', indicator=True, suffixes=('_order','_payment'))
    merged['match_type'] = merged['_merge'].map({'both':'direct_id','left_only':None,'right_only':'payment_only'})

    # 2) For unmatched orders, try amount-based matching (one-to-one greedy)
    unmatched_orders = merged[merged['match_type'].isna()].copy()
    payments_pool = p.copy()
    payments_pool['__used__'] = False

    assignments = []
    for idx, row in unmatched_orders.iterrows():
        amt = row.get(amount_col_o, 0.0)
        # find payments within tolerance
        cand = payments_pool[ (payments_pool['__used__']==False) & (abs(payments_pool[payment_amount_col] - amt) <= amount_tolerance) ]
        if not cand.empty:
            # pick the one closest by absolute difference
            cand['diff_abs'] = (cand[payment_amount_col] - amt).abs()
            best = cand.sort_values('diff_abs').iloc[0]
            payments_pool.loc[best.name, '__used__'] = True
            assignments.append((idx, best.name, 'amount_greedy'))
    # apply assignments
    for ord_idx, pay_idx, mtype in assignments:
        for c in p.columns:
            merged.at[ord_idx, c] = p.at[pay_idx, c]
        merged.at[ord_idx, 'match_type'] = mtype

    # 3) fuzzy id match for remaining (small edit distances)
    still_unmatched = merged[merged['match_type'].isna()].copy()
    payment_ids = list(p[payment_id_col].astype(str)) if payment_id_col in p.columns else []
    for idx, row in still_unmatched.iterrows():
        oid = str(row[order_id_col])
        best_score = 0.0; best_pay = None
        for pid in payment_ids:
            sc = similar(oid, pid)
            if sc > best_score:
                best_score = sc; best_pay = pid
        if best_score > 0.85:
            # assign (note: this is heuristic)
            pay_row = p[p[payment_id_col].astype(str)==best_pay].iloc[0]
            for c in p.columns:
                merged.at[idx, c] = pay_row[c]
            merged.at[idx, 'match_type'] = f'fuzzy_id_{best_score:.2f}'

    # fill remaining with statuses
    merged['match_type'] = merged['match_type'].fillna('unmatched')
    return merged

def group_orders_by_batch_and_match(orders_df, bank_stmt_df, order_amount_col='__order_amount__', date_col_orders=None, date_col_bank=None, days_window=2):
    """
    For bank-statement style reconciliation where bank has payout batches (no per-order ids),
    group orders by date window and total amount and try to match to bank entries.
    Returns mapping of bank_row_index -> list of order indices.
    """
    o = orders_df.copy()
    b = bank_stmt_df.copy()
    o[order_amount_col] = o[order_amount_col].apply(parse_amount) if order_amount_col in o.columns else 0.0
    b['__bank_amount__'] = b.apply(lambda r: parse_amount(r.to_string()), axis=1)

    # naive grouping: try to find sets of orders that sum to bank amount (subset sum is NP-hard; use greedy)
    mapping = {}
    for bi, brow in b.iterrows():
        target = brow['__bank_amount__']
        # greedy: sort orders by amount desc, pick until close
        cand_orders = o.sort_values(order_amount_col, ascending=False).copy()
        chosen = []
        s = 0.0
        for oi, orow in cand_orders.iterrows():
            if abs((s + orow[order_amount_col]) - target) <= max(1.0, 0.02*target):
                chosen.append(oi); s += orow[order_amount_col]
            elif (s + orow[order_amount_col]) <= target:
                chosen.append(oi); s += orow[order_amount_col]
            if s>= target*(0.98):
                break
        mapping[bi] = {'orders': chosen, 'sum': s, 'target': target}
    return mapping
