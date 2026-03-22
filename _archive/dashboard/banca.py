import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from google.cloud import bigquery

st.set_page_config(page_title="HotelOps — Incassi", layout="wide")
st.title("HotelOps — Incassi Bancari")

ENTRATA_TIPI = ["POS_ENTRATA", "CONTANTE_ENTRATA", "BONIFICO_ENTRATA", "PAYBYLINK"]
COLORI_CANALE = {
    "POS_ENTRATA":      "#4C9BE8",
    "BONIFICO_ENTRATA": "#2ECC71",
    "PAYBYLINK":        "#9B59B6",
    "CONTANTE_ENTRATA": "#F39C12",
}
COLORI_SOCIETA = {
    "INTUR": "#1A6FB5",
    "ORTI":  "#1A8A4A",
}

ANNO = str(date.today().year)


@st.cache_data(ttl=300)
def load(anno: str):
    client = bigquery.Client(project="hotelops-suite")
    return client.query(f"""
        SELECT
          FORMAT_DATE('%Y-%m', data_operazione) AS mese,
          data_operazione,
          societa_id, banca_id, macro_tipo, is_intercompany,
          descrizione, tipo_movimento,
          importo_netto, importo_credito
        FROM `hotelops-suite.hotelops.v_movimenti_classificati`
        WHERE EXTRACT(YEAR FROM data_operazione) = {int(anno)}
        ORDER BY data_operazione
    """).to_dataframe()


df = load(ANNO)

# --- Sidebar ---
st.sidebar.header("Filtri")
societa  = st.sidebar.multiselect("Società",  sorted(df["societa_id"].unique()),  default=list(df["societa_id"].unique()))
banca    = st.sidebar.multiselect("Banca",    sorted(df["banca_id"].unique()),    default=list(df["banca_id"].unique()))
canali   = st.sidebar.multiselect("Canale",   sorted(df["macro_tipo"].unique()),  default=ENTRATA_TIPI)
escludi_ic = st.sidebar.checkbox("Escludi intercompany", value=True)

# --- Filter ---
mask = (
    df["societa_id"].isin(societa) &
    df["banca_id"].isin(banca)
)
if escludi_ic:
    mask &= ~df["is_intercompany"]

filtered = df[mask]
incassi = filtered[filtered["macro_tipo"].isin(canali)]

df_intur = incassi[incassi["societa_id"] == "INTUR"]
df_orti  = incassi[incassi["societa_id"] == "ORTI"]

# --- Scorecards ---
st.subheader(f"Totale incassi {ANNO}")
c1, c2, c3 = st.columns(3)

by_societa = incassi.groupby("societa_id")["importo_credito"].sum()
tot_intur = by_societa.get("INTUR", 0)
tot_orti  = by_societa.get("ORTI", 0)
tot_all   = by_societa.sum()

c1.metric("INTUR", f"€ {tot_intur:,.0f}")
c2.metric("ORTI",  f"€ {tot_orti:,.0f}")
c3.metric("Totale", f"€ {tot_all:,.0f}")

st.divider()

# --- Grafici per società ---
def grafico_incassi(df_soc: pd.DataFrame, titolo: str):
    agg = (
        df_soc.groupby(["mese", "macro_tipo"])["importo_credito"]
        .sum().reset_index()
        .sort_values("mese")
    )
    if agg.empty:
        st.info(f"Nessun dato per {titolo}")
        return
    fig = px.bar(
        agg, x="mese", y="importo_credito", color="macro_tipo",
        title=titolo, barmode="stack",
        color_discrete_map=COLORI_CANALE,
        labels={"importo_credito": "€", "mese": "", "macro_tipo": "Canale"},
    )
    fig.update_layout(legend_title_text="Canale", height=350)
    st.plotly_chart(fig, use_container_width=True)


col1, col2 = st.columns(2)
with col1:
    grafico_incassi(df_intur, "INTUR — Incassi per canale")
with col2:
    grafico_incassi(df_orti,  "ORTI — Incassi per canale")

st.divider()

# --- Cashflow netto mensile ---
st.subheader("Cashflow netto mensile (entrate - uscite)")
netto = (
    filtered.groupby(["mese", "societa_id"])["importo_netto"]
    .sum().reset_index().sort_values("mese")
)
fig_netto = px.bar(
    netto, x="mese", y="importo_netto", color="societa_id",
    barmode="group",
    labels={"importo_netto": "€ netto", "mese": "", "societa_id": "Società"},
    color_discrete_map=COLORI_SOCIETA,
)
fig_netto.update_layout(height=300)
st.plotly_chart(fig_netto, use_container_width=True)

st.divider()

# --- Tabella movimenti ---
st.subheader("Movimenti")
st.dataframe(
    filtered[["mese", "data_operazione", "societa_id", "banca_id",
              "macro_tipo", "descrizione", "importo_netto"]]
    .sort_values("data_operazione", ascending=False),
    use_container_width=True,
    height=400,
)
st.caption(f"{len(filtered):,} movimenti | netto totale € {filtered['importo_netto'].sum():,.2f}")
