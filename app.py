import streamlit as st
import pandas as pd
import io
import os
import importlib
from datetime import datetime
import altair as alt

# Reload utils to avoid cached version issues on Streamlit Cloud
import utils
importlib.reload(utils)
from utils import fuzzy_match_orders_to_payments, group_orders_by_batch_and_match, parse_amount

st.set_page_config(page_title="Meesho Recon — Advanced", layout="wide")
st.title("📊 Meesho Payment Reconciliation — Advanced Dashboard")

st.sidebar.header("Controls")
mode = st.sidebar.selectbox("Mode", ["Reconciliation", "Analytics", "Bank-statement Match", "About"])

# ---------------------------------------------------------------------
# ABOUT
# ---------------------------------------------------------------------
if mode == "About":
    st.markdown("""
    ### 🧩 Meesho Recon — Advanced Dashboard
    - Upload **Orders** & **Payments** CSV/XLSX files.
    - Automatically match using **fuzzy logic + amount tolerance**.
    - View analytics like **Matched %, Payout Difference**, and unmatched order insights.
    - Perform **Bank Statement Reconciliation** for payout batches.
    """)

# ---------------------------------------------------------------------
# RECONCILIATION MODE
# ---------------------------------------------------------------------
if mode == "Reconciliation":
    st.header("🔍 Reconciliation (Per-Order Matching)")
    c1, c2 = st.columns([1, 1])
    with c1:
        orders_file = st.file_uploader("📄 Orders CSV/XLSX", type=["csv", "xlsx"], key="o_file")
    with c2:
        payments_file = st.file_uploader("💰 Payments CSV/XLSX (Settlements)", type=["csv", "xlsx"], key="p_file")

    st.markdown("**Options**")
    tolerance = st.number_input("Amount tolerance (₹)", value=1.0, step=0.5)

    if not orders_file:
        st.info("Upload your Orders file to begin.")
        st.stop()

    # Read Orders file
    if orders_file.name.lower().endswith(".xlsx"):
        orders_df = pd.read_excel(orders_file)
    else:
        orders_df = pd.read_csv(orders_file, low_memory=False)

    # Read Payments file (optional)
    if payments_file:
        if payments_file.name.lower().endswith(".xlsx"):
            payments_df = pd.read_excel(payments_file)
        else:
            payments_df = pd.read_csv(payments_file, low_memory=False)
    else:
        payments_df = pd.DataFrame()

    # Preview tables
    st.subheader("Preview: Orders (Top 5 Rows)")
    st.dataframe(orders_df.head())
    st.subheader("Preview: Payments (Top 5 Rows)")
    st.dataframe(payments_df.head())

    # Helper: find best matching column names
    def find_like(columns, keywords):
        for key in keywords:
            for col in columns:
                if key.lower() in col.lower():
                    return col
        return None

    # Auto-detect column names
    cols_o = list(orders_df.columns)
    cols_p = list(payments_df.columns) if not payments_df.empty else []

    order_id_col = find_like(cols_o, ["order id", "sub order", "packet id"]) or "__order_id__"
    order_amount_col = find_like(cols_o, ["amount", "supplier discounted", "price"]) or "__order_amount__"
    payment_id_col = find_like(cols_p, ["order id", "packet id", "sub order"]) or "__payment_orderid__"
    payment_amount_col = find_like(cols_p, ["amount", "credited", "paid"]) or "__amount_received__"

    # Prepare columns
    orders_df_copy = orders_df.copy()
    payments_df_copy = payments_df.copy()

    orders_df_copy["__order_id__"] = orders_df_copy.get(order_id_col, orders_df_copy.index).astype(str)
    orders_df_copy["__order_amount__"] = orders_df_copy.get(order_amount_col, 0).apply(parse_amount)

    if not payments_df.empty:
        payments_df_copy["__payment_orderid__"] = payments_df_copy.get(payment_id_col, payments_df_copy.index).astype(str)
        payments_df_copy["__amount_received__"] = payments_df_copy.get(payment_amount_col, 0).apply(parse_amount)
    else:
        payments_df_copy["__payment_orderid__"] = []
        payments_df_copy["__amount_received__"] = []

    # Perform reconciliation
    merged = fuzzy_match_orders_to_payments(
        orders_df_copy,
        payments_df_copy,
        order_id_col="__order_id__",
        amount_col_o="__order_amount__",
        payment_amount_col="__amount_received__",
        payment_id_col="__payment_orderid__",
        amount_tolerance=tolerance,
    )

    # Summary Metrics
    total_orders = len(orders_df_copy)
    total_payments = len(payments_df_copy)
    matched_direct = (merged["match_type"] == "direct_id").sum()
    matched_amount = merged["match_type"].str.contains("amount_greedy").sum()
    matched_fuzzy = merged["match_type"].str.contains("fuzzy_id").sum()
    unmatched = (merged["match_type"] == "unmatched").sum()

    payout_diff = merged["__amount_received__"].fillna(0).sum() - merged["__order_amount__"].fillna(0).sum()

    st.subheader("📊 Summary Metrics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Orders", total_orders)
    c2.metric("Total Payments", total_payments)
    c3.metric("Matched %", f"{(matched_direct + matched_amount + matched_fuzzy) / max(1, total_orders) * 100:.1f}%")
    c4.metric("Payout Difference (₹)", f"{payout_diff:.2f}")

    # Display results
    st.markdown("---")
    st.subheader("Unmatched Orders (Sample)")
    st.dataframe(merged[merged["match_type"] == "unmatched"].head(50))

    st.markdown("---")
    st.subheader("Detailed Reconciliation Table")
    st.dataframe(merged.head(500))

    # Download Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        merged.to_excel(writer, index=False, sheet_name="Reconciliation_Detail")
        pd.DataFrame([
            {"Metric": "Total Orders", "Value": total_orders},
            {"Metric": "Total Payments", "Value": total_payments},
            {"Metric": "Matched (Direct)", "Value": matched_direct},
            {"Metric": "Matched (Amount)", "Value": matched_amount},
            {"Metric": "Matched (Fuzzy)", "Value": matched_fuzzy},
            {"Metric": "Unmatched", "Value": unmatched},
            {"Metric": "Payout Difference (₹)", "Value": payout_diff},
            {"Metric": "Exported At", "Value": datetime.now().isoformat()},
        ]).to_excel(writer, index=False, sheet_name="Summary")

    buffer.seek(0)
    st.download_button(
        "⬇️ Download Reconciliation Excel",
        data=buffer,
        file_name="meesho_reconciliation_advanced.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---------------------------------------------------------------------
# BANK STATEMENT MATCH
# ---------------------------------------------------------------------
if mode == "Bank-statement Match":
    st.header("🏦 Bank-statement / Payout Batch Matcher")
    bf1, bf2 = st.columns(2)
    with bf1:
        orders_file = st.file_uploader("Orders CSV/XLSX", type=["csv", "xlsx"], key="bs_o")
    with bf2:
        bank_file = st.file_uploader("Bank Statement / Payout CSV/XLSX", type=["csv", "xlsx"], key="bs_b")

    if orders_file and bank_file:
        orders_df = pd.read_excel(orders_file) if orders_file.name.endswith(".xlsx") else pd.read_csv(orders_file)
        bank_df = pd.read_excel(bank_file) if bank_file.name.endswith(".xlsx") else pd.read_csv(bank_file)

        st.write("🔎 Running greedy batch match (heuristic)...")
        mapping = group_orders_by_batch_and_match(orders_df, bank_df)
        st.json(mapping)
        st.markdown("⚠️ Review mapping carefully — this is heuristic-based.")

# ---------------------------------------------------------------------
# ANALYTICS MODE
# ---------------------------------------------------------------------
if mode == "Analytics":
    st.header("📈 Analytics & KPIs")
    f = st.file_uploader("Upload Orders CSV for KPIs", type=["csv", "xlsx"], key="kpi_o")

    if f:
        df = pd.read_excel(f) if f.name.endswith(".xlsx") else pd.read_csv(f)
        cols = list(df.columns)
        sku = st.selectbox("SKU column", ["--select--"] + cols)
        pricec = st.selectbox("Selling Price column", ["--select--"] + cols)
        datec = st.selectbox("Date column", ["--select--"] + cols)

        if st.button("Generate KPIs"):
            df["__price__"] = df[pricec].apply(parse_amount) if pricec != "--select--" else 0.0
            df["__date__"] = pd.to_datetime(df[datec], errors="coerce") if datec != "--select--" else pd.to_datetime("today")
            df["month"] = df["__date__"].dt.to_period("M").astype(str)
            top = (
                df.groupby(sku)
                .agg(qty=("Quantity", "sum"), revenue=("__price__", "sum"))
                .reset_index()
                .sort_values("revenue", ascending=False)
                .head(50)
            )

            st.subheader("🏆 Top SKUs by Revenue")
            st.dataframe(top)

            chart_df = df.groupby("month").agg(rev=("__price__", "sum")).reset_index()
            chart = alt.Chart(chart_df).mark_line(point=True).encode(x="month", y="rev")
            st.altair_chart(chart, use_container_width=True)
