"""Tesoreria Streamlit app — wires together parse_pf, bq_data, cashflow, export_excel.

Run:
    streamlit run condges/tesoreria.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

# Ensure project root is on sys.path when run via `streamlit run condges/tesoreria.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from condges.bq_data import load_bva, load_consuntivo, load_voci
from condges.cashflow import project_cashflow
from condges.export_excel import generate_tesoreria_excel
from condges.parse_pf import PFData, ScadenzarioData, parse_pf, parse_scadenzario
from condges.scadenze_parse import (
    parse_scadenze,
    partite_df_to_scadenzario_data,
    sintetica_list_to_scadenzario_data,
)
from condges.scadenzario_excel import parse_sintetica_scadenze

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

# Scadenzario upload: same helpers as app_scadenzario / parse_pf / scadenzario_excel
SCAD_TIPO_LABELS: dict[str, str] = {
    "riepilogo": "Riepilogo (tabella con intestazioni mese)",
    "partite": "Esolver — partite (righe fattura / colonne fisse)",
    "sintetica": "Esolver — sintetica (col. A: codice + ragione sociale)",
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


_EUR_FMT = "€{:,.0f}"


def _eur_fmt(cols: list[str]) -> dict[str, str]:
    """Build a Styler format dict for EUR columns."""
    return {c: _EUR_FMT for c in cols}


def _color_delta(val) -> str:
    """Red for negative, green for positive. For Styler.map()."""
    if not isinstance(val, (int, float)):
        return ""
    if val < 0:
        return "color: #CC0000"
    if val > 0:
        return "color: #276221"
    return ""


def _color_scaduto(val) -> str:
    if isinstance(val, (int, float)) and val > 0:
        return "color: #CC0000; font-weight: bold"
    return ""


def _match_banca_saldo(pf_saldi: dict[str, float], bank_name: str) -> float:
    """Try to find a matching saldo from pf_saldi for a given bank_name.

    PF file stores saldi as 'Saldo MPS', 'Saldo Intesa', etc.
    Matches bank_name against labels; requires the label to cover all words
    in the bank name (or vice versa as exact match) to avoid 'MPS' bleeding
    into 'MPS_KROSS'.
    """
    # Normalize: MPS_KROSS -> ["mps", "kross"], MPS -> ["mps"]
    bank_words = set(bank_name.lower().replace("_", " ").split())
    for label, amount in pf_saldi.items():
        label_words = set(label.lower().split())
        # All bank words must appear in the label (or all label words = bank words)
        if bank_words <= label_words:
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

    styler = styler.format(_eur_fmt(eur_cols))

    # Color Stato column
    styler = styler.map(color_stato, subset=["Stato"])

    # Color negative saldo fine
    styler = styler.map(color_saldo_fine, subset=["Saldo Fine"])

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
                # Push parsed saldi into session_state so number_inputs pick them up
                if pf_data.saldi_banca:
                    for bank in BANKS_BY_SOCIETA.get(pf_data.societa, []):
                        matched = _match_banca_saldo(pf_data.saldi_banca, bank)
                        if matched != 0.0:
                            st.session_state[f"saldo_{bank}"] = matched
            except Exception as exc:
                st.error(f"Errore parsing PF: {exc}")

        st.divider()
        st.subheader("Società")
        default_societa = pf_data.societa if pf_data and pf_data.societa in ("ORTI", "INTUR") else "ORTI"
        societa = st.selectbox("Società", ["ORTI", "INTUR"], index=["ORTI", "INTUR"].index(default_societa))

        st.divider()
        st.subheader("Saldi Banca")
        # Date + saldi amounts on the PF sheet refer to the same cut-over (e.g. file
        # "… aprile …" often carries saldi al 31/03). Reset picker when a different PF is uploaded.
        _pf_stable_key = "none"
        if pf_file is not None:
            _pf_stable_key = f"{pf_file.name}_{pf_file.size}"
        _default_data_saldo = _last_day_prev_month()
        if pf_data and pf_data.data_saldo:
            _default_data_saldo = pf_data.data_saldo
        data_saldo = st.date_input(
            "Data saldo (riferimento saldi banca)",
            value=_default_data_saldo,
            key=f"data_saldo_{_pf_stable_key}",
            help="Di norma è la data letta dal foglio Piano Finanziario (cut-off dei saldi). "
            "Il nome del file (es. lavorazione aprile) può essere sul mese dopo quella data.",
        )
        if pf_data and pf_data.data_saldo and data_saldo != pf_data.data_saldo:
            st.caption(
                f"Nel PF il parser ha trovato **{pf_data.data_saldo.strftime('%d/%m/%Y')}** — "
                "puoi allineare il selettore se serve."
            )

        banks = BANKS_BY_SOCIETA[societa]
        saldi_banca: dict[str, float] = {}
        for bank in banks:
            saldi_banca[bank] = float(
                st.number_input(
                    f"Saldo {bank} (€)",
                    value=0.0,
                    step=1000.0,
                    format="%.0f",
                    key=f"saldo_{bank}",
                )
            )

        totale_saldo = sum(saldi_banca.values())
        st.metric("Totale saldi", _fmt_eur(totale_saldo))

        st.divider()
        st.subheader("Scadenzario Fornitori")
        scad_tipo = st.radio(
            "Formato file",
            options=list(SCAD_TIPO_LABELS.keys()),
            format_func=lambda k: SCAD_TIPO_LABELS[k],
            horizontal=True,
            key="scad_tipo",
        )
        scad_file = st.file_uploader("Carica Scadenzario (opzionale)", type=["xlsx"], key="scad_uploader")

        scad_data: ScadenzarioData | None = None
        if scad_file is not None:
            raw = scad_file.getvalue()
            try:
                if scad_tipo == "riepilogo":
                    scad_data = parse_scadenzario(raw)
                elif scad_tipo == "partite":
                    df_scad, bucket_months = parse_scadenze(BytesIO(raw))
                    scad_data = partite_df_to_scadenzario_data(df_scad, bucket_months)
                else:
                    suppliers, bucket_months = parse_sintetica_scadenze(BytesIO(raw))
                    scad_data = sintetica_list_to_scadenzario_data(suppliers, bucket_months)
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
        fornitori_per_mese = scad_data.totale_per_mese

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

        # Section subheader on change
        if sezione != current_sezione:
            current_sezione = sezione
            st.subheader(f"{'📥' if sezione == 'ENTRATE' else '📤'} {sezione}")

        # Check if voce has any non-zero data
        has_data = any(
            (voci_index.get((voce_id, m), {}).get("previsione", 0) or 0) != 0
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
                cons = data.get("consuntivo", 0) or 0

                row_dict: dict = {"Mese": MESI_NOMI[m - 1]}
                row_dict["Previsione"] = prev

                if m < mese_corrente:
                    # Closed month: previsione vs consuntivo
                    row_dict["Consuntivo"] = cons
                    row_dict["Δ"] = cons - prev

                rows_display.append(row_dict)

            df_voce = pd.DataFrame(rows_display)

            eur_cols = [c for c in df_voce.columns if c != "Mese"]
            fmt = _eur_fmt(eur_cols)

            delta_cols = [c for c in df_voce.columns if c.startswith("Δ")]
            styler = df_voce.style.format(fmt)
            if delta_cols:
                styler = styler.map(_color_delta, subset=delta_cols)

            st.dataframe(styler, hide_index=True, use_container_width=True)


def render_fornitori_section(scad_data: ScadenzarioData) -> None:
    """Render the fornitori / scadenzario section."""
    st.header("Scadenzario Fornitori")

    if not scad_data.fornitori:
        st.info("Nessun fornitore trovato nel file.")
        return

    # Detect which months have data
    all_mesi = sorted(scad_data.totale_per_mese.keys())

    # Summary: totale per mese
    st.subheader("Uscite Fornitori per Mese")
    if scad_data.totale_per_mese:
        mesi_forn = sorted(scad_data.totale_per_mese.items())
        summary_row = {"Voce": "TOTALE FORNITORI"}
        for m, v in mesi_forn:
            summary_row[MESI_NOMI[m - 1]] = v
        summary_row["Totale"] = sum(v for _, v in mesi_forn)
        summary_row["Scaduto"] = scad_data.scaduto_totale
        df_summary = pd.DataFrame([summary_row])
        eur_cols = [c for c in df_summary.columns if c != "Voce"]
        fmt = _eur_fmt(eur_cols)
        st.dataframe(df_summary.style.format(fmt), hide_index=True, use_container_width=True)

    st.divider()

    # Full table: all fornitori x mesi
    sorted_forn = sorted(scad_data.fornitori, key=lambda r: r.get("totale", 0) or 0, reverse=True)

    rows_display = []
    for f in sorted_forn:
        totale = f.get("totale", 0) or 0
        scaduto = f.get("scaduto", 0) or 0
        if abs(totale) < 1 and abs(scaduto) < 1:
            continue
        row = {"Fornitore": f["fornitore"]}
        for m in all_mesi:
            row[MESI_NOMI[m - 1]] = f.get(f"mese_{m}", 0) or 0
        row["Totale"] = totale
        row["Scaduto"] = scaduto
        rows_display.append(row)

    if rows_display:
        df_forn = pd.DataFrame(rows_display)
        eur_cols = [c for c in df_forn.columns if c != "Fornitore"]
        fmt = _eur_fmt(eur_cols)

        styler = df_forn.style.format(fmt)
        if "Scaduto" in df_forn.columns:
            styler = styler.map(_color_scaduto, subset=["Scaduto"])
        st.dataframe(styler, hide_index=True, use_container_width=True)


def render_bva_section(societa: str, anno: int) -> None:
    """Render Budget vs Consuntivo tab — monthly grid per codice conto."""
    st.header("Budget vs Consuntivo")

    mese_corrente = date.today().month

    with st.spinner("Caricamento BvA da BigQuery..."):
        try:
            df_bva = load_bva(societa, anno)
        except Exception as exc:
            st.error(f"Errore caricamento BvA: {exc}")
            return

    if df_bva.empty:
        st.info("Nessun dato BvA disponibile.")
        return

    # Filter to months with data (up to current month)
    df_bva = df_bva[df_bva["mese"] <= mese_corrente]

    # Pivot: one row per conto, columns = mesi
    conti = (
        df_bva.groupby(["codice_conto_display", "descrizione", "categoria_ce"])
        .agg({"budget": "sum", "consuntivo": "sum", "delta": "sum"})
        .reset_index()
        .sort_values("delta", key=abs, ascending=False)
    )

    # Summary metrics
    tot_budget = df_bva["budget"].sum()
    tot_consuntivo = df_bva["consuntivo"].sum()
    tot_delta = tot_consuntivo - tot_budget

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Budget YTD", _fmt_eur(tot_budget))
    with col2:
        st.metric("Consuntivo YTD", _fmt_eur(tot_consuntivo))
    with col3:
        st.metric("Delta", _fmt_eur(tot_delta), delta=f"{tot_delta/tot_budget*100:.1f}%" if tot_budget else None)

    st.divider()

    # Group by categoria_ce
    categorie = df_bva["categoria_ce"].dropna().unique()
    for cat in sorted(categorie):
        cat_conti = conti[conti["categoria_ce"] == cat].copy()
        if cat_conti.empty:
            continue

        cat_budget = cat_conti["budget"].sum()
        cat_consuntivo = cat_conti["consuntivo"].sum()
        cat_delta = cat_consuntivo - cat_budget

        with st.expander(
            f"{'📥' if 'Ricav' in str(cat) else '📤'} {cat} — "
            f"Budget {_fmt_eur(cat_budget)} | Consuntivo {_fmt_eur(cat_consuntivo)} | "
            f"Δ {_fmt_eur(cat_delta)}"
        ):
            # For each conto in this category, show monthly breakdown
            cat_df = df_bva[df_bva["categoria_ce"] == cat]
            conto_ids = cat_conti.sort_values("delta", key=abs, ascending=False)["codice_conto_display"].tolist()

            for conto_id in conto_ids:
                conto_rows = cat_df[cat_df["codice_conto_display"] == conto_id]
                if conto_rows.empty:
                    continue

                desc = conto_rows["descrizione"].iloc[0] or conto_id
                conto_budget = conto_rows["budget"].sum()
                conto_cons = conto_rows["consuntivo"].sum()
                conto_delta = conto_cons - conto_budget

                # Skip if both are zero
                if abs(conto_budget) < 1 and abs(conto_cons) < 1:
                    continue

                st.markdown(f"**{conto_id}** — {desc}")

                rows_display = []
                for m in range(1, mese_corrente + 1):
                    m_data = conto_rows[conto_rows["mese"] == m]
                    bud = float(m_data["budget"].sum()) if not m_data.empty else 0.0
                    cons = float(m_data["consuntivo"].sum()) if not m_data.empty else 0.0
                    rows_display.append({
                        "Mese": MESI_NOMI[m - 1],
                        "Budget": bud,
                        "Consuntivo": cons,
                        "Delta": cons - bud,
                    })

                # Add totale row
                rows_display.append({
                    "Mese": "TOTALE",
                    "Budget": conto_budget,
                    "Consuntivo": conto_cons,
                    "Delta": conto_delta,
                })

                df_display = pd.DataFrame(rows_display)
                eur_cols = ["Budget", "Consuntivo", "Delta"]
                fmt = _eur_fmt(eur_cols)

                styler = df_display.style.format(fmt)
                styler = styler.map(_color_delta, subset=["Delta"])

                st.dataframe(styler, hide_index=True, use_container_width=True)

    # Show unmatched conti (no categoria_ce)
    unmatched = conti[conti["categoria_ce"].isna()]
    if not unmatched.empty and (unmatched["budget"].abs().sum() > 100 or unmatched["consuntivo"].abs().sum() > 100):
        with st.expander(f"❓ Non categorizzati ({len(unmatched)} conti)"):
            df_um = unmatched[["codice_conto_display", "descrizione", "budget", "consuntivo", "delta"]].copy()
            df_um.columns = ["Codice", "Descrizione", "Budget", "Consuntivo", "Delta"]
            fmt = _eur_fmt(["Budget", "Consuntivo", "Delta"])
            st.dataframe(df_um.style.format(fmt), hide_index=True, use_container_width=True)


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
    """Build unified voci_data list merging PF previsioni and consuntivo."""
    try:
        df_consuntivo = load_consuntivo(societa, anno)
    except Exception:
        df_consuntivo = pd.DataFrame(columns=["voce_id", "mese", "importo_consuntivo"])

    # Index consuntivo for O(1) lookups
    cons_index: dict[tuple[str, int], float] = {}
    for _, row in df_consuntivo.iterrows():
        cons_index[(str(row["voce_id"]), int(row["mese"]))] = float(row["importo_consuntivo"])

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

            voci_data.append(
                {
                    "voce_id": voce_id,
                    "voce_label": voce_label,
                    "sezione": sezione,
                    "categoria": categoria,
                    "ord": ord_val,
                    "mese": mese,
                    "previsione": prev,
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

    tab_cassa, tab_bva = st.tabs(["💰 Cassa (Rosa)", "📊 Budget vs Consuntivo"])

    # ── Tab 1: Cassa ────────────────────────────────────────────────────────
    with tab_cassa:
        if pf_data is None:
            st.info("⬅️ Carica il Piano Finanziario dal pannello laterale per iniziare.")
        else:
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

            render_header_metrics(saldi_banca, pf_data, scad_data)
            st.divider()
            cashflow_rows = render_cashflow_section(pf_data, voci_data, saldi_banca, scad_data)
            st.divider()
            render_voci_section(voci_data, df_voci)

            if scad_data:
                st.divider()
                render_fornitori_section(scad_data)

            render_download_button(societa, anno, cashflow_rows, voci_data, saldi_banca, scad_data)

    # ── Tab 2: BvA ──────────────────────────────────────────────────────────
    with tab_bva:
        render_bva_section(societa, anno)


if __name__ == "__main__":
    main()
