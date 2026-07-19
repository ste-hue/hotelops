"""Pagina hub — Cassa consuntivo (Livelli A+B).

Spec: docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md.
Read-only: v_cash_position (Livello A) + consolidato società (Livello B).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from verticals.condges.services.cassa_consuntivo_service import (
    load_cash_position,
    load_classificato,
    load_consolidato,
)
from verticals.hub.surface_context import SurfaceContext, current_context


@st.cache_data(ttl=600)
def _cash_position(societa: str) -> pd.DataFrame:
    return load_cash_position(societa)


@st.cache_data(ttl=600)
def _consolidato(societa: str, anno: int, mese: int) -> dict:
    return load_consolidato(societa, anno, mese)


@st.cache_data(ttl=600)
def _classificato(societa: str, anno: int, mese: int) -> dict:
    return load_classificato(societa, anno, mese)


def render(ctx: SurfaceContext | None = None) -> None:
    ctx = ctx or current_context()
    st.title("💰 Cassa consuntivo")
    st.caption(
        "Il vero cashflow: totali dalla banca, quadratura sui saldi certificati. "
        "Livello A = lordi per conto · Livello B = consolidato società, "
        "trasferimenti interni neutralizzati."
    )
    societa_options = ["ORTI", "INTUR"]
    societa = st.radio(
        "Società",
        societa_options,
        index=societa_options.index(ctx.societa),
        horizontal=True,
    )

    st.subheader("Livello A — Cash position per conto")
    df = _cash_position(societa)
    if df.empty:
        st.info("Nessun dato in v_cash_position per questa società.")
        return
    st.caption(
        f"Contesto globale: {societa} · {ctx.anno}-{ctx.mese:02d} · {ctx.scenario}"
    )
    st.dataframe(
        df.style.map(
            lambda v: (
                "background-color:#fdd"
                if isinstance(v, float) and abs(v) > 0.01
                else ""
            ),
            subset=["scarto"],
        ),
        use_container_width=True,
    )
    st.caption(
        "scarto ≠ 0 → export homebanking incompleto o saldo certificato da rivedere. "
        "Anchor NULL = saldo certificato mancante per quel mese."
    )

    st.subheader("Livello B — Consolidato società (mese)")
    mesi = sorted({(m.year, m.month) for m in df["mese"]}, reverse=True)
    scelta_default = next((am for am in mesi if am == (ctx.anno, ctx.mese)), mesi[0])
    if scelta_default != (ctx.anno, ctx.mese):
        st.caption(
            f"Contesto {ctx.anno}-{ctx.mese:02d} non disponibile qui: uso "
            f"{scelta_default[0]}-{scelta_default[1]:02d}."
        )
    scelta = st.selectbox(
        "Mese",
        mesi,
        index=mesi.index(scelta_default),
        format_func=lambda am: f"{am[0]}-{am[1]:02d}",
    )
    anno, mese = scelta
    cons = _consolidato(societa, anno, mese)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Incassi esterni", f"{cons['incassi_esterni']:,.2f} €")
    c2.metric("Pagamenti esterni", f"{cons['pagamenti_esterni']:,.2f} €")
    c3.metric("Trasferimenti interni", f"{cons['trasferimenti_interni']:,.2f} €")
    c4.metric("Variazione netta", f"{cons['variazione_netta']:,.2f} €")
    st.caption(
        "Matcher Fase 1 (deterministico): importo esatto ±0,01 €, finestra ±3 giorni, "
        "stessa banca solo con causale di giro. Coppie fuori soglia non vengono "
        "segnalate — arriva con la review queue (C.2)."
    )
    if cons["candidati_trasferimento"]:
        st.warning(
            f"Candidati trasferimento non confermati: "
            f"{cons['candidati_trasferimento']:,.2f} € — restano nei flussi esterni "
            "(review in arrivo con C.2)."
        )

    st.subheader("Livello C — Classificazione contabile (per voce PF)")
    st.caption(
        "Esolver spiega, non determina: il totale reale resta quello della banca. "
        "Lo scarto aggregato è la 'differenza banca–contabilità' (il matching "
        "per movimento arriva con C.2)."
    )
    cls = _classificato(societa, anno, mese)
    df_voci = pd.DataFrame(
        sorted(cls["per_voce"].items(), key=lambda kv: kv[1]),
        columns=["voce", "importo"],
    )
    st.dataframe(df_voci, use_container_width=True)
    r1, r2, r3 = st.columns(3)
    r1.metric("Non mappato (conto)", f"{cls['non_mappato_conto']:,.2f} €")
    r2.metric("Non mappato (fornitore)", f"{cls['non_mappato_fornitore']:,.2f} €")
    diff = cons["variazione_netta"] - cls["totale_registrato"]
    r3.metric("Differenza banca–contabilità", f"{diff:,.2f} €")
