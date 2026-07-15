"""Pagina Mutui — embed del tracker mutui (Cloudflare Worker già deployato).

Caso B1 della skill hub-bind: artifact esterno autocontenuto, montato in iframe
dentro la navigazione della hub. Il dato vive nel deploy del Worker (snapshot JSON,
non BigQuery live) — è un sito a sé brandizzato, esente dalla regola BQ-only che
vale per le viste dati Streamlit. Il Worker non setta X-Frame-Options/CSP, quindi
si lascia embeddare (verificato 2026-06-13).

Dal 2026-07-15 il tracker vive su mutui.panorama-host.com dietro Cloudflare Access
(HAR-04): l'iframe si carica solo se il browser ha già una sessione Access —
il primo accesso passa dal bottone "Apri a schermo intero" (login Google).
"""

import streamlit as st
import streamlit.components.v1 as components

from verticals.hub.theme import brand_header

MUTUI_URL = "https://mutui.panorama-host.com/"


def render():
    brand_header("Mutui", "Gruppo Panorama · piani di ammortamento")
    st.link_button("↗ Apri a schermo intero", MUTUI_URL)
    st.caption(
        "Se il riquadro resta vuoto: apri prima 'schermo intero' (login Google via "
        "Cloudflare Access), poi ricarica questa pagina."
    )
    components.html(
        f'<iframe src="{MUTUI_URL}" '
        'style="width:100%;height:1500px;border:0;border-radius:16px;" '
        'loading="lazy"></iframe>',
        height=1520,
        scrolling=True,
    )
