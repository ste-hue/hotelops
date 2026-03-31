"""Tesoreria Streamlit app — wires together parse_pf, bq_data, cashflow, export_excel.

Run:
    streamlit run condges/tesoreria.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on sys.path when run via `streamlit run condges/tesoreria.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from condges.bq_data import load_budget, load_consuntivo, load_voci
from condges.cashflow import project_cashflow
from condges.export_excel import generate_tesoreria_excel
from condges.parse_pf import PFData, ScadenzarioData, parse_pf, parse_scadenzario

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tesoreria", layout="wide")

MESI_NOMI = [
    "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
    "Lug", "Ago", "Set", "Ott", "Nov", "Dic",
]

BANKS_BY_SOCIETA: dict[str, list[str]] = {
    "ORTI": ["MPS", "Intesa", "MPS_KROSS"],
    "INTUR": ["Sella", "MPS", "Intesa", "BCP"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_day_prev_month() -> date:
    today = date.today()
    first_of_month = today.replace(day=1)
    return first_of_month - timedelta(days=1)


def _fmt_eur(value: float) -> str:
    return f"€{value:,.0f}"


def _semaphore_emoji(saldo: float) -> str:
    if saldo < 0:
        return "🔴"
    if saldo <= 50_000:
        return "🟡"
    return "🟢"


def _match_banca_saldo(pf_saldi: dict[str, float], bank_name: str) -> float:
    """Try to find a matching saldo from pf_saldi for a given bank_name.

    PF file stores saldi as 'Saldo MPS', 'Saldo Intesa', etc.
    """
    bank_lower = bank_name.lower()
    for label, amount in pf_saldi.items():
        label_lower = label.lower()
        if bank_lower in label_lower or label_lower in bank_lower:
            return amount
    return 0.0


def _build_cashflow_df(cashflow_rows) -> pd.DataFrame:
    """Convert CashflowRow list to a display-friendly DataFrame."""
    return pd.DataFrame(
        [
            {
                "Mese": MESI_NOMI[r.mese - 1],
                "Saldo Inizio": r.saldo_iniziale,
                "+ Entrate": r.entrate,
                "- Uscite PF": r.uscite_pf,
                "- Fornitori": r.uscite_fornitori,
                "Netto": r.netto,
                "Saldo Fine": r.saldo_fine,
                "Stato": r.stato,
            }
            for r in cashflow_rows
        ]
    )


def _style_cashflow(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Apply color styling to the cashflow dataframe."""
    eur_cols = ["Saldo Inizio", "+ Entrate", "- Uscite PF", "- Fornitori", "Netto", "Saldo Fine"]

    def color_stato(val: str) -> str:
        if val == "PERICOLO":
            return "background-color: #FFC7CE; color: #9C0006; font-weight: bold"
        if val == "ATTENZIONE":
            return "background-color: #FFEB9C; color: #7F6000; font-weight: bold"
        return "background-color: #C6EFCE; color: #276221; font-weight: bold"

    def color_saldo_fine(val) -> str:
        if isinstance(val, (int, float)) and val < 0:
            return "color: #CC0000; font-weight: bold"
        return ""

    styler = df.style

    # EUR formatting for numeric columns
    fmt = {col: "€{:,.0f}" for col in eur_cols}
    styler = styler.format(fmt)

    # Color Stato column
    styler = styler.applymap(color_stato, subset=["Stato"])

    # Color negative saldo fine
    styler = styler.applymap(color_saldo_fine, subset=["Saldo Fine"])

    return styler


