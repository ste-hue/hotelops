"""Pagina hub — Bilancini (bilancio di verifica: YTD, progressione, navigatore).

Read-only, dati riservati (S1: sensitive). Il payload si costruisce live da
BigQuery riusando il builder condges (fetch_bilancino/fetch_gruppi/build_payload
di verticals/condges/build_bilancini_artifact) e si monta l'HTML self-contained
(render_html) in un embed — nessun file su disco, nessun iframe esterno.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from verticals.hub.theme import brand_header


@st.cache_data(ttl=3600)
def _payload() -> dict:
    """Payload live da BQ (f_bilancino + d_conti_gruppi). Cache-a la funzione,
    non il client BQ (non hashable)."""
    from core.bq.client import get_client
    from verticals.condges.build_bilancini_artifact import (
        build_payload,
        fetch_bilancino,
        fetch_gruppi,
    )

    client = get_client()
    bilancino = fetch_bilancino(client)
    gruppi = fetch_gruppi(client)
    return build_payload(bilancino, gruppi)


def render() -> None:
    brand_header("Bilancini", "bilancio di verifica: YTD, progressione, navigatore")

    from verticals.condges.build_bilancini_artifact import render_html

    payload = _payload()
    if not payload.get("mesi"):
        st.info("Nessun dato in f_bilancino per il periodo.")
        return
    components.html(render_html(payload), height=1500, scrolling=True)
