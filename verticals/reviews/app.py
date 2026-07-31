"""Reviews Dashboard — Streamlit app for guest review analysis."""

from __future__ import annotations

from urllib.parse import urlencode

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from core import config as cfg
from verticals.reviews.scan import build_scan, render_scan_html

PIATTAFORME = ["BOOKING", "TRIPADVISOR", "GOOGLE", "EXPEDIA", "TRIP"]
ANNI = [2025, 2026, 2027]
ANNO_DEFAULT = 2026
BUSINESS_UNITS = ["HOTEL", "RESIDENCE", "CVM", "LIDO"]

# Colore fisso per BU (palette categorica validata CVD, mai riassegnata dai filtri).
BU_TREND_COLORS = {
    "HOTEL": "#2a78d6",
    "RESIDENCE": "#008300",
    "CVM": "#e87ba4",
    "LIDO": "#eda100",
}
# Sotto questa soglia la media mensile è poco affidabile → marker vuoto.
LOW_SAMPLE_N = 3
# Peso del prior nella media smorzata: un mese domina solo con n >> SHRINK_M.
SHRINK_M = 10

MESI_LABELS = [
    "Gen",
    "Feb",
    "Mar",
    "Apr",
    "Mag",
    "Giu",
    "Lug",
    "Ago",
    "Set",
    "Ott",
    "Nov",
    "Dic",
]
# Coppia divergente per i delta YoY (validata CVD light+dark, script skill dataviz).
YOY_UP = "#2a78d6"
YOY_DOWN = "#c8452c"

# Modalità ?scan=full: solo lo scan, senza chrome hub/Streamlit.
# Sfondo allineato a --paper dello scan (light/dark come in scan.py).
_FULLSCREEN_CSS = """<style>
header[data-testid="stHeader"] {display: none;}
.block-container {padding: 0 !important; max-width: 100% !important;}
.stApp {background: #F2F5F4;}
@media (prefers-color-scheme: dark) {.stApp {background: #0E181C;}}
</style>"""


def parse_scan_params(params) -> tuple[int, list[str], str | None]:
    """Filtri (anno, piattaforme, bu) dai query param; malformati → default."""
    try:
        anno = int(params.get("anno", ""))
    except ValueError:
        anno = ANNO_DEFAULT
    if anno not in ANNI:
        anno = ANNO_DEFAULT
    piattaforme = [
        p for p in str(params.get("piattaforme", "")).split(",") if p in PIATTAFORME
    ] or list(PIATTAFORME)
    bu = params.get("bu")
    return anno, piattaforme, bu if bu in BUSINESS_UNITS else None


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


