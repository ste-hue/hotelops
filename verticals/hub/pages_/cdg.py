"""Pagina hub — CdG (Controllo di Gestione): porta verso l'app edge indipendente.

Dal 2026-10-29 la pagina Cassa del CdG vive su cdg.panorama-host.com (Cloudflare
Worker + Access, policy nominativa «Canone — nominativa»), come Canone e Mutui
(concept HUB_EMBED_VS_EDGE). Qui niente embed: la hub è dietro IAP, l'app dietro
Access, due cancelli distinti. La pagina edge si aggiorna via push KV dal builder
condges (``hotelops cdg cassa --aggiorna --push``), senza redeploy. Dati riservati
(saldi, PF, progetti): tile sensibile, grant a mano (S1); il re-check del grant
resta anche qui, come per le superfici di scrittura.
"""

import streamlit as st

from verticals.hub.theme import brand_header

CDG_URL = "https://cdg.panorama-host.com/"


def render() -> None:
    from verticals.hub.roles import current_apps

    if "cdg" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
    brand_header("Controllo di Gestione", "Cassa ORTI e INTUR · scenari")
    st.link_button("↗ Apri la pagina Cassa", CDG_URL)
    st.caption(
        "App indipendente dietro Cloudflare Access: al primo accesso arriva un "
        "codice OTP via email (accessi nominativi). Dentro trovi i minimi di cassa "
        "delle due società, lo slider del canone, progetti e finanziamenti da "
        "accendere o spostare, fonti e limiti dichiarati. Competenza e Impegno "
        "arrivano dopo."
    )
