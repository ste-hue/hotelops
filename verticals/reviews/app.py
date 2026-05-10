"""Reviews Dashboard — Streamlit app for guest review analysis."""

from __future__ import annotations


import pandas as pd
import plotly.express as px
import streamlit as st

from core import config as cfg

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


def main():
    st.set_page_config(
        page_title="Reviews Dashboard",
        page_icon="⭐",
        layout="wide",
        initial_sidebar_state="expanded",
    )

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

    if sentiment_filter != "Tutti":
        df = df[df["sentiment_nlp"] == sentiment_filter]

    # ── KPI Cards ────────────────────────────────────────────────────────────
    avg_score = df["punteggio_norm"].mean()
    n_total = len(df)
    n_negative = (df["punteggio_norm"] <= 6.0).sum()
    pct_neg = n_negative / n_total * 100 if n_total > 0 else 0

    # Worst platform
    by_plat = df.groupby("piattaforma")["punteggio_norm"].mean()
    worst_plat = by_plat.idxmin() if not by_plat.empty else "—"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Punteggio medio", f"{avg_score:.1f}/10")
    col2.metric("Review totali", n_total)
    col3.metric("% Negative", f"{pct_neg:.0f}%")
    col4.metric("Piattaforma peggiore", worst_plat)

    st.divider()

    # ── Trend Chart ──────────────────────────────────────────────────────────
    st.subheader("Trend punteggio medio mensile")
    df["mese"] = df["data_review"].dt.to_period("M").astype(str)
    monthly = df.groupby(["mese", "piattaforma"])["punteggio_norm"].mean().reset_index()
    if not monthly.empty:
        fig = px.line(
            monthly,
            x="mese",
            y="punteggio_norm",
            color="piattaforma",
            markers=True,
            labels={"punteggio_norm": "Media", "mese": "Mese"},
        )
        fig.update_layout(yaxis_range=[1, 10], height=350)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Category Breakdown ───────────────────────────────────────────────────
    st.subheader("Categorie")
    cat_counts = df["categoria_nlp"].value_counts().reset_index()
    cat_counts.columns = ["Categoria", "Count"]
    if not cat_counts.empty:
        fig2 = px.bar(
            cat_counts,
            x="Count",
            y="Categoria",
            orientation="h",
            color="Categoria",
        )
        fig2.update_layout(height=300, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

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


if __name__ == "__main__":
    main()
