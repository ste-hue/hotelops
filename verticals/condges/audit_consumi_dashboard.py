"""Audit consumi F&B per la direzione — Hotel Panorama.

Streamlit read-only che applica la canonical-transformation-matrix a 3 vertical
F&B (BREAKFAST / RISTORANTE / BAR). 6 layer per vertical: Ricavi → Consumi →
Coperti → KPI → Range industria → Alert.

Run: streamlit run verticals/condges/audit_consumi_dashboard.py
Spec: docs/superpowers/specs/2026-05-21-audit-consumi-fb-direzione-design.md
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

PROJECT = "hotelops-suite"
DATASET = "hotelops"
FORM_URL = "https://forms.gle/PLACEHOLDER"  # update dopo creazione Form via Apps Script

PAGES = [
    "🏠 Primer — Mental model",
    "🥐 B1 — Breakfast",
    "🍽️ B2 — Ristorante",
    "🍷 B3 — Bar / Beverage",
    "⚠️ Anomalie FYI",
    "📋 Recap + Form",
]


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    """BQ client singleton."""
    return bigquery.Client(project=PROJECT)


@st.cache_data(ttl=300)
def run_query(sql: str) -> pd.DataFrame:
    """Esegue query BQ con cache 5 min."""
    return get_bq_client().query(sql).to_dataframe()


def alert_color(value: float, target_lo: float, target_hi: float,
                warning_hi: float) -> str:
    """Ritorna colore semaforo per valore vs range.
    verde se nel target, giallo se warning, rosso se investigate.
    """
    if target_lo <= value <= target_hi:
        return "🟢"
    if target_hi < value <= warning_hi:
        return "🟡"
    return "🔴"


def main() -> None:
    st.set_page_config(
        page_title="Audit consumi F&B — Hotel Panorama",
        page_icon="🍴",
        layout="wide",
    )
    st.sidebar.title("🍴 Audit F&B")
    st.sidebar.markdown("**Hotel Panorama** — canonical-transformation-matrix")
    page = st.sidebar.radio("Naviga", PAGES, label_visibility="collapsed")
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "Dati live da BigQuery `hotelops-suite.hotelops`.\n\n"
        "Read-only. Risposte vanno nel Google Form (link in fondo)."
    )

    if page == PAGES[0]:
        render_primer()
    elif page == PAGES[1]:
        render_b1_breakfast()
    elif page == PAGES[2]:
        render_b2_ristorante()
    elif page == PAGES[3]:
        render_b3_bar()
    elif page == PAGES[4]:
        render_anomalie()
    elif page == PAGES[5]:
        render_recap()


def render_primer() -> None:
    st.title("🏠 Primer — Mental model")
    st.info("Pagina da implementare nel Task 2")


def render_b1_breakfast() -> None:
    st.title("🥐 B1 — Breakfast")
    st.info("Pagina da implementare nel Task 3")


def render_b2_ristorante() -> None:
    st.title("🍽️ B2 — Ristorante")
    st.info("Pagina da implementare nel Task 4")


def render_b3_bar() -> None:
    st.title("🍷 B3 — Bar / Beverage")
    st.info("Pagina da implementare nel Task 5")


def render_anomalie() -> None:
    st.title("⚠️ Anomalie FYI")
    st.info("Pagina da implementare nel Task 6")


def render_recap() -> None:
    st.title("📋 Recap + Form")
    st.info("Pagina da implementare nel Task 7")


if __name__ == "__main__":
    main()
