"""Pagina Revenue — a che ritmo riempiamo, e com'è andata (v_booking_curve).

LA domanda della pagina: "a che ritmo riempiamo le prenotazioni, e come
abbiamo fatto rispetto al 2025 a parità di camera?" Due sezioni: consuntivo
(mesi chiusi, fatto vs target) e ritmo (mesi aperti, batteria + pickup).
Nessun verdetto calcolato: i numeri col segno giusto, la lettura è di chi
decide. Metodologia: vault concepts/BOOKING_PACE_E_BASI.

Write-path (sensitive): upload della foto settimanale — validazione basi
omogenee (valida_basi_export) e poi SOLO il percorso lineage
(intake → GCS → promote), mai scorciatoie verso BQ.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client
from core.config import V_BOOKING_CURVE

# ── palette (dataviz reference instance — ruoli, non hex sparsi) ─────────────
BLUE = "#2a78d6"  # slot-1: emphasis + riempimento meter
GRAY_CTX = "#c3c2b7"  # de-enfasi (linee contesto)

SOURCE_FOTO = "POWERBI_ANDAMENTOPRENOTAZIONI_ORTI_SNAPSHOT"


def _ingest_foto(upload) -> None:
    """Valida e ingerisce l'export settimanale via lineage (intake → promote)."""
    import tempfile
    from pathlib import Path

    from ingest.flussi.ingest_andamento_prenotazioni import valida_basi_export

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / (upload.name or "foto_otb.xlsx")
        path.write_bytes(upload.getvalue())
        ok, motivo = valida_basi_export(path)
        if not ok:
            st.error(f"Export rifiutato — {motivo}")
            return

        from ingest.intake import intake_file
        from ingest.promotion import promote_raw_object

        with st.spinner("Carico su GCS e promuovo…"):
            r = intake_file(path, source_name=SOURCE_FOTO, actor="hub:revenue")
            if r.deduped:
                st.info("Foto già presente (contenuto identico) — niente da fare.")
                return
            if not r.raw_object_id:
                st.error("Intake fallito (lineage gate): file NON caricato.")
                return
            p = promote_raw_object(r.raw_object_id, actor="hub:revenue")
    if p.status == "PROMOTED":
        st.success("Foto caricata — curve aggiornate.")
        load_curve.clear()
        st.rerun()
    else:
        st.error(
            f"Promote {p.status} ({p.reason or '-'}): il file è al sicuro in "
            "GCS ma non è entrato in tabella — da investigare, non ricaricarlo."
        )


def calendario_confrontabile(
    ly_gg: float | None, cy_gg: float | None, tolleranza: float = 0.15
) -> bool:
    """True se i giorni operativi dei due anni sono comparabili (±15%).

    Aprile 2026 (28 gg) vs 2025 (15 gg, apertura 16/4) → NON confrontabile:
    un delta vs target mentirebbe in entrambe le direzioni.
    """
    if not ly_gg or not cy_gg:
        return False
    r = cy_gg / ly_gg
    return (1 - tolleranza) <= r <= (1 + tolleranza)


