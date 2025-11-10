
import streamlit as st
import pandas as pd, io, re, os, json
import altair as alt
from datetime import datetime
from utils import parse_amount, fuzzy_match_orders_to_payments, group_orders_by_batch_and_match

st.set_page_config(page_title="Meesho Recon — Full", layout="wide")
st.title("Meesho Reconciliation & Insights — Full Edition")

# Load presets
PRESETS_PATH = "presets.json"
if os.path.exists(PRESETS_PATH):
    with open(PRESETS_PATH, "r", encoding="utf-8") as f:
        PRESETS = json.load(f)
else:
    PRESETS = {}

# Sidebar for features
st.sidebar.header("Quick Menu")
mode = st.sidebar.selectbox("Mode", ["Reconciliation","Bank-statement Match","Profit & Loss","KPI Dashboard","Settings","About"])

# Optional simple auth via env variable (if set)
PASSWORD = os.environ.get("MEESHO_RECON_PASS")
if PASSWORD:
    pw = st.sidebar.text_input("Password (env-protected)", type="password")
    if pw != PASSWORD:
        st.warning("Enter password to proceed")
        st.stop()

if mode == "About":
    st.markdown("Full-featured Meesho Reconciliation tool with presets, fuzzy matching, bank-statement reconciliation, KPIs and profit analytics.")

if mode == "Settings":
    st.subheader("Presets loaded")
    st.json(PRESETS)
    st.markdown("You can edit `presets.json` file to add more presets for different CSV layouts.")

if mode == "Profit & Loss":
    st.header("Profit & Loss (advanced)")
    df = st.file_uploader("Upload Orders CSV to compute P&L by SKU (optional)", type=["csv","xlsx"])
    if df is not None:
        if str(df.name).lower().endswith(".xlsx"):
            odf = pd.read_excel(df)
        else:
            odf = pd.read_csv(df, low_memory=False)
        # ask for mapping
        sku_col = st.selectbox("SKU column", ["--select--"] + list(odf.columns))
        price_col = st.selectbox("Selling price column", ["--select--"] + list(odf.columns))
        cost_col = st.selectbox("Cost price column", ["--select--"] + list(odf.columns))
        if st.button("Compute P&L by SKU"):
            odf['__selling__'] = odf[price_col].apply(parse_amount) if price_col!="--select--" else 0.0
            odf['__cost__'] = odf[cost_col].apply(parse_amount) if cost_col!="--select--" else 0.0
            report = odf.groupby(sku_col).agg(total_qty=('Quantity','sum'), revenue=('__selling__','sum'), cost=('__cost__','sum')).reset_index()
            report['profit'] = report['revenue'] - report['cost']
            st.dataframe(report.sort_values('profit', ascending=False).head(50))
            st.download_button("Download P&L XLSX", data=to_excel_bytes(report), file_name="pl_by_sku.xlsx")

