"""Un ingresso per i progetti; gli strumenti restano nelle app di progetto."""

import streamlit as st

from verticals.hub.theme import brand_header
from verticals.projects.catalog import PROJECTS


def render() -> None:
    # Import locale: roles legge il registry, che importa questa pagina.
    from verticals.hub.roles import current_apps

    if "projects" not in current_apps():
        st.error("Accesso ai progetti non autorizzato.")
        return

    brand_header("Progetti", "strumenti operativi e governo del progetto")
    for project in PROJECTS:
        with st.container(border=True):
            st.subheader(project.title)
            st.caption(project.progetto_id)
            st.write(project.description)
            st.link_button("Apri il progetto", project.app_url)
            st.link_button("Apri il fronte in Regia", project.regia_url)
    st.caption(
        "Collegamenti alle app esistenti. Accessi gestiti anche dalle destinazioni; "
        "nessuna sincronizzazione di dati o verifica di avanzamento in questa pagina."
    )