def _cashflow_chart(cashflow_rows) -> go.Figure:
    """Build a combined bar+line chart for the cashflow projection."""
    mesi = [MESI_NOMI[r.mese - 1] for r in cashflow_rows]
    entrate = [r.entrate for r in cashflow_rows]
    uscite = [r.uscite_pf + r.uscite_fornitori for r in cashflow_rows]
    saldi = [r.saldo_fine for r in cashflow_rows]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="Entrate",
        x=mesi,
        y=entrate,
        marker_color="#27AE60",
        opacity=0.85,
    ))

    fig.add_trace(go.Bar(
        name="Uscite",
        x=mesi,
        y=[-u for u in uscite],
        marker_color="#E74C3C",
        opacity=0.85,
    ))

    fig.add_trace(go.Scatter(
        name="Saldo Fine",
        x=mesi,
        y=saldi,
        mode="lines+markers",
        line=dict(color="#2980B9", width=2),
        marker=dict(size=7),
        yaxis="y2",
    ))

    # Red zone below 0
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="#CC0000",
        opacity=0.5,
        annotation_text="Zero",
        annotation_position="bottom right",
    )

    fig.update_layout(
        barmode="relative",
        xaxis_title="Mese",
        yaxis_title="Flussi (€)",
        yaxis2=dict(title="Saldo (€)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.05),
        height=380,
        margin=dict(l=40, r=40, t=30, b=40),
    )

    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> tuple[int, PFData | None, str, date, dict[str, float], ScadenzarioData | None]:
    """Render sidebar controls. Returns (anno, pf_data, societa, data_saldo, saldi_banca, scad_data)."""
    with st.sidebar:
        st.title("⚙️ Parametri")

        anno = st.number_input("Anno", min_value=2020, max_value=2035, value=2026, step=1)

        st.divider()
        st.subheader("Piano Finanziario")
        pf_file = st.file_uploader("Carica PF Excel", type=["xlsx"], key="pf_uploader")

        pf_data: PFData | None = None
        if pf_file is not None:
            try:
                pf_data = parse_pf(pf_file.read())
                st.success(
                    f"✅ {pf_data.societa} — {len(pf_data.voci)} voci"
                )
                if pf_data.warnings:
                    with st.expander(f"⚠️ {len(pf_data.warnings)} avvisi"):
                        for w in pf_data.warnings:
                            st.warning(w)
            except Exception as exc:
                st.error(f"Errore parsing PF: {exc}")

        st.divider()
        st.subheader("Società")
        default_societa = pf_data.societa if pf_data and pf_data.societa in ("ORTI", "INTUR") else "ORTI"
        societa = st.selectbox("Società", ["ORTI", "INTUR"], index=["ORTI", "INTUR"].index(default_societa))

        st.divider()
        st.subheader("Saldi Banca")
        data_saldo = st.date_input("Data saldo", value=_last_day_prev_month())

        banks = BANKS_BY_SOCIETA[societa]
        saldi_banca: dict[str, float] = {}
        for bank in banks:
            default_val = 0.0
            if pf_data and pf_data.saldi_banca:
                default_val = _match_banca_saldo(pf_data.saldi_banca, bank)
            saldi_banca[bank] = float(
                st.number_input(
                    f"Saldo {bank} (€)",
                    value=default_val,
                    step=1000.0,
                    format="%.0f",
                    key=f"saldo_{bank}",
                )
            )

        totale_saldo = sum(saldi_banca.values())
        st.metric("Totale saldi", _fmt_eur(totale_saldo))

        st.divider()
        st.subheader("Scadenzario Fornitori")
        scad_file = st.file_uploader("Carica Scadenzario (opzionale)", type=["xlsx"], key="scad_uploader")

        scad_data: ScadenzarioData | None = None
        if scad_file is not None:
            try:
                scad_data = parse_scadenzario(scad_file.read())
                st.success(f"✅ {len(scad_data.fornitori)} fornitori")
            except Exception as exc:
                st.error(f"Errore parsing Scadenzario: {exc}")

    return int(anno), pf_data, societa, data_saldo, saldi_banca, scad_data


# ---------------------------------------------------------------------------
# Main content sections
# ---------------------------------------------------------------------------

def render_header_metrics(
    saldi_banca: dict[str, float],
    pf_data: PFData | None,
    scad_data: ScadenzarioData | None,
) -> None:
    totale_saldo = sum(saldi_banca.values())
    emoji = _semaphore_emoji(totale_saldo)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            f"{emoji} Saldo Banca",
            _fmt_eur(totale_saldo),
        )
    with col2:
        n_voci = len(pf_data.voci) if pf_data else 0
        st.metric("Voci PF", str(n_voci))
    with col3:
        if scad_data:
            n_forn = len(scad_data.fornitori)
            scaduto = scad_data.scaduto_totale
            st.metric("Fornitori", n_forn, delta=f"scaduto {_fmt_eur(scaduto)}", delta_color="inverse")
        else:
            st.metric("Fornitori", "—")


