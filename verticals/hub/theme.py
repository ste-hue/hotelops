"""Panorama Group — theming Streamlit (token dal design system 496a60).

Streamlit non può usare i componenti React del design system; qui ne replichiamo
il *linguaggio visivo* via CSS: palette horizon, i 3 font (Cinzel/Cormorant/Jost,
tutti Google Fonts), eyebrow in maiuscolo tracciato, header navy, card morbide,
ombre calde. Fonti: brief Panorama Group Design System (2026-06-13).

Uso:
    from verticals.hub.theme import inject_brand, brand_header, eyebrow
    inject_brand()                       # una volta per script-run, dopo set_page_config
    brand_header("Food & Beverage", "Maiori")
    eyebrow("Amalfi Coast · Maiori")
"""

from __future__ import annotations

import streamlit as st

# ── Palette "panoramic horizon" (hex esatti dal brief) ──────────────────────
NAVY = "#003764"        # deep-sea — anchor, wordmark, heading
SKY = "#57c1e8"         # sky cyan — la signature wave
AZURE = "#00a8e1"       # azure — hotel accent, focus
TEAL = "#00bfd6"        # teal
GOLD = "#ffd13f"        # sun gold
CORAL = "#ff7f2f"       # sunset coral — roof terrace
IVORY = "#fbf9f5"       # limestone bg
SAND = "#f3eee6"        # warm surface
SLATE = "#3a4750"       # body text

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;1,300&family=Jost:wght@300;400;500;600&display=swap');

:root {{
  --pg-navy: {NAVY}; --pg-sky: {SKY}; --pg-azure: {AZURE}; --pg-teal: {TEAL};
  --pg-gold: {GOLD}; --pg-coral: {CORAL};
  --pg-ivory: {IVORY}; --pg-sand: {SAND}; --pg-slate: {SLATE};
  --pg-font-display: 'Cinzel', serif;
  --pg-font-serif: 'Cormorant Garamond', serif;
  --pg-font-sans: 'Jost', sans-serif;
  --pg-radius-lg: 16px; --pg-radius-xl: 24px;
  --pg-shadow-sm: 0 2px 8px rgba(0,55,100,.08);
  --pg-shadow-navy: 0 12px 32px rgba(0,55,100,.16);
}}

/* Body / widget → Jost geometrico.
   NB: scope su .stApp (eredita ai figli) — MAI [class*="st-"]: blanketava ogni
   emotion-class `st-emotion-cache-*` e bleedava in dataframe overlay, expander e
   controlli sidebar → testo mush/sovrapposto + freccia "espandi" invisibile
   (currentColor forzato a slate). Bug viewer 2026-06-14. */
html, body, .stApp, .stMarkdown, .stMetric {{
  font-family: var(--pg-font-sans);
  color: var(--pg-slate);
}}

/* Heading → Cinzel inscrizionale, navy, leggermente tracciato */
h1, h2, h3 {{
  font-family: var(--pg-font-display) !important;
  color: var(--pg-navy) !important;
  letter-spacing: 0.03em;
  font-weight: 600;
}}

/* st.title un filo più arioso */
h1 {{ font-weight: 600; letter-spacing: 0.04em; }}

/* Eyebrow: maiuscolo tracciato (la firma tipografica del brand) */
.pg-eyebrow {{
  font-family: var(--pg-font-sans);
  text-transform: uppercase;
  letter-spacing: 0.22em;
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--pg-azure);
}}

/* Header brandizzato */
.pg-header {{
  border-bottom: 1px solid var(--pg-sand);
  padding-bottom: 1rem;
  margin-bottom: 1.5rem;
}}
.pg-wordmark {{
  font-family: var(--pg-font-display);
  font-size: 1.5rem; font-weight: 600;
  letter-spacing: 0.18em; color: var(--pg-navy);
}}
.pg-descriptor {{
  font-family: var(--pg-font-serif);
  font-size: 1.6rem; font-weight: 300; font-style: italic;
  color: var(--pg-slate);
}}

