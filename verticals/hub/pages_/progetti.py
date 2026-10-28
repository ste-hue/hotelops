"""Pagina hub — Progetti: i cantieri aperti, con le loro scadenze e le loro porte.

Un progetto CapEx vive in tre posti (skill ``progetto-capex``): l'app di avanzamento
(edge, Cloudflare Access), la cartella Drive ``Investimenti<YYYY>/<id>/`` con le
sorgenti, e il cockpit ``<id>_Tracking.xlsx``. Qui si mettono insieme, con le tappe
che contano. Niente lettura delle API edge (servirebbe un service token): le tappe
sono dichiarate qui e si aggiornano a mano quando cambia il piano. Il registry BQ
``d_progetti`` (piano *Projects event-sourced*, deferred) è la casa futura di
questi dati.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import streamlit as st

from verticals.hub.theme import brand_header


@dataclass(frozen=True)
class Tappa:
    label: str
    quando: date


@dataclass(frozen=True)
class Progetto:
    id: str
    titolo: str
    committente: str
    perimetro: str
    app_url: str
    drive_url: str
    cockpit_url: str
    tappe: tuple[Tappa, ...] = field(default_factory=tuple)
    nota: str = ""


_DRIVE = "https://drive.google.com/drive/folders/"
_FILE = "https://drive.google.com/file/d/"

PROGETTI: tuple[Progetto, ...] = (
    Progetto(
        id="HPAN26PIANO3",
        titolo="Cantiere terzo piano",
        committente="INTUR",
        perimetro="20 camere (H301–H322) · impresa AMCN · PM Hospitality Project · DL ing. Pisacane",
        app_url="https://hpan26.panorama-host.com",
        drive_url=_DRIVE + "1RO88SZebB6SKEkVOpWbc1S0ngbRSRfwa",
        cockpit_url=_FILE + "1dV0WZLJru2N7PSBqE5IBCqqw5vNqBIYw/view",
        tappe=(
            Tappa("Inizio lavori", date(2026, 10, 19)),
            Tappa("Uscita impresa edile", date(2027, 3, 20)),
            Tappa("Fine lavori", date(2027, 4, 14)),
        ),
        nota="Dopo il 20/03 restano finiture, forniture e montaggi fino al 14/04.",
    ),
    Progetto(
        id="HPAN26SOFT",
        titolo="Soft restyling camere",
        committente="INTUR / ORTI per struttura",
        perimetro="Hotel piano 2 + 101–114 · 20 unità Angelina · 9 Casa Vacanze · risorse interne",
        app_url="https://soft.panorama-host.com",
        drive_url=_DRIVE + "1Qobru_psvvTFWw2dUCeUo4VjXx0-hQoO",
        cockpit_url=_FILE + "1YwcAGqsyzAomSydj1UT0BIUMSiA8GB8s/view",
        tappe=(Tappa("Fine lavori (riapertura)", date(2027, 4, 14)),),
        nota="Il budget nasce dal rilievo nell'app: prezzo per voce × voci da fare.",
    ),
)


def giorni_mancanti(quando: date, oggi: date) -> str:
    """Testo della distanza da una tappa, nel verso giusto per chi legge."""
    d = (quando - oggi).days
    if d == 0:
        return "oggi"
    if d > 0:
        return f"fra {d} giorni"
    return f"{-d} giorni fa"


def _card(p: Progetto, oggi: date) -> None:
    with st.container(border=True):
        st.markdown(f"### {p.titolo}")
        st.caption(f"{p.id} · committente {p.committente}")
        st.caption(p.perimetro)
        for t in p.tappe:
            st.markdown(
                f"**{t.label}** — {t.quando:%d/%m/%Y} · {giorni_mancanti(t.quando, oggi)}"
            )
        if p.nota:
            st.caption(p.nota)
        c1, c2, c3 = st.columns(3)
        c1.link_button("↗ Avanzamento", p.app_url)
        c2.link_button("↗ Cartella Drive", p.drive_url)
        c3.link_button("↗ Cockpit", p.cockpit_url)


def render(oggi: date | None = None) -> None:
    oggi = oggi or date.today()
    brand_header("Progetti", "cantieri aperti · dove siamo, quando finiamo")
    st.caption(
        "Avanzamento = app edge (Cloudflare Access, codice OTP via email). "
        "Cartella Drive = sorgenti preventivi e fatture. Cockpit = tracking economico."
    )
    cols = st.columns(len(PROGETTI))
    for col, p in zip(cols, PROGETTI, strict=True):
        with col:
            _card(p, oggi)