def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Media mensile di punteggio_norm per BU: (mese, business_unit_id, media, media_adj, n).

    Mesi senza review non producono righe (nessuna interpolazione).
    `media_adj` = media smorzata (empirical Bayes): i mesi a basso n vengono
    tirati verso la media della BU sul df in ingresso, peso del prior SHRINK_M.
    """
    cols = ["mese", "business_unit_id", "media", "media_adj", "n"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = (
        df.assign(mese=df["data_review"].dt.strftime("%Y-%m"))
        .groupby(["mese", "business_unit_id"], as_index=False)
        .agg(media=("punteggio_norm", "mean"), n=("punteggio_norm", "size"))
    )
    prior = out["business_unit_id"].map(
        df.groupby("business_unit_id")["punteggio_norm"].mean()
    )
    out["media_adj"] = (out["n"] * out["media"] + SHRINK_M * prior) / (
        out["n"] + SHRINK_M
    )
    return out.sort_values("mese", ignore_index=True)[cols]


def yoy_compare(df_cur: pd.DataFrame, df_prev: pd.DataFrame) -> dict:
    """Confronto YoY sui mesi confrontabili (gen..ultimo mese con review in df_cur).

    Ritorna ultimo_mese, kpi_cur/kpi_prev (n, media, neg) calcolati sui soli mesi
    confrontabili, e `mensile` (mese_num, media/n per anno, delta).
    """
    ultimo_mese = int(df_cur["data_review"].dt.month.max())

    def _agg(df):
        df = df[df["data_review"].dt.month <= ultimo_mese]
        mensile = (
            df.assign(mese_num=df["data_review"].dt.month)
            .groupby("mese_num")
            .agg(media=("punteggio_norm", "mean"), n=("punteggio_norm", "size"))
        )
        kpi = {
            "n": len(df),
            "media": df["punteggio_norm"].mean(),
            "neg": int((df["sentiment_nlp"] == "NEGATIVO").sum()),
        }
        return mensile, kpi

    mens_cur, kpi_cur = _agg(df_cur)
    mens_prev, kpi_prev = _agg(df_prev)
    mensile = (
        mens_cur.join(mens_prev, how="outer", lsuffix="_cur", rsuffix="_prev")
        .reset_index()
        .sort_values("mese_num", ignore_index=True)
    )
    mensile["delta"] = mensile["media_cur"] - mensile["media_prev"]
    return {
        "ultimo_mese": ultimo_mese,
        "kpi_cur": kpi_cur,
        "kpi_prev": kpi_prev,
        "mensile": mensile,
    }


def yoy_delta_figure(mensile: pd.DataFrame, anno: int) -> go.Figure:
    sub = mensile.dropna(subset=["delta"])
    fig = go.Figure(
        go.Bar(
            x=[MESI_LABELS[m - 1] for m in sub["mese_num"]],
            y=sub["delta"],
            marker_color=[YOY_UP if d >= 0 else YOY_DOWN for d in sub["delta"]],
            text=[f"{d:+.2f}" for d in sub["delta"]],
            textposition="outside",
            customdata=sub[["media_cur", "n_cur", "media_prev", "n_prev"]],
            hovertemplate=(
                f"%{{x}} · {anno}: %{{customdata[0]:.2f}} (%{{customdata[1]:.0f}} review)"
                f" · {anno - 1}: %{{customdata[2]:.2f}} (%{{customdata[3]:.0f}} review)"
                "<extra>Δ %{y:+.2f}</extra>"
            ),
        )
    )
    fig.update_layout(
        height=300,
        margin={"l": 60, "r": 20, "t": 10, "b": 40},
        yaxis={"title": f"Δ media vs {anno - 1}", "zeroline": True},
        xaxis={"type": "category"},
        showlegend=False,
    )
    return fig


def trend_figure(trend: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for bu, color in BU_TREND_COLORS.items():
        sub = trend[trend["business_unit_id"] == bu]
        if sub.empty:
            continue
        symbols = ["circle" if n >= LOW_SAMPLE_N else "circle-open" for n in sub["n"]]
        fig.add_trace(
            go.Scatter(
                x=sub["mese"],
                y=sub["media_adj"],
                name=bu,
                mode="lines+markers",
                line={"color": color, "width": 2},
                marker={
                    "symbol": symbols,
                    "size": 9,
                    "color": color,
                    "line": {"color": color, "width": 2},
                },
                customdata=sub[["media", "n"]],
                hovertemplate=(
                    "%{x} · punteggio %{y:.2f}/10"
                    " · media grezza %{customdata[0]:.2f}"
                    " · %{customdata[1]} review"
                    f"<extra>{bu}</extra>"
                ),
            )
        )
    fig.update_layout(
        height=340,
        margin={"l": 60, "r": 20, "t": 10, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        yaxis={"title": "media /10"},
        xaxis={"type": "category"},
    )
    return fig


def _render_scan_fullscreen():
    """Solo lo scan, a tutta finestra — filtri dai query param (?scan=full)."""
    anno, piattaforme, bu = parse_scan_params(st.query_params)
    st.markdown(_FULLSCREEN_CSS, unsafe_allow_html=True)
    with st.spinner("Caricamento reviews..."):
        df = load_reviews(anno, piattaforme, bu, _bq=get_bq())
    if df.empty:
        st.warning("Nessuna review trovata con questi filtri.")
        return
    scan = build_scan(df.to_dict("records"))
    components.html(render_scan_html(scan, anno), height=4300, scrolling=True)


def render():
    if st.query_params.get("scan") == "full":
        _render_scan_fullscreen()
        return

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⭐ Reviews Dashboard")
        anno = st.selectbox("Anno", ANNI, index=ANNI.index(ANNO_DEFAULT))
        piattaforme = st.multiselect("Piattaforme", PIATTAFORME, default=PIATTAFORME)
        bu = st.selectbox("Business Unit", ["Tutte", *BUSINESS_UNITS])
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
    fs_params = {"scan": "full", "anno": str(anno)}
    if piattaforme and set(piattaforme) != set(PIATTAFORME):
        fs_params["piattaforme"] = ",".join(piattaforme)
    if bu_filter:
        fs_params["bu"] = bu_filter
    st.link_button("↗ Apri a schermo intero", "?" + urlencode(fs_params))
    scan = build_scan(df.to_dict("records"))
    components.html(render_scan_html(scan, anno), height=4300, scrolling=True)

    st.divider()

    # ── Trend punteggio (pre-filtro sentiment, come lo scan) ─────────────────
    st.subheader("Trend punteggio")
    trend = monthly_trend(df)
    if trend["mese"].nunique() < 2:
        st.caption("Serve più di un mese di review per leggere il trend.")
    st.plotly_chart(trend_figure(trend), use_container_width=True)
    st.caption(
        f"Punteggio smorzato: i mesi con poche review sono riportati verso la "
        f"media della BU (la media grezza è nel hover). "
        f"Marker vuoto = meno di {LOW_SAMPLE_N} review nel mese."
    )

    st.divider()

    # ── Confronto YoY (pre-filtro sentiment, come lo scan) ───────────────────
    st.subheader(f"Confronto con il {anno - 1}")
    with st.spinner(f"Caricamento reviews {anno - 1}..."):
        df_prev = load_reviews(anno - 1, piattaforme or None, bu_filter, _bq=bq)
    if df_prev.empty:
        st.caption(f"Nessuna review nel {anno - 1} con questi filtri.")
    else:
        yoy = yoy_compare(df, df_prev)
        kc, kp = yoy["kpi_cur"], yoy["kpi_prev"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Review", kc["n"], delta=kc["n"] - kp["n"])
        c2.metric(
            "Media /10", f"{kc['media']:.2f}", delta=f"{kc['media'] - kp['media']:+.2f}"
        )
        c3.metric(
            "Negative", kc["neg"], delta=kc["neg"] - kp["neg"], delta_color="inverse"
        )
        st.plotly_chart(
            yoy_delta_figure(yoy["mensile"], anno), use_container_width=True
        )
        st.caption(
            f"A parità di mesi (Gen–{MESI_LABELS[yoy['ultimo_mese'] - 1]}); "
            f"l'ultimo mese può essere ancora parziale. "
            f"Barre solo per i mesi con review in entrambi gli anni."
        )

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
