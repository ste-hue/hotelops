"""Pagina hub — Management OS: porta verso l'app edge indipendente.

La regia vive su regia.panorama-host.com (Cloudflare Worker + Access, policy
nominativa), come Canone, Bilancini e Mutui (concept HUB_EMBED_VS_EDGE). Qui niente embed.
"""

import streamlit as st

from verticals.hub.theme import brand_header

REGIA_URL = "https://regia.panorama-host.com"


def render() -> None:
    brand_header("Management OS", "priorità 2027, numeri, regia")
    st.link_button("↗ Apri la regia", REGIA_URL)
    st.caption(
        "App indipendente dietro Cloudflare Access, accesso nominativo con codice OTP "
        "via email. Si apre su «Priorità 2027»; le schede «Numeri» e il diario stanno "
        "dietro."
    )
