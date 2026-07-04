"""Reviews Dashboard — Streamlit app for guest review analysis."""

from __future__ import annotations


import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import config as cfg
from verticals.reviews.scan import build_scan, render_scan_html

PIATTAFORME = ["BOOKING", "TRIPADVISOR", "GOOGLE", "EXPEDIA", "TRIP"]


@st.cache_resource
def get_bq():
    from core.bq.client import get_client

    return get_client()


@st.cache_data(ttl=300, show_spinner=False)
def load_reviews(
    anno: int,
    piattaforme: list[str] | None = None,
    bu: str | None = None,
    _bq=None,
) -> pd.DataFrame:
    bq = _bq or get_bq()
    filters = [f"EXTRACT(YEAR FROM PARSE_DATE('%Y-%m-%d', data_review)) = {anno}"]
    if piattaforme:
        plist = ", ".join(f"'{p}'" for p in piattaforme)
        filters.append(f"piattaforma IN ({plist})")
    if bu:
        filters.append(f"business_unit_id = '{bu}'")

    where = " AND ".join(filters)
    sql = f"""
    SELECT *
    FROM `{cfg.F_REVIEWS}`
    WHERE {where}
    ORDER BY data_review DESC
    """
    df = bq.query(sql).to_dataframe()
    if "data_review" in df.columns:
        df["data_review"] = pd.to_datetime(df["data_review"])
    return df


def render():
    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⭐ Reviews Dashboard")
        anno = st.selectbox("Anno", [2025, 2026, 2027], index=1)
        piattaforme = st.multiselect("Piattaforme", PIATTAFORME, default=PIATTAFORME)
        bu = st.selectbox(
            "Business Unit", ["Tutte", "HOTEL", "RESIDENCE", "CVM", "LIDO"]
        )
        sentiment_filter = st.selectbox(
            "Sentiment", ["Tutti", "POSITIVO", "NEGATIVO", "MISTO"]
        )

        st.divider()
        if st.button("🔄 Ricarica da BQ", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    bq = get_bq()
    bu_filter = bu if bu != "Tutte" else None

    with st.spinner("Caricamento reviews..."):
        df = load_reviews(anno, piattaforme or None, bu_filter, _bq=bq)

    if df.empty:
        st.warning("Nessuna review trovata con questi filtri.")
        return

    # ── Quadro generale (scan NLP) ───────────────────────────────────────────
    # Calcolato sulle righe filtrate anno/piattaforme/BU, PRIMA del filtro
    # sentiment: il corpus pos/neg è già distinto dentro lo scan.
    scan = build_scan(df.to_dict("records"))
    components.html(render_scan_html(scan, anno), height=4300, scrolling=True)

    st.divider()

    if sentiment_filter != "Tutti":
        df = df[df["sentiment_nlp"] == sentiment_filter]
        if df.empty:
            st.info("Nessuna review con questo sentiment.")
            return

    # ── Review Table ─────────────────────────────────────────────────────────
    st.subheader("Dettaglio review")

    display_cols = [
        "data_review",
        "piattaforma",
        "business_unit_id",
        "punteggio_norm",
        "categoria_nlp",
        "sentiment_nlp",
        "riassunto_nlp",
    ]
    available_cols = [c for c in display_cols if c in df.columns]
    show_df = df[available_cols].copy()
    show_df = show_df.rename(
        columns={
            "data_review": "Data",
            "piattaforma": "Piattaforma",
            "business_unit_id": "BU",
            "punteggio_norm": "Score",
            "categoria_nlp": "Categoria",
            "sentiment_nlp": "Sentiment",
            "riassunto_nlp": "Riassunto",
        }
    )

    st.dataframe(show_df, hide_index=True, use_container_width=True, height=400)

    # ── Drill-down ───────────────────────────────────────────────────────────
    if st.checkbox("Mostra testo completo review"):
        for _, row in df.head(10).iterrows():
            score = f"{row['punteggio_norm']:.0f}/10"
            label = f"{row['data_review'].date()} | {row['piattaforma']} | {score}"
            with st.expander(label):
                if row.get("testo_positivo"):
                    st.markdown(f"**Pro:** {row['testo_positivo']}")
                if row.get("testo_negativo"):
                    st.markdown(f"**Contro:** {row['testo_negativo']}")
                st.markdown(f"**Testo:** {row.get('testo', '')}")
                if row.get("url_review"):
                    st.markdown(f"[Vai alla review]({row['url_review']})")


def main():
    st.set_page_config(
        page_title="Reviews Dashboard",
        page_icon="⭐",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render()


if __name__ == "__main__":
    main()
