"""Pagina hub — Cassa consuntivo (Livelli A+B).

Spec: docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md.
Read-only: v_cash_position (Livello A) + consolidato società (Livello B).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from verticals.condges.cashflow_consuntivo_data import (
    consolidato_societa,
    detect_trasferimenti_interni,
    fetch_movimenti_mese,
)


@st.cache_data(ttl=600)
def _cash_position(societa: str) -> pd.DataFrame:
    from google.cloud import bigquery

    from core.bq.client import get_client
    from core.config import V_CASH_POSITION

    client = get_client()
    sql = f"""
    SELECT mese, banca_id, saldo_iniziale_cert, accrediti, addebiti, netto,
           saldo_calcolato, saldo_finale_cert, scarto
    FROM `{V_CASH_POSITION}`
    WHERE societa_id = @societa
    ORDER BY mese DESC, banca_id
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa)
            ]
        ),
    )
    return job.to_dataframe()


@st.cache_data(ttl=600)
def _consolidato(societa: str, anno: int, mese: int) -> dict:
    movs = fetch_movimenti_mese(societa, anno, mese)
    return consolidato_societa(detect_trasferimenti_interni(movs))


def render() -> None:
    st.title("💰 Cassa consuntivo")
    st.caption(
        "Il vero cashflow: totali dalla banca, quadratura sui saldi certificati. "
        "Livello A = lordi per conto · Livello B = consolidato società, "
        "trasferimenti interni neutralizzati."
    )

    societa = st.radio("Società", ["ORTI", "INTUR"], horizontal=True)

    st.subheader("Livello A — Cash position per conto")
    df = _cash_position(societa)
    if df.empty:
        st.info("Nessun dato in v_cash_position per questa società.")
        return
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
    scelta = st.selectbox("Mese", mesi, format_func=lambda am: f"{am[0]}-{am[1]:02d}")
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
