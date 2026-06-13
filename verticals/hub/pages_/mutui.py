"""Pagina Mutui — embed del tracker mutui (Cloudflare Worker già deployato).

Caso B1 della skill hub-bind: artifact esterno autocontenuto, montato in iframe
dentro la navigazione della hub. Il dato vive nel deploy del Worker (snapshot JSON,
non BigQuery live) — è un sito a sé brandizzato, esente dalla regola BQ-only che
vale per le viste dati Streamlit. Il Worker non setta X-Frame-Options/CSP, quindi
si lascia embeddare (verificato 2026-06-13).
"""

import streamlit as st
import streamlit.components.v1 as components

from verticals.hub.theme import brand_header

MUTUI_URL = "https://mutui-tracker.ste-dellapietra.workers.dev/"


def render():
    brand_header("Mutui", "Gruppo Panorama · piani di ammortamento")
    st.link_button("↗ Apri a schermo intero", MUTUI_URL)
    components.html(
        f'<iframe src="{MUTUI_URL}" '
        'style="width:100%;height:1500px;border:0;border-radius:16px;" '
        'loading="lazy"></iframe>',
        height=1520,
        scrolling=True,
    )