if mode == "Reconciliation":
    st.header("Per-order Reconciliation (fuzzy + presets)")
    col1, col2 = st.columns(2)
    with col1:
        orders_file = st.file_uploader("Orders CSV/XLSX (per-order)", type=["csv","xlsx"], key="o1")
    with col2:
        payments_file = st.file_uploader("Payments CSV/XLSX (per-order settlements)", type=["csv","xlsx"], key="p1")

    preset_choice = st.selectbox("Apply preset", ["--none--"] + list(PRESETS.keys()))
    if preset_choice != "--none--":
        preset = PRESETS[preset_choice]
    else:
        preset = {}

    if orders_file is not None:
        if str(orders_file.name).lower().endswith(".xlsx"):
            o = pd.read_excel(orders_file)
        else:
            o = pd.read_csv(orders_file, low_memory=False)
        st.write("Orders rows:", o.shape[0])
        st.dataframe(o.head(6))
    else:
        o = None

    if payments_file is not None:
        if str(payments_file.name).lower().endswith(".xlsx"):
            p = pd.read_excel(payments_file)
        else:
            p = pd.read_csv(payments_file, low_memory=False)
        st.write("Payments rows:", p.shape[0])
        st.dataframe(p.head(6))
    else:
        p = None

    # detect defaults
    def find_in(cols, name):
        for c in cols:
            if name and name.lower() in c.lower():
                return c
        return None

    possible_order_cols = list(o.columns) if o is not None else []
    possible_pay_cols = list(p.columns) if p is not None else []

    order_id_col = find_in(possible_order_cols, preset.get("order_id_col")) or st.selectbox("Order ID column", ["--select--"] + possible_order_cols)
    order_amount_col = find_in(possible_order_cols, preset.get("order_amount_col")) or st.selectbox("Order Amount column", ["--select--"] + possible_order_cols)
    payment_id_col = find_in(possible_pay_cols, preset.get("payment_orderid_col")) or st.selectbox("Payment Order ID column", ["--select--"] + possible_pay_cols)
    payment_amount_col = find_in(possible_pay_cols, preset.get("payment_amount_col")) or st.selectbox("Payment Amount column", ["--select--"] + possible_pay_cols)

    tolerance = st.number_input("Amount tolerance (₹)", value=1.0)
    if st.button("Run advanced reconciliation"):
        if o is None:
            st.error("Upload orders file first")
        else:
            o2 = o.copy()
            p2 = p.copy() if p is not None else pd.DataFrame()
            # standardize
            if isinstance(order_id_col, str) and order_id_col!="--select--":
                o2['__order_id__'] = o2[order_id_col].astype(str).str.strip()
            else:
                o2['__order_id__'] = o2.index.astype(str)
            if isinstance(order_amount_col, str) and order_amount_col!="--select--":
                o2['__order_amount__'] = o2[order_amount_col].apply(parse_amount)
            else:
                o2['__order_amount__'] = 0.0
            if p is not None and isinstance(payment_id_col, str) and payment_id_col!="--select--":
                p2['__payment_orderid__'] = p2[payment_id_col].astype(str).str.strip()
            if p is not None and isinstance(payment_amount_col, str) and payment_amount_col!="--select--":
                p2['__amount_received__'] = p2[payment_amount_col].apply(parse_amount)
            # run fuzzy matcher
            merged = fuzzy_match_orders_to_payments(o2, p2, order_id_col='__order_id__', amount_col_o='__order_amount__', payment_amount_col='__amount_received__', payment_id_col='__payment_orderid__', amount_tolerance=tolerance)
            merged['__diff__'] = merged['__amount_received__'].fillna(0.0) - merged['__order_amount__'].fillna(0.0)
            st.subheader("Summary")
            st.write("Total orders:", o2.shape[0])
            st.write("Total payments rows:", p2.shape[0] if p is not None else 0)
            st.write("Matched (direct or fuzzy):", merged[merged['match_type']!='unmatched'].shape[0])
            st.write("Unmatched:", merged[merged['match_type']=='unmatched'].shape[0])
            st.dataframe(merged.head(200))
            # download
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                merged.to_excel(writer, index=False, sheet_name="Detail")
            buf.seek(0)
            st.download_button("Download advanced reconciliation", buf, file_name="meesho_recon_full.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if mode == "Bank-statement Match":
    st.header("Bank-statement / Payout-batch fuzzy matcher")
    orders_file = st.file_uploader("Orders CSV/XLSX (per-order)", type=["csv","xlsx"], key="bs_o")
    bank_file = st.file_uploader("Bank statement / Payout CSV/XLSX", type=["csv","xlsx"], key="bs_b")
    if orders_file is not None and bank_file is not None:
        if str(orders_file.name).lower().endswith(".xlsx"):
            o = pd.read_excel(orders_file)
        else:
            o = pd.read_csv(orders_file, low_memory=False)
        if str(bank_file.name).lower().endswith(".xlsx"):
            b = pd.read_excel(bank_file)
        else:
            b = pd.read_csv(bank_file, low_memory=False)
        st.write("Orders rows:", o.shape[0], "Bank rows:", b.shape[0])
        mapping = group_orders_by_batch_and_match(o, b, order_amount_col='Supplier Discounted Price (Incl GST and Commision)')
        st.json(mapping)
        st.markdown("Note: this is a heuristic greedy grouping. Review results manually.")

if mode == "KPI Dashboard":
    st.header("KPIs & Charts")
    st.markdown("Upload Orders CSV to compute KPIs (top SKUs, revenue trends)")
    f = st.file_uploader("Orders CSV", type=["csv","xlsx"], key="kpi_o")
    if f is not None:
        if str(f.name).lower().endswith(".xlsx"):
            df = pd.read_excel(f)
        else:
            df = pd.read_csv(f, low_memory=False)
        # Try find columns
        cols = list(df.columns)
        sku = st.selectbox("SKU column", ["--select--"] + cols)
        datec = st.selectbox("Date column", ["--select--"] + cols)
        pricec = st.selectbox("Price/Sales column", ["--select--"] + cols)
        if st.button("Generate KPIs"):
            df['__price__'] = df[pricec].apply(parse_amount) if pricec!="--select--" else 0.0
            df['__date__'] = pd.to_datetime(df[datec]) if datec!="--select--" else pd.to_datetime("today")
            df['month'] = df['__date__'].dt.to_period("M").astype(str)
            top = df.groupby(sku).agg(qty=('Quantity','sum'), revenue=('__price__','sum')).reset_index().sort_values('revenue', ascending=False).head(20)
            st.subheader("Top SKUs by revenue")
            st.dataframe(top)
            chart = alt.Chart(df.groupby('month').agg(rev=('__price__','sum')).reset_index()).mark_line(point=True).encode(x='month', y='rev')
            st.altair_chart(chart, use_container_width=True)

# helpers
def to_excel_bytes(df):
    import io
    with io.BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        return buf.getvalue()

# Footer
st.markdown("---")
st.caption("Full edition — includes fuzzy ID matching, greedy amount matching, bank-statement grouping, KPIs and P&L tools.")