/* Card metriche: superficie morbida, bordo sabbia, ombra calda */
[data-testid="stMetric"] {{
  background: #ffffff;
  border: 1px solid var(--pg-sand);
  border-radius: var(--pg-radius-lg);
  box-shadow: var(--pg-shadow-sm);
  padding: 1.1rem 1.2rem;
}}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{
  /* Colpisce ANCHE i figli: Streamlit mette nowrap+ellissi su un div interno,
     non sul padre. + font più piccolo così "2026-05-08" sta nella card. */
  font-family: var(--pg-font-sans) !important;
  font-size: 1.3rem !important;
  font-weight: 600;
  color: var(--pg-navy);
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  overflow-wrap: anywhere;
  line-height: 1.2;
}}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{
  text-transform: uppercase; letter-spacing: 0.05em;
  font-size: 0.68rem; color: var(--pg-slate);
  white-space: normal !important;  /* label a capo, niente "COMANDE ..." tagliato */
}}

/* Bottoni: pill, azure, Jost tracciato */
.stButton > button {{
  font-family: var(--pg-font-sans);
  text-transform: uppercase; letter-spacing: 0.1em;
  border-radius: 999px;
  border: 1px solid var(--pg-azure);
}}

/* Sidebar nav su sabbia calda */
[data-testid="stSidebar"] {{ background: var(--pg-sand); }}

/* Controllo "espandi sidebar" sempre visibile e navy: la freccia » usa
   currentColor → spariva (col vecchio blanket). Difensivo per il viewer. */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapsedControl"] * {{
  color: var(--pg-navy) !important;
  visibility: visible !important;
  opacity: 1 !important;
}}

/* Link / underline cyan */
a {{ color: var(--pg-azure); text-decoration-color: var(--pg-sky); }}

/* ── Mobile (<= 640px) ──────────────────────────────────────────────────
   Streamlit non impila le colonne da solo: si schiacciano. Qui: meno padding,
   colonne che vanno a capo (KPI card 2×2), wordmark/heading rimpiccioliti. */
@media (max-width: 640px) {{
  [data-testid="stMainBlockContainer"], .block-container {{
    padding-left: 0.8rem !important; padding-right: 0.8rem !important;
    padding-top: 2.5rem !important;
  }}
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; gap: 0.6rem !important; }}
  [data-testid="stColumn"], [data-testid="column"] {{
    min-width: 45% !important; flex: 1 1 45% !important;
  }}
  .pg-wordmark {{ font-size: 1.15rem; letter-spacing: 0.1em; }}
  .pg-descriptor {{ font-size: 1.2rem; }}
  h1 {{ font-size: 1.5rem; letter-spacing: 0.02em; }}
  h2, h3 {{ font-size: 1.2rem; }}
  [data-testid="stMetricValue"] {{ font-size: 1.4rem; }}
  /* il controllo "apri sidebar" deve essere visibile e toccabile su mobile
     (altrimenti la nav — che vive nella sidebar — è irraggiungibile) */
  [data-testid="stSidebarCollapsedControl"] {{
    visibility: visible !important; opacity: 1 !important; display: flex !important;
    background: var(--pg-navy) !important; border-radius: 0 0 12px 0 !important;
    padding: 0.25rem 0.4rem !important; z-index: 999 !important;
  }}
  [data-testid="stSidebarCollapsedControl"] svg,
  [data-testid="stSidebarCollapsedControl"] span {{ color: #fff !important; }}
}}
</style>
"""

_HIDE_CHROME = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {visibility: hidden;}
[data-testid="stDecoration"] {display: none;}
</style>
"""


def inject_brand(hide_chrome: bool = False) -> None:
    """Inietta CSS Panorama. hide_chrome=True per la superficie direttore (viewer)."""
    st.markdown(_CSS, unsafe_allow_html=True)
    if hide_chrome:
        st.markdown(_HIDE_CHROME, unsafe_allow_html=True)


def eyebrow(text: str) -> None:
    """Etichetta in maiuscolo tracciato — la firma tipografica del brand."""
    st.markdown(f'<div class="pg-eyebrow">{text}</div>', unsafe_allow_html=True)


def brand_header(descriptor: str, location: str = "Amalfi Coast · Maiori") -> None:
    """Header con wordmark PANORAMA + descrittore editoriale + luogo tracciato."""
    st.markdown(
        f'<div class="pg-header">'
        f'<span class="pg-wordmark">PANORAMA</span>&nbsp;&nbsp;'
        f'<span class="pg-descriptor">{descriptor}</span><br>'
        f'<span class="pg-eyebrow">{location}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )
