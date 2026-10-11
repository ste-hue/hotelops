"""Pagina hub — Canone ORTI → INTUR: porta verso l'app edge indipendente.

Il cruscotto vive su canone.panorama-host.com (Cloudflare Worker + Access, policy
nominativa), come Bilancini e Mutui (concept HUB_EMBED_VS_EDGE). Qui niente embed.
La pagina edge si aggiorna via push KV dal builder condges
(``hotelops canone --push``), senza redeploy.
"""

import streamlit as st

from verticals.hub.theme import brand_header

CANONE_URL = "https://canone.panorama-host.com/"


def render() -> None:
    brand_header("Canone ORTI → INTUR", "la scaletta regge le due gambe?")
    st.link_button("↗ Apri il cruscotto", CANONE_URL)
    st.caption(
        "App indipendente dietro Cloudflare Access: al primo accesso arriva un "
        "codice OTP via email (accessi nominativi). Dentro trovi la scaletta del "
        "canone, i DSCR di ORTI, INTUR e gruppo fino al 2031, le ipotesi e le fonti."
    )