def render_cashflow_section(
    pf_data: PFData,
    voci_data: list[dict],
    saldi_banca: dict[str, float],
    scad_data: ScadenzarioData | None,
) -> list:
    """Render the cashflow projection section. Returns cashflow_rows."""
    st.header("Proiezione Cashflow")

    # Build per-mese totals from PF voci_data
    entrate_per_mese: dict[int, float] = {}
    uscite_per_mese: dict[int, float] = {}
    for row in voci_data:
        m = row["mese"]
        if row["sezione"] == "ENTRATE":
            entrate_per_mese[m] = entrate_per_mese.get(m, 0.0) + row["previsione"]
        else:
            uscite_per_mese[m] = uscite_per_mese.get(m, 0.0) + row["previsione"]

    fornitori_per_mese: dict[int, float] = {}
    if scad_data:
        fornitori_per_mese = {k: v for k, v in scad_data.totale_per_mese.items()}

    saldo_iniziale = sum(saldi_banca.values())
    mese_corrente = date.today().month

    cashflow_rows = project_cashflow(
        saldo_iniziale=saldo_iniziale,
        mese_inizio=mese_corrente,
        entrate_per_mese=entrate_per_mese,
        uscite_per_mese=uscite_per_mese,
        fornitori_per_mese=fornitori_per_mese,
        mese_fine=12,
    )

    if cashflow_rows:
        df_cf = _build_cashflow_df(cashflow_rows)
        styled = _style_cashflow(df_cf)
        st.dataframe(styled, hide_index=True, use_container_width=True)

        st.plotly_chart(_cashflow_chart(cashflow_rows), use_container_width=True)
    else:
        st.info("Nessun dato cashflow disponibile.")

    return cashflow_rows


def render_voci_section(
    voci_data: list[dict],
    df_voci: pd.DataFrame,
) -> None:
    """Render the voci PF detail section with expanders."""
    st.header("Voci Piano Finanziario")

    mese_corrente = date.today().month

    # Index voci_data for fast lookups: (voce_id, mese) -> row
    voci_index: dict[tuple[str, int], dict] = {}
    for row in voci_data:
        voci_index[(row["voce_id"], row["mese"])] = row

    current_sezione = None

    for _, voce_row in df_voci.iterrows():
        voce_id = voce_row["voce_id"]
        voce_label = voce_row.get("voce_label", voce_id)
        sezione = voce_row.get("sezione", "")
        ord_val = voce_row.get("ord", 0)

        # Section subheader on change
        if sezione != current_sezione:
            current_sezione = sezione
            st.subheader(f"{'📥' if sezione == 'ENTRATE' else '📤'} {sezione}")

        # Check if voce has any non-zero data
        has_data = any(
            (voci_index.get((voce_id, m), {}).get("previsione", 0) or 0) != 0
            or (voci_index.get((voce_id, m), {}).get("budget", 0) or 0) != 0
            or (voci_index.get((voce_id, m), {}).get("consuntivo", 0) or 0) != 0
            for m in range(1, 13)
        )
        if not has_data:
            continue

        with st.expander(f"{voce_label}"):
            rows_display = []
            for m in range(1, 13):
                data = voci_index.get((voce_id, m), {})
                prev = data.get("previsione", 0) or 0
                bud = data.get("budget", 0) or 0
                cons = data.get("consuntivo", 0) or 0

                row_dict: dict = {"Mese": MESI_NOMI[m - 1]}

                if m < mese_corrente:
                    # Closed month: show all + deltas
                    delta_prev = cons - prev
                    delta_bud = cons - bud
                    row_dict["Previsione"] = prev
                    row_dict["Budget"] = bud
                    row_dict["Consuntivo"] = cons
                    row_dict["Δ Prev"] = delta_prev
                    row_dict["Δ Budget"] = delta_bud
                else:
                    # Future month: show previsione + budget + delta P-B
                    delta_pb = prev - bud
                    row_dict["Previsione"] = prev
                    row_dict["Budget"] = bud
                    row_dict["Δ Prev-Budget"] = delta_pb

                rows_display.append(row_dict)

            df_voce = pd.DataFrame(rows_display)

            eur_cols = [c for c in df_voce.columns if c != "Mese"]
            fmt = {col: "€{:,.0f}" for col in eur_cols}

            def color_delta(val):
                if not isinstance(val, (int, float)):
                    return ""
                if val < 0:
                    return "color: #CC0000"
                if val > 0:
                    return "color: #276221"
                return ""

            delta_cols = [c for c in df_voce.columns if c.startswith("Δ")]
            styler = df_voce.style.format(fmt)
            if delta_cols:
                styler = styler.applymap(color_delta, subset=delta_cols)

            st.dataframe(styler, hide_index=True, use_container_width=True)


