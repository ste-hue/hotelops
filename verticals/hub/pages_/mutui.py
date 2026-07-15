"""Pagina hub — Mutui: porta verso l'app edge indipendente.

Dal 2026-07-15 il tracker vive su mutui.panorama-host.com dietro Cloudflare Access
(HAR-04, policy nominativa: org + ste.dellapietra@ + stedepi@). Qui niente embed:
una volta che l'app è Access-gated, l'iframe della hub non renderizza finché il
browser non ha una sessione Access — la hub è dietro IAP, mutui dietro Access, due
cancelli distinti (concept HUB_EMBED_VS_EDGE, stessa lezione di bilancini). La pagina
edge serve da sé ammortamenti, simulatore Piano Industriale e scenario (Workers KV);
il dato è uno snapshot del Worker, non BigQuery live.
"""

import streamlit as st

from verticals.hub.theme import brand_header

MUTUI_URL = "https://mutui.panorama-host.com/"


def render() -> None:
    brand_header("Mutui", "Gruppo Panorama · piani di ammortamento")
    st.link_button("↗ Apri Mutui", MUTUI_URL)
    st.caption(
        "App indipendente dietro Cloudflare Access: al primo accesso passi dal "
        "login Google (accessi nominativi). Dentro trovi ammortamenti, simulatore "
        "e Piano Industriale."
    )
