import streamlit as st
import pandas as pd
from google.cloud import bigquery

st.set_page_config(page_title="HotelOps — Banca", layout="wide")
st.title("HotelOps — Movimenti Bancari")

@st.cache_data(ttl=300)
def load():
    client = bigquery.Client(project="hotelops-suite")
    return client.query("""
        SELECT
          FORMAT_DATE('%Y-%m', data_operazione) AS mese,
          data_operazione,
          societa_id, banca_id, macro_tipo, is_intercompany,
          descrizione, tipo_movimento,
          importo_netto, importo_debito, importo_credito
        FROM hotelops.v_movimenti_classificati
        ORDER BY data_operazione
    """).to_dataframe()

df = load()

# --- Sidebar filters ---
st.sidebar.header("Filtri")

societa = st.sidebar.multiselect("Società", df["societa_id"].unique(), default=list(df["societa_id"].unique()))
banca = st.sidebar.multiselect("Banca", df["banca_id"].unique(), default=list(df["banca_id"].unique()))
macro = st.sidebar.multiselect("Tipo", df["macro_tipo"].unique(), default=list(df["macro_tipo"].unique()))
escludi_intercompany = st.sidebar.checkbox("Escludi intercompany", value=True)

anni = sorted(df["mese"].str[:4].unique())
anno_range = st.sidebar.select_slider("Anno", options=anni, value=(anni[0], anni[-1]))

# --- Apply filters ---
mask = (
    df["societa_id"].isin(societa) &
    df["banca_id"].isin(banca) &
    df["macro_tipo"].isin(macro) &
    (df["mese"].str[:4] >= anno_range[0]) &
    (df["mese"].str[:4] <= anno_range[1])
)
if escludi_intercompany:
    mask &= ~df["is_intercompany"]

filtered = df[mask]

# --- Monthly aggregation ---
mensile = (
    filtered.groupby(["mese", "societa_id"])
    .agg(
        entrate=("importo_netto", lambda x: x[x > 0].sum()),
        uscite=("importo_netto", lambda x: x[x < 0].abs().sum()),
        netto=("importo_netto", "sum"),
    )
    .reset_index()
    .sort_values("mese")
)

# --- Entrate per tipo ---
st.subheader("Entrate per tipo — mese per mese")
entrate_tipo = (
    filtered[filtered["macro_tipo"].isin(["POS_ENTRATA","CONTANTE_ENTRATA","BONIFICO_ENTRATA","PAYBYLINK"])]
    .groupby(["mese", "macro_tipo"])["importo_credito"]
    .sum().reset_index()
)
pivot_et = entrate_tipo.pivot(index="mese", columns="macro_tipo", values="importo_credito").fillna(0)
st.bar_chart(pivot_et)

# --- Netto per societa ---
st.subheader("Netto mensile per società (entrate - uscite)")
pivot_n = mensile.pivot(index="mese", columns="societa_id", values="netto").fillna(0)
st.bar_chart(pivot_n)

# --- Detail table ---
st.subheader("Movimenti")
st.dataframe(
    filtered[["mese","societa_id","banca_id","macro_tipo","descrizione","importo_netto"]]
    .sort_values("mese", ascending=False),
    use_container_width=True,
    height=400,
)

st.caption(f"{len(filtered):,} movimenti | {filtered['importo_netto'].sum():,.2f} EUR netto totale")