def render_fornitori_section(scad_data: ScadenzarioData) -> None:
    """Render the fornitori / scadenzario section."""
    st.header("Scadenzario Fornitori")

    if not scad_data.fornitori:
        st.info("Nessun fornitore trovato nel file.")
        return

    # Top 10 by totale
    sorted_forn = sorted(scad_data.fornitori, key=lambda r: r.get("totale", 0) or 0, reverse=True)
    top10 = sorted_forn[:10]

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Top 10 Fornitori")
        df_top = pd.DataFrame(
            [
                {
                    "Fornitore": f["fornitore"],
                    "Totale": f.get("totale", 0) or 0,
                    "Scaduto": f.get("scaduto", 0) or 0,
                }
                for f in top10
            ]
        )

        def color_scaduto(val):
            if isinstance(val, (int, float)) and val > 0:
                return "color: #CC0000; font-weight: bold"
            return ""

        styler = df_top.style.format({"Totale": "€{:,.0f}", "Scaduto": "€{:,.0f}"})
        styler = styler.applymap(color_scaduto, subset=["Scaduto"])
        st.dataframe(styler, hide_index=True, use_container_width=True)

    with col_right:
        st.subheader("Uscite per Mese")
        if scad_data.totale_per_mese:
            mesi_forn = sorted(scad_data.totale_per_mese.items())
            df_mesi = pd.DataFrame(
                [{"Mese": MESI_NOMI[m - 1], "Totale": v} for m, v in mesi_forn if v > 0]
            )
            if not df_mesi.empty:
                st.dataframe(
                    df_mesi.style.format({"Totale": "€{:,.0f}"}),
                    hide_index=True,
                    use_container_width=True,
                )


