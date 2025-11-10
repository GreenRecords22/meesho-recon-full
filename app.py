
import streamlit as st
import pandas as pd, io, os, importlib
from datetime import datetime
import altair as alt

# reload utils to avoid stale cache on Streamlit Cloud
import utils
importlib.reload(utils)
from utils import fuzzy_match_orders_to_payments, group_orders_by_batch_and_match, parse_amount

st.set_page_config(page_title="Meesho Recon — Advanced", layout="wide")
st.title("Meesho Payment Reconciliation — Advanced Dashboard")

st.sidebar.header("Controls")
mode = st.sidebar.selectbox("Mode", ["Reconciliation", "Analytics", "Bank-statement Match", "About"])

# Simple info
if mode == "About":
    st.markdown(\"\"\"
    **Meesho Recon — Advanced**  
    - Upload Orders & Payments (per-order) CSV/XLSX.  
    - Advanced fuzzy reconciliation + analytics.  
    - Bank-statement batch matching for aggregated payouts.  
    \"\"\")

# RECONCILIATION
if mode == "Reconciliation":
    st.header("Reconciliation (per-order)")
    c1, c2 = st.columns([1,1])
    with c1:
        orders_file = st.file_uploader("Orders CSV/XLSX", type=["csv","xlsx"], key="o_file")
    with c2:
        payments_file = st.file_uploader("Payments CSV/XLSX (per-order settlements)", type=["csv","xlsx"], key="p_file")

    st.markdown("**Options**")
    tolerance = st.number_input("Amount tolerance (₹)", value=1.0, step=0.5)
    date_filter = st.date_input("Show orders from date (optional)", value=None)
    if isinstance(date_filter, list): # safety
        date_filter = date_filter[0] if date_filter else None

    if orders_file is None:
        st.info("Upload Orders file to begin.")
        st.stop()

    # load orders
    if str(orders_file.name).lower().endswith(".xlsx"):
        orders_df = pd.read_excel(orders_file)
    else:
        orders_df = pd.read_csv(orders_file, low_memory=False)

    # load payments
    if payments_file is not None:
        if str(payments_file.name).lower().endswith(".xlsx"):
            payments_df = pd.read_excel(payments_file)
        else:
            payments_df = pd.read_csv(payments_file, low_memory=False)
    else:
        payments_df = pd.DataFrame()

    st.subheader("Preview: Orders (first 5 rows)")
    st.dataframe(orders_df.head(5))
    st.subheader("Preview: Payments (first 5 rows)")
    st.dataframe(payments_df.head(5))

    # Ask mapping or try autodetect
    st.markdown("### Column mapping (auto-detected if possible)")
    cols_o = list(orders_df.columns)
    cols_p = list(payments_df.columns) if not payments_df.empty else []

    # heuristics names
    def find_like(cols, keywords):
        for k in keywords:
            for c in cols:
                if k.lower() in c.lower():
                    return c
        return None

    order_id_col = find_like(cols_o, ["sub order","order id","sub order no","packet id","order no"]) or st.selectbox("Order ID column (orders)", ["--auto--"]+cols_o, index=0)
    order_amount_col = find_like(cols_o, ["supplier discounted price","supplier listed price","amount","price","order value"]) or st.selectbox("Order Amount column (orders)", ["--auto--"]+cols_o, index=0)
    order_date_col = find_like(cols_o, ["order date","date"]) or st.selectbox("Order Date column (orders)", ["--auto--"]+cols_o, index=0)

    payment_id_col = find_like(cols_p, ["order id","sub order","packet id"]) or st.selectbox("Order ID column (payments)", ["--auto--"]+cols_p, index=0)
    payment_amount_col = find_like(cols_p, ["amount","paid","credited","settlement"]) or st.selectbox("Amount column (payments)", ["--auto--"]+cols_p, index=0)
    commission_col = find_like(cols_p, ["commission","fee","charge"]) or st.selectbox("Commission column (payments)", ["--auto--"]+cols_p, index=0)

    # Normalize chosen values: if auto found returns string; if user selected, selection is string
    if order_id_col == "--auto--": order_id_col = find_like(cols_o, ["sub order","order id","sub order no","packet id","order no"]) or "__order_id__"
    if order_amount_col == "--auto--": order_amount_col = find_like(cols_o, ["supplier discounted price","supplier listed price","amount","price","order value"]) or "__order_amount__"
    if order_date_col == "--auto--": order_date_col = find_like(cols_o, ["order date","date"]) or None

    if payment_id_col == "--auto--": payment_id_col = find_like(cols_p, ["order id","sub order","packet id"]) or "__payment_orderid__"
    if payment_amount_col == "--auto--": payment_amount_col = find_like(cols_p, ["amount","paid","credited","settlement"]) or "__amount_received__"
    if commission_col == "--auto--": commission_col = find_like(cols_p, ["commission","fee","charge"]) or None

    # Prepare orders: ensure id and amount columns exist
    orders_df_copy = orders_df.copy()
    if order_id_col not in orders_df_copy.columns:
        orders_df_copy["__order_id__"] = orders_df_copy.index.astype(str)
    else:
        orders_df_copy["__order_id__"] = orders_df_copy[order_id_col].astype(str).str.strip()

    if order_amount_col not in orders_df_copy.columns:
        orders_df_copy["__order_amount__"] = 0.0
    else:
        orders_df_copy["__order_amount__"] = orders_df_copy[order_amount_col].apply(parse_amount)

    # Prepare payments: ensure columns exist
    payments_df_copy = payments_df.copy() if not payments_df.empty else pd.DataFrame()
    if payment_id_col not in payments_df_copy.columns:
        payments_df_copy["__payment_orderid__"] = payments_df_copy.index.astype(str)
    else:
        payments_df_copy["__payment_orderid__"] = payments_df_copy[payment_id_col].astype(str).str.strip()
    if payment_amount_col not in payments_df_copy.columns:
        payments_df_copy["__amount_received__"] = 0.0
    else:
        payments_df_copy["__amount_received__"] = payments_df_copy[payment_amount_col].apply(parse_amount)
    if commission_col and commission_col in payments_df_copy.columns:
        payments_df_copy["__commission__"] = payments_df_copy[commission_col].apply(parse_amount)
    else:
        payments_df_copy["__commission__"] = 0.0

    # Optionally filter by date
    if order_date_col and order_date_col in orders_df_copy.columns and st.checkbox("Filter by Order Date", value=False):
        try:
            orders_df_copy[order_date_col] = pd.to_datetime(orders_df_copy[order_date_col], errors="coerce")
            start = st.date_input("Start date", value=None)
            end = st.date_input("End date", value=None)
            if start and end:
                orders_df_copy = orders_df_copy[(orders_df_copy[order_date_col].dt.date >= start) & (orders_df_copy[order_date_col].dt.date <= end)]
        except Exception as e:
            st.warning("Could not parse order dates: " + str(e))

    # Run advanced fuzzy reconciliation
    merged = fuzzy_match_orders_to_payments(
        orders_df_copy,
        payments_df_copy,
        order_id_col="__order_id__",
        amount_col_o="__order_amount__",
        payment_amount_col="__amount_received__",
        payment_id_col="__payment_orderid__",
        amount_tolerance=tolerance,
    )

    # Analytics
    total_orders = len(orders_df_copy)
    total_payments = len(payments_df_copy)
    matched_direct = (merged["match_type"] == "direct_id").sum()
    matched_amount = merged["match_type"].str.contains("amount_greedy").sum()
    matched_fuzzy = merged["match_type"].str.contains("fuzzy_id").sum()
    unmatched = (merged["match_type"] == "unmatched").sum()

    st.subheader("Summary Metrics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Orders", total_orders)
    c2.metric("Total Payments (rows)", total_payments)
    c3.metric("Matched %", f"{(matched_direct+matched_amount+matched_fuzzy)/max(1,total_orders)*100:.1f}%")
    # compute payout diff: sum(amount_received) - sum(order_amount)
    payout_diff = merged["__amount_received__"].fillna(0).sum() - merged["__order_amount__"].fillna(0).sum()
    c4.metric("Total Payout Difference (₹)", f"{payout_diff:.2f}")

    st.markdown("---")
    st.subheader("Top issues / quick views")
    st.write("Unmatched orders (sample):")
    st.dataframe(merged[merged['match_type']=='unmatched'].head(50))

    st.markdown("---")
    st.subheader("Detailed table (first 500 rows)")
    st.dataframe(merged.head(500))

    # Export Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        merged.to_excel(writer, index=False, sheet_name="Reconciliation_Detail")
        pd.DataFrame([
            {"Metric": "Total Orders", "Value": total_orders},
            {"Metric": "Total Payments (rows)", "Value": total_payments},
            {"Metric": "Matched (direct)", "Value": int(matched_direct)},
            {"Metric": "Matched (amount)", "Value": int(matched_amount)},
            {"Metric": "Matched (fuzzy)", "Value": int(matched_fuzzy)},
            {"Metric": "Unmatched", "Value": int(unmatched)},
            {"Metric": "Payout Difference (₹)", "Value": f"{payout_diff:.2f}"},
            {"Metric": "Exported At", "Value": datetime.now().isoformat()}
        ]).to_excel(writer, index=False, sheet_name="Summary")
    buffer.seek(0)
    st.download_button("⬇️ Download Reconciliation Excel", buffer, file_name="meesho_reconciliation_advanced.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# BANK STATEMENT MATCH
if mode == "Bank-statement Match":
    st.header("Bank-statement / Payout-batch Matcher")
    bf1, bf2 = st.columns(2)
    with bf1:
        orders_file = st.file_uploader("Orders CSV/XLSX", type=["csv","xlsx"], key="bs_o")
    with bf2:
        bank_file = st.file_uploader("Bank Statement / Payout CSV/XLSX", type=["csv","xlsx"], key="bs_b")
    if orders_file and bank_file:
        if str(orders_file.name).lower().endswith(".xlsx"):
            orders_df = pd.read_excel(orders_file)
        else:
            orders_df = pd.read_csv(orders_file, low_memory=False)
        if str(bank_file.name).lower().endswith(".xlsx"):
            bank_df = pd.read_excel(bank_file)
        else:
            bank_df = pd.read_csv(bank_file, low_memory=False)
        st.write("Running greedy batch match (heuristic) ...")
        mapping = group_orders_by_batch_and_match(orders_df, bank_df, order_amount_col="Supplier Discounted Price (Incl GST and Commision)")
        st.json(mapping)
        st.markdown("Review mapping carefully; this is a greedy heuristic.")

# ANALYTICS
if mode == "Analytics":
    st.header("Analytics & KPIs")
    f = st.file_uploader("Upload Orders CSV for KPIs", type=["csv","xlsx"], key="kpi_o")
    if f:
        if str(f.name).lower().endswith(".xlsx"):
            df = pd.read_excel(f)
        else:
            df = pd.read_csv(f, low_memory=False)
        cols = list(df.columns)
        sku = st.selectbox("SKU column", ["--select--"]+cols)
        pricec = st.selectbox("Selling Price column", ["--select--"]+cols)
        datec = st.selectbox("Date column", ["--select--"]+cols)
        if st.button("Generate KPIs"):
            df["__price__"] = df[pricec].apply(parse_amount) if pricec!="--select--" else 0.0
            df["__date__"] = pd.to_datetime(df[datec], errors="coerce") if datec!="--select--" else pd.to_datetime("today")
            df["month"] = df["__date__"].dt.to_period("M").astype(str)
            top = df.groupby(sku).agg(qty=("Quantity","sum"), revenue=("__price__","sum")).reset_index().sort_values("revenue", ascending=False).head(50)
            st.subheader("Top SKUs by Revenue")
            st.dataframe(top)
            chart_df = df.groupby("month").agg(rev=("__price__","sum")).reset_index()
            chart = alt.Chart(chart_df).mark_line(point=True).encode(x="month", y="rev")
            st.altair_chart(chart, use_container_width=True)
