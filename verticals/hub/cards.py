"""KPI vivi per le tile della Home gateway.

Ogni `card_*` ritorna un dict ``{"semaforo", "kpi_label", "kpi_value"}`` calcolato
**live da BigQuery** (cache 5 min). Regola dati: BQ-only, mai cache silente — se BQ è
giù la funzione solleva e la Home mostra la tile "n/d" (non rompe la griglia).
"""

from __future__ import annotations

import streamlit as st

from verticals.hub.freshness import carica_freshness, semaforo


def _fmt_eur(v: float | None) -> str:
    if v is None:
        return "n/d"
    return "€ " + f"{v:,.0f}".replace(",", ".")


@st.cache_data(ttl=300, show_spinner=False)
def _freshness() -> dict:
    return carica_freshness()


@st.cache_data(ttl=300, show_spinner=False)
def card_cashflow() -> dict:
    """Saldo banca totale certificato all'ultima data disponibile."""
    from core.bq.client import get_client

    q = """
    SELECT data_riferimento, SUM(saldo_eur) AS tot
    FROM `hotelops-suite.hotelops.f_saldi_banca_chiusura_mensile`
    WHERE data_riferimento = (
      SELECT MAX(data_riferimento)
      FROM `hotelops-suite.hotelops.f_saldi_banca_chiusura_mensile`
    )
    GROUP BY data_riferimento
    """
    r = next(iter(get_client().query(q).result()))
    return {
        "semaforo": "🟢",
        "kpi_label": f"saldo al {r.data_riferimento:%d/%m}",
        "kpi_value": _fmt_eur(r.tot),
    }


@st.cache_data(ttl=300, show_spinner=False)
def card_banche() -> dict:
    """Giorni dall'ultimo movimento bancario (staleness = il segnale che conta)."""
    from core.bq.client import get_client

    q = """
    SELECT DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data_operazione), DAY) AS g
    FROM `hotelops-suite.hotelops.f_banche_movimenti`
    """
    g = next(iter(get_client().query(q).result())).g
    return {
        "semaforo": semaforo(g, soglia_attenzione=7, soglia_allarme=21),
        "kpi_label": "ultimo movimento",
        "kpi_value": f"{g} gg fa" if g is not None else "n/d",
    }


@st.cache_data(ttl=300, show_spinner=False)
def card_spiaggia() -> dict:
    """Ricavo stabilimento dell'ultimo giorno disponibile."""
    from core.bq.client import get_client

    q = """
    SELECT data, stabilimento_totale AS tot
    FROM `hotelops-suite.hotelops.v_spiaggia_giornaliero`
    WHERE data = (SELECT MAX(data) FROM `hotelops-suite.hotelops.v_spiaggia_giornaliero`)
    """
    r = next(iter(get_client().query(q).result()))
    return {
        "semaforo": "🟢",
        "kpi_label": f"ricavo {r.data:%d/%m}",
        "kpi_value": _fmt_eur(r.tot),
    }


def card_fb() -> dict:
    """Freschezza F&B (ultimo mese coperto). Food-cost% rimandato al fix mensa."""
    g = _freshness()["fb"]["giorni"]
    return {
        "semaforo": semaforo(g, soglia_attenzione=35, soglia_allarme=70),
        "kpi_label": "ultimo mese",
        "kpi_value": f"{g} gg fa" if g is not None else "n/d",
    }


def card_reviews() -> dict:
    r = _freshness()["reviews"]
    return {
        "semaforo": semaforo(r["giorni"], soglia_attenzione=7, soglia_allarme=14),
        "kpi_label": "media mese",
        "kpi_value": str(r["media_mese"]) if r["media_mese"] is not None else "n/d",
    }


def card_ingest() -> dict:
    n = _freshness()["ingest"]["in_coda"]
    return {
        "semaforo": "🟢" if n == 0 else "🟡",
        "kpi_label": "raw in coda",
        "kpi_value": str(n),
    }
