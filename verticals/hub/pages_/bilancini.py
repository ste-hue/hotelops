"""Pagina hub — Bilancini: porta verso l'app edge indipendente.

Dal 2026-07-15 i bilancini vivono su bilancini.panorama-host.com (Cloudflare
Worker + Access, policy nominativa OTP — stessi grant S1 di questa pagina).
Qui niente embed: l'iframe sandbox di Streamlit uccide download/fullscreen
(pomeriggio di workaround 2026-07-14, concept HUB_EMBED_VS_EDGE). La pagina
edge serve da sé ⬇CSV e /data.{csv,json}; si aggiorna via push KV dal builder
condges (--push), senza redeploy.
"""

import streamlit as st

from verticals.hub.theme import brand_header

BILANCINI_URL = "https://bilancini.panorama-host.com/"


def render() -> None:
    brand_header("Bilancini", "bilancio di verifica: YTD, progressione, navigatore")
    st.link_button("↗ Apri Bilancini", BILANCINI_URL)
    st.caption(
        "App indipendente dietro Cloudflare Access: al primo accesso arriva un "
        "codice OTP via email (accessi nominativi). Dentro trovi le tre viste, "
        "il download CSV e i dati grezzi su /data.csv e /data.json."
    )
