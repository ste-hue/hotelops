"""Pagina Revenue — booking curve & pace (read-only su v_booking_curve).

Spec: docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md
Metodologia: vault concepts/BOOKING_PACE_E_BASI (batteria / ADR marginale /
ADR richiesto). NON è un motore di pricing: lente + loop umano settimanale.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client
from core.config import DATASET, PROJECT

# ── palette (dataviz reference instance — ruoli, non hex sparsi) ─────────────
BLUE = "#2a78d6"  # slot-1: emphasis + riempimento meter
GRAY_CTX = "#c3c2b7"  # de-enfasi (linee contesto)
GRAY_MUTED = "#898781"  # inchiostro muted (righe consuntivo)
STATUS_COLOR = {  # status riservati, sempre con icona+etichetta
    "TARGET_SCONTATO": "#0ca30c",  # good
    "SERVE_DOMANDA": "#fab219",  # warning
    "SERVE_REPRICING": "#ec835a",  # serious
}
STATUS_LABEL = {
    "CONSUNTIVO": "· consuntivo",
    "DATI_INSUFFICIENTI": "— dati insufficienti",
    "TARGET_RAGGIUNTO": "✓ target raggiunto",
    "TARGET_INCOERENTE": "≠ target incoerente",
    "NESSUN_CONFRONTO": "— nessun confronto",
    "TARGET_SCONTATO": "✓ target scontato",
    "SERVE_DOMANDA": "⚠ serve domanda",
    "SERVE_REPRICING": "⛔ serve repricing",
}


def verdetto(
    *,
    mese_consumato: bool,
    prima_foto: bool,
    pickup_notti: float | None,
    gap_target: float | None,
    gap_notti_target: float | None,
    adr_marginale: float | None,
    adr_richiesto: float | None,
) -> str:
    """Semantica del verdetto (spec §vista) — pura, testabile senza BQ.

    Stati preliminari in quest'ordine, poi le 3 zone richiesto-vs-marginale.
    """
    if mese_consumato:
        return "CONSUNTIVO"
    if prima_foto or pickup_notti is None or pickup_notti <= 0:
        return "DATI_INSUFFICIENTI"
    if gap_target is not None and gap_target <= 0:
        return "TARGET_RAGGIUNTO"
    if gap_notti_target is not None and gap_notti_target <= 0:
        return "TARGET_INCOERENTE"
    if adr_marginale is None or adr_richiesto is None:
        return "NESSUN_CONFRONTO"
    if adr_richiesto < 0.6 * adr_marginale:
        return "TARGET_SCONTATO"
    if adr_richiesto > adr_marginale:
        return "SERVE_REPRICING"
    return "SERVE_DOMANDA"


def _f(v) -> float | None:
    """NaN/NA pandas -> None (il verdetto ragiona su Optional)."""
    return None if v is None or pd.isna(v) else float(v)


@st.cache_data(ttl=300)
def load_curve() -> pd.DataFrame:
    sql = (
        f"SELECT * FROM `{PROJECT}.{DATASET}.v_booking_curve` "
        "ORDER BY business_unit_id, mese_soggiorno, snapshot_date"
    )
    df = get_client().query(sql).to_dataframe()
    for c in ("snapshot_date", "mese_soggiorno"):
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


_MESI = [
    "gen",
    "feb",
    "mar",
    "apr",
    "mag",
    "giu",
    "lug",
    "ago",
    "set",
    "ott",
    "nov",
    "dic",
]


def _mese_label(d) -> str:
    return f"{_MESI[d.month - 1]} {d.year}"


def render() -> None:
    st.title("📈 Revenue")
    st.caption(
        "Booking curve & pace — fotografie OTB che si accumulano · "
        "batteria / ADR marginale / ADR richiesto (base imponibile)"
    )
    df = load_curve()
    if df.empty:
        st.info("Nessuna fotografia OTB in `f_prenotazioni_otb`.")
        return

    bus = sorted(df["business_unit_id"].unique())
    bu = st.selectbox(
        "Business unit", bus, index=bus.index("HOTEL") if "HOTEL" in bus else 0
    )
    d = df[df["business_unit_id"] == bu]

    # ── freshness (stat tile) ────────────────────────────────────────────
    ultima = d["snapshot_date"].max()
    gg_fa = (pd.Timestamp.today().date() - ultima).days
    n_foto = d["snapshot_date"].nunique()
    c1, c2 = st.columns(2)
    c1.metric(
        "Ultima foto",
        ultima.strftime("%d/%m/%Y"),
        f"{gg_fa} giorni fa",
        delta_color="off",
    )
    c2.metric("Fotografie", n_foto)
    if gg_fa > 10:
        st.warning(
            "Foto più recente di oltre 10 giorni — manca l'export settimanale "
            '"Andamento Prenotazioni" (rituale: export → intake → promote).'
        )

    # ── tabella batteria (ultima foto) ───────────────────────────────────
    last = d[d["snapshot_date"] == ultima].sort_values("mese_soggiorno").copy()
    prime_foto = d.groupby("mese_soggiorno")["snapshot_date"].min()

    def _row_verdetto(r) -> str:
        stato = verdetto(
            mese_consumato=r["mese_soggiorno"] < ultima.replace(day=1),
            prima_foto=prime_foto[r["mese_soggiorno"]] == r["snapshot_date"],
            pickup_notti=_f(r["pickup_notti"]),
            gap_target=_f(r["gap_target"]),
            gap_notti_target=_f(r["gap_notti_target"]),
            adr_marginale=_f(r["adr_marginale"]),
            adr_richiesto=_f(r["adr_richiesto"]),
        )
        return STATUS_LABEL[stato]

    show = pd.DataFrame(
        {
            "Mese": last["mese_soggiorno"].map(_mese_label),
            "Batteria": last["saturazione_pct"].clip(upper=1.0),
            "Sat. %": (last["saturazione_pct"] * 100).round(1),
            "OTB notti": last["otb_notti"],
            "OTB €": last["otb_imponibile"].round(0),
            "Pickup €/gg": last["pickup_eur_gg"].round(0),
            "ADR medio": last["otb_adr"].round(0),
            "ADR marginale": last["adr_marginale"].round(0),
            "ADR richiesto": last["adr_richiesto"].round(0),
            "Gap € target": last["gap_target"].round(0),
            "Verdetto": last.apply(_row_verdetto, axis=1),
        }
    )
    _label_color = {STATUS_LABEL[k]: v for k, v in STATUS_COLOR.items()}

    def _riga_consuntivo(row):
        if row["Verdetto"] == STATUS_LABEL["CONSUNTIVO"]:
            return [f"color: {GRAY_MUTED}"] * len(row)
        return [""] * len(row)

    styled = show.style.apply(_riga_consuntivo, axis=1).map(
        lambda v: (
            f"color: {_label_color[v]}; font-weight: 600" if v in _label_color else ""
        ),
        subset=["Verdetto"],
    )
    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Batteria": st.column_config.ProgressColumn(
                "Batteria",
                min_value=0.0,
                max_value=1.0,
                format=" ",
                color=BLUE,
            ),
        },
    )
    st.caption(
        "gap_notti_target = notti mancanti al volume 2025 riproporzionato "
        "sulla capacità — non la capacità residua reale. ADR richiesto = "
        "ADR medio necessario su quelle notti aggiuntive."
    )

    # ── curva delle foto (emphasis: un mese in evidenza, il resto contesto) ─
    import plotly.graph_objects as go

    mesi = list(last["mese_soggiorno"])
    ott = [m for m in mesi if m.month == 10]
    sel = st.selectbox(
        "Mese in evidenza",
        mesi,
        index=mesi.index(ott[0]) if ott else 0,
        format_func=_mese_label,
    )
    fig = go.Figure()
    for m, grp in d.groupby("mese_soggiorno"):
        if m == sel:
            continue
        fig.add_trace(
            go.Scatter(
                x=grp["snapshot_date"],
                y=grp["saturazione_pct"] * 100,
                mode="lines",
                line=dict(color=GRAY_CTX, width=1),
                hovertemplate=_mese_label(m) + " · %{y:.1f}%<extra></extra>",
            )
        )
    sel_grp = d[d["mese_soggiorno"] == sel]
    fig.add_trace(
        go.Scatter(
            x=sel_grp["snapshot_date"],
            y=sel_grp["saturazione_pct"] * 100,
            mode="lines+markers+text",
            line=dict(color=BLUE, width=2),
            marker=dict(size=9),
            text=[""] * (len(sel_grp) - 1) + [_mese_label(sel)],
            textposition="middle right",
            hovertemplate=_mese_label(sel) + " · %{y:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        showlegend=False,
        height=380,
        yaxis_title="saturazione %",
        xaxis_title=None,
        margin=dict(l=10, r=60, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