def render_download_button(
    societa: str,
    anno: int,
    cashflow_rows: list,
    voci_data: list[dict],
    saldi_banca: dict[str, float],
    scad_data: ScadenzarioData | None,
) -> None:
    st.divider()
    today_str = date.today().strftime("%Y%m%d")
    filename = f"Tesoreria_{societa}_{anno}_{today_str}.xlsx"

    with st.spinner("Generazione Excel..."):
        fornitori = scad_data.fornitori if scad_data else []
        buf = generate_tesoreria_excel(
            societa=societa,
            anno=anno,
            cashflow_rows=cashflow_rows,
            voci_data=voci_data,
            fornitori=fornitori,
            saldi_banca=saldi_banca,
        )

    st.download_button(
        label=f"📥 Scarica {filename}",
        data=buf,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def assemble_voci_data(
    pf_data: PFData,
    societa: str,
    anno: int,
    df_voci: pd.DataFrame,
) -> list[dict]:
    """Build unified voci_data list merging PF previsioni, budget, and consuntivo."""
    try:
        df_consuntivo = load_consuntivo(societa, anno)
    except Exception:
        df_consuntivo = pd.DataFrame(columns=["voce_id", "mese", "importo_consuntivo"])

    try:
        df_budget = load_budget(societa, anno)
    except Exception:
        df_budget = pd.DataFrame(columns=["voce_id", "mese", "importo_budget"])

    # Index consuntivo and budget for O(1) lookups
    cons_index: dict[tuple[str, int], float] = {}
    for _, row in df_consuntivo.iterrows():
        cons_index[(str(row["voce_id"]), int(row["mese"]))] = float(row["importo_consuntivo"])

    bud_index: dict[tuple[str, int], float] = {}
    for _, row in df_budget.iterrows():
        bud_index[(str(row["voce_id"]), int(row["mese"]))] = float(row["importo_budget"])

    # Filter voci by societa (societa_id IS NULL or matches)
    df_filtered = df_voci[
        df_voci["societa_id"].isna() | (df_voci["societa_id"] == societa)
    ].copy()
    df_filtered = df_filtered.sort_values("ord")

    voci_data: list[dict] = []

    for _, voce_row in df_filtered.iterrows():
        voce_id = voce_row["voce_id"]
        voce_label = voce_row.get("voce_label", voce_id)
        sezione = voce_row.get("sezione", "")
        categoria = voce_row.get("categoria", "")
        ord_val = voce_row.get("ord", 0)

        for mese in range(1, 13):
            prev = (
                pf_data.voci[voce_id].importi.get(mese, 0.0)
                if voce_id in pf_data.voci
                else 0.0
            )
            cons = cons_index.get((voce_id, mese), 0.0)
            bud = bud_index.get((voce_id, mese), 0.0)

            voci_data.append(
                {
                    "voce_id": voce_id,
                    "voce_label": voce_label,
                    "sezione": sezione,
                    "categoria": categoria,
                    "ord": ord_val,
                    "mese": mese,
                    "previsione": prev,
                    "budget": bud,
                    "consuntivo": cons,
                }
            )

    return voci_data


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    anno, pf_data, societa, data_saldo, saldi_banca, scad_data = render_sidebar()

    st.title(f"Tesoreria {societa} — {anno}")

    if pf_data is None:
        st.info("⬅️ Carica il Piano Finanziario dal pannello laterale per iniziare.")
        return

    # Load dimension data from BQ
    try:
        df_voci = load_voci()
    except Exception as exc:
        st.error(f"Errore caricamento voci da BigQuery: {exc}")
        df_voci = pd.DataFrame(
            columns=["voce_id", "voce_label", "sezione", "categoria", "ord", "societa_id"]
        )

    # Assemble unified voci_data
    with st.spinner("Caricamento dati da BigQuery..."):
        voci_data = assemble_voci_data(pf_data, societa, anno, df_voci)

    # ── Header metrics ──────────────────────────────────────────────────────
    render_header_metrics(saldi_banca, pf_data, scad_data)

    st.divider()

    # ── Cashflow projection ─────────────────────────────────────────────────
    cashflow_rows = render_cashflow_section(pf_data, voci_data, saldi_banca, scad_data)

    st.divider()

    # ── Voci detail ─────────────────────────────────────────────────────────
    render_voci_section(voci_data, df_voci)

    # ── Fornitori ───────────────────────────────────────────────────────────
    if scad_data:
        st.divider()
        render_fornitori_section(scad_data)

    # ── Download button ─────────────────────────────────────────────────────
    render_download_button(societa, anno, cashflow_rows, voci_data, saldi_banca, scad_data)


if __name__ == "__main__":
    main()