@st.cache_data(ttl=300)
def load_curve() -> pd.DataFrame:
    sql = (
        f"SELECT * FROM `{V_BOOKING_CURVE}` "
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


def _eur(v) -> str:
    try:
        return f"{float(v):,.0f} €".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def render() -> None:
    st.title("📈 Revenue")
    st.caption(
        "A che ritmo riempiamo, e com'è andata — fotografie OTB settimanali, "
        "base imponibile, target = 2025 a parità di camera"
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

    ultima = d["snapshot_date"].max()
    gg_fa = (pd.Timestamp.today().date() - ultima).days
    c1, c2 = st.columns(2)
    c1.metric(
        "Ultima foto",
        ultima.strftime("%d/%m/%Y"),
        f"{gg_fa} giorni fa",
        delta_color="off",
    )
    c2.metric("Fotografie", d["snapshot_date"].nunique())
    if gg_fa > 10:
        st.warning(
            "Foto più recente di oltre 10 giorni — manca l'export settimanale "
            '"Andamento Prenotazioni" (caricalo qui sotto).'
        )

    with st.expander('📥 Carica la foto settimanale (export "Andamento Prenotazioni")'):
        st.caption(
            "Un export a settimana, tutte le strutture, senza filtro tipologia. "
            "Il file viene validato (basi omogenee) prima di entrare: se i "
            "filtri sono diversi dalla serie, viene rifiutato col motivo."
        )
        up = st.file_uploader("Export xlsx", type=["xlsx"], key="foto_otb")
        if up is not None and st.button("Ingerisci", type="primary"):
            _ingest_foto(up)

    last = d[d["snapshot_date"] == ultima].sort_values("mese_soggiorno")
    mese_foto = ultima.replace(day=1)
    consumati = last[last["mese_soggiorno"] < mese_foto]
    aperti = last[last["mese_soggiorno"] >= mese_foto]

    # ── Com'è andata (mesi chiusi: fatto vs 2025 × capacità) ────────────────
    if not consumati.empty:
        st.subheader("Com'è andata")
        st.caption(
            "Ricavo camere dei mesi chiusi vs target parità-camera "
            "(= 2025 × capacità). Sopra il target = crescita organica."
        )

        def _vs_target(r) -> str:
            if not calendario_confrontabile(
                r["ly_giorni_operativi"], r["cy_giorni_operativi_osservati"]
            ):
                return (
                    f"n/c — calendario diverso "
                    f"({int(r['ly_giorni_operativi'])} gg operativi 2025 "
                    f"vs {int(r['cy_giorni_operativi_osservati'])})"
                )
            if pd.isna(r["target_imponibile"]) or not r["target_imponibile"]:
                return "n/c — target assente"
            delta = r["otb_imponibile"] / r["target_imponibile"] - 1
            return f"{delta:+.0%}"

        st.dataframe(
            pd.DataFrame(
                {
                    "Mese": consumati["mese_soggiorno"].map(_mese_label),
                    "Ricavo camere": consumati["otb_imponibile"].map(_eur),
                    "Target (2025 × cap.)": consumati["target_imponibile"].map(_eur),
                    "vs target": consumati.apply(_vs_target, axis=1),
                }
            ),
            hide_index=True,
            width="stretch",
        )

    # ── A che ritmo carichiamo (mesi aperti) ────────────────────────────────
    st.subheader("A che ritmo carichiamo")
    st.caption(
        "Batteria = occupazione OTB vs capacità fisica. ADR marginale = a "
        "quanto si vende l'ultima camera (tra le ultime due foto); ADR "
        "richiesto = quanto serve sulle notti mancanti per arrivare al target."
    )
    st.dataframe(
        pd.DataFrame(
            {
                "Mese": aperti["mese_soggiorno"].map(_mese_label),
                "Batteria": aperti["saturazione_pct"].clip(upper=1.0),
                "Pickup notti": aperti["pickup_notti"],
                "Pickup €/gg": aperti["pickup_eur_gg"].round(0),
                "ADR medio": aperti["otb_adr"].round(0),
                "ADR marginale": aperti["adr_marginale"].round(0),
                "ADR richiesto": aperti["adr_richiesto"].round(0),
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Batteria": st.column_config.ProgressColumn(
                "Batteria",
                min_value=0.0,
                max_value=1.0,
                format="percent",
                color=BLUE,
            ),
        },
    )

    # ── curva delle foto (emphasis: un mese in evidenza, il resto contesto) ─
    import plotly.graph_objects as go

    mesi = list(aperti["mese_soggiorno"])
    if mesi:
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
            yaxis_title="batteria %",
            xaxis_title=None,
            margin=dict(l=10, r=60, t=10, b=10),
        )
        st.plotly_chart(fig, width="stretch")

    with st.expander("Dettaglio analista (tutte le colonne, ultima foto)"):
        st.dataframe(last, hide_index=True, width="stretch")
