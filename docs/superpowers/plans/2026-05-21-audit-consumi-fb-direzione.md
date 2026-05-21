# Audit Consumi F&B per la Direzione — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire due artefatti audit per la direzione di Hotel Panorama che applicano la canonical-transformation-matrix a 3 vertical F&B (BREAKFAST/RISTORANTE/BAR) — Streamlit read-only con 6 layer per vertical + range industria + alert, e Google Form per conferma codici.

**Architecture:** Streamlit `audit_consumi_dashboard.py` con sidebar 6 pagine (Primer + B1/B2/B3 vertical + Anomalie FYI + Recap). Per ogni vertical: layer 1-3 dati (codici/reparti/coperti), layer 4 KPI calcolati, layer 5 range industria tabella, layer 6 alert semaforo verde/giallo/rosso. Google Form via Apps Script con 8 sezioni: identità + 3 vertical + coperti mapping + range + anomalie + catch-all.

**Tech Stack:** Python (Streamlit, pandas, plotly, google-cloud-bigquery) + Google Apps Script (JavaScript).

**Spec:** [2026-05-21-audit-consumi-fb-direzione-design.md](../specs/2026-05-21-audit-consumi-fb-direzione-design.md)

**Test strategy:** UI tool one-off + Apps Script. Niente unit test (le query sono SQL pure su BQ produzione; il rendering Streamlit è visivo). Smoke test finale che confronta numeri con SQL manuale + verifica esempio aprile 2026 breakfast (~€4 cost/pax, ~€10 ricavo/pax, FC ~40%).

---

## File Structure

| File | Responsabilità | LOC stimate |
|---|---|---|
| `verticals/condges/audit_consumi_dashboard.py` | Streamlit app: 6 pagine + cache BQ + 3 funzioni vertical riusabili | ~600 |
| `verticals/condges/audit_form.gs` | Apps Script `createAuditForm()` 8 sezioni | ~300 |
| `docs/audit_consumi_workflow.md` | Workflow setup + esecuzione + analisi post-risposte | ~60 |

Il file Streamlit è auto-contenuto: query inline nelle funzioni `render_*()`, nessun modulo helper. È accettabile perché ogni vertical ha query specifiche (no DRY violation reale) e il file resta nei 600 LOC. Una **funzione helper** `render_vertical_layers()` riusabile per i 3 bucket riduce duplicazione del template 6-layer.

---

## Task 1: Skeleton Streamlit + sidebar navigazione

**Files:**
- Create: `verticals/condges/audit_consumi_dashboard.py`

- [ ] **Step 1: Write skeleton**

```python
"""Audit consumi F&B per la direzione — Hotel Panorama.

Streamlit read-only che applica la canonical-transformation-matrix a 3 vertical
F&B (BREAKFAST / RISTORANTE / BAR). 6 layer per vertical: Ricavi → Consumi →
Coperti → KPI → Range industria → Alert.

Run: streamlit run verticals/condges/audit_consumi_dashboard.py
Spec: docs/superpowers/specs/2026-05-21-audit-consumi-fb-direzione-design.md
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

PROJECT = "hotelops-suite"
DATASET = "hotelops"
FORM_URL = "https://forms.gle/PLACEHOLDER"  # update dopo creazione Form via Apps Script

PAGES = [
    "🏠 Primer — Mental model",
    "🥐 B1 — Breakfast",
    "🍽️ B2 — Ristorante",
    "🍷 B3 — Bar / Beverage",
    "⚠️ Anomalie FYI",
    "📋 Recap + Form",
]


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    """BQ client singleton."""
    return bigquery.Client(project=PROJECT)


@st.cache_data(ttl=300)
def run_query(sql: str) -> pd.DataFrame:
    """Esegue query BQ con cache 5 min."""
    return get_bq_client().query(sql).to_dataframe()


def alert_color(value: float, target_lo: float, target_hi: float,
                warning_hi: float) -> str:
    """Ritorna colore semaforo per valore vs range.
    verde se nel target, giallo se warning, rosso se investigate.
    """
    if target_lo <= value <= target_hi:
        return "🟢"
    if target_hi < value <= warning_hi:
        return "🟡"
    return "🔴"


def main() -> None:
    st.set_page_config(
        page_title="Audit consumi F&B — Hotel Panorama",
        page_icon="🍴",
        layout="wide",
    )
    st.sidebar.title("🍴 Audit F&B")
    st.sidebar.markdown("**Hotel Panorama** — canonical-transformation-matrix")
    page = st.sidebar.radio("Naviga", PAGES, label_visibility="collapsed")
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "Dati live da BigQuery `hotelops-suite.hotelops`.\n\n"
        "Read-only. Risposte vanno nel Google Form (link in fondo)."
    )

    if page == PAGES[0]:
        render_primer()
    elif page == PAGES[1]:
        render_b1_breakfast()
    elif page == PAGES[2]:
        render_b2_ristorante()
    elif page == PAGES[3]:
        render_b3_bar()
    elif page == PAGES[4]:
        render_anomalie()
    elif page == PAGES[5]:
        render_recap()


def render_primer() -> None:
    st.title("🏠 Primer — Mental model")
    st.info("Pagina da implementare nel Task 2")


def render_b1_breakfast() -> None:
    st.title("🥐 B1 — Breakfast")
    st.info("Pagina da implementare nel Task 3")


def render_b2_ristorante() -> None:
    st.title("🍽️ B2 — Ristorante")
    st.info("Pagina da implementare nel Task 4")


def render_b3_bar() -> None:
    st.title("🍷 B3 — Bar / Beverage")
    st.info("Pagina da implementare nel Task 5")


def render_anomalie() -> None:
    st.title("⚠️ Anomalie FYI")
    st.info("Pagina da implementare nel Task 6")


def render_recap() -> None:
    st.title("📋 Recap + Form")
    st.info("Pagina da implementare nel Task 7")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run streamlit and verify sidebar**

```bash
streamlit run verticals/condges/audit_consumi_dashboard.py
```

Browser apre. Sidebar mostra 6 voci. Cliccare su ogni voce mostra il placeholder.

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): Streamlit skeleton — 6 pagine vertical + sidebar"
```

---

## Task 2: Primer page

**Files:**
- Modify: `verticals/condges/audit_consumi_dashboard.py` — replace `render_primer()`

- [ ] **Step 1: Implement render_primer()**

```python
def render_primer() -> None:
    st.title("🏠 Primer — Mental model")
    st.markdown(
        "Questa dashboard applica una **matrice canonica di trasformazione** "
        "in 6 layer per analizzare i 3 vertical F&B (Breakfast / Ristorante / Bar). "
        "Se conosci HotelCube ma non le nostre tabelle BigQuery, leggi qui prima."
    )

    st.header("Le 3 fonti dati su BigQuery")
    fonti = pd.DataFrame([
        {
            "Fonte HotelCube (che conosci)": "Produzione Netta Dashboard (Power BI export)",
            "Tabella BigQuery": "`f_ricavi_fb`",
            "Cosa contiene": "Ricavi netti per BU×mese×codice (SCBKFBB, BRK*, RISLFOOD, BAR, BAN…)",
        },
        {
            "Fonte HotelCube (che conosci)": "Scarico magazzino HotelCube (Excel Economato)",
            "Tabella BigQuery": "`f_consumi_economato`",
            "Cosa contiene": "Cost mensile per reparto×prodotto (BRK, CUCINA, CANTINA, DIPEND, HSK*, MAN*…)",
        },
        {
            "Fonte HotelCube (che conosci)": "Conta coperti (Hoxell / Google Sheet RistoCube)",
            "Tabella BigQuery": "`f_coperti_giornalieri`",
            "Cosa contiene": "Coperti giornalieri per BU × tipo_pasto (BRK, LUNCH, DINNER)",
        },
    ])
    st.dataframe(fonti, hide_index=True, use_container_width=True)

    st.header("Mental model: 6 layer canonical")
    st.markdown(
        """
```
RICAVI       (domanda — cosa è stato venduto, da dove)
   ↓
CONSUMI      (assorbimento materie — quanto magazzino è uscito)
   ↓
COPERTI      (volume operativo reale — quante persone servite)
   ↓
KPI          (efficienza normalizzata — €/coperto, %, quantità/coperto)
   ↓
RANGE        (aspettativa industria — qual è la fascia normale?)
   ↓
ALERT        (deviazione — cosa è fuori range e va indagato)
```

Per ogni vertical i 6 layer sono diversi: fonti, reparti, coperti applicabili,
KPI sensati, range industria.

Quello che ti chiediamo è di confermare i **layer 1-3** (codici, reparti,
coperti). I layer 4-6 li costruiamo noi.
"""
    )

    st.header("I 3 vertical in sintesi")
    sint = pd.DataFrame([
        {
            "Vertical": "🥐 B1 BREAKFAST",
            "Ricavi": "SCBKFBB + BRK* (multi-BU: HOTEL+RES+ANG+CVM)",
            "Consumi": "reparto BRK",
            "Coperti": "tipo_pasto=BRK (tutte BU)",
            "KPI primary": "€/coperto + food cost %",
        },
        {
            "Vertical": "🍽️ B2 RISTORANTE",
            "Ricavi": "RISLFOOD + RISDFOOD + RISTLUNC + RISTDINN + DINFOOD + LUNBAR + RISBFOOD + BAN + eventi",
            "Consumi": "reparto CUCINA",
            "Coperti": "tipo_pasto IN (LUNCH, DINNER)",
            "KPI primary": "Food cost % (target 25-35%)",
        },
        {
            "Vertical": "🍷 B3 BAR / BEVERAGE",
            "Ricavi": "BAR + RISLBEVE + RISDBEV + DINBEV + BANB + PROSECCO",
            "Consumi": "reparto CANTINA",
            "Coperti": "n/a (bar standalone) o lunch+dinner per drink al pasto",
            "KPI primary": "Beverage cost % (target 10-30%)",
        },
    ])
    st.dataframe(sint, hide_index=True, use_container_width=True)

    st.info(
        "👉 Adesso vai a vedere i 3 vertical nel menu a sinistra, "
        "ognuno ha i 6 layer. Quando hai finito, in fondo trovi il link "
        "al Google Form per confermare i codici."
    )
```

- [ ] **Step 2: Refresh streamlit and verify primer**

Cliccare "🏠 Primer". Verificare:
- Tabella 3 fonti dati
- Block 6-layer mental model
- Tabella sintetica 3 vertical
- Nessun errore console

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): Primer — fonti dati + mental model 6-layer"
```

---

## Task 3: B1 — Breakfast (vertical completo 6 layer)

**Files:**
- Modify: `verticals/condges/audit_consumi_dashboard.py` — replace `render_b1_breakfast()`

- [ ] **Step 1: Implement render_b1_breakfast()**

```python
def render_b1_breakfast() -> None:
    st.title("🥐 B1 — Breakfast")
    st.markdown("Vertical breakfast multi-BU (HOTEL + RESIDENCE + ANGELINA + CVM).")

    # ── Layer 1: Ricavi ──
    st.header("Layer 1: Ricavi")
    st.caption("Codici inclusi nel bucket breakfast (proposta da confermare)")

    codici_brk_sql = (
        "'SCBKFBB', 'SCBKFHB', 'BRKADULT', 'BRKBABY', 'BRKEXT', 'BRKEXTC'"
    )
    ricavi = run_query(
        f"""
        SELECT codice,
               ANY_VALUE(descrizione) AS descrizione,
               STRING_AGG(DISTINCT business_unit_id ORDER BY business_unit_id) AS bu,
               ROUND(SUM(netto), 0) AS netto_2025
        FROM `hotelops-suite.hotelops.f_ricavi_fb`
        WHERE codice IN ({codici_brk_sql})
          AND anno = 2025
        GROUP BY codice
        ORDER BY netto_2025 DESC
        """
    )
    st.dataframe(ricavi, hide_index=True, use_container_width=True)
    ricavi_totale = float(ricavi["netto_2025"].sum())
    st.metric("Ricavi breakfast totali 2025", f"€ {ricavi_totale:,.0f}".replace(",", "."))

    # ── Layer 2: Consumi ──
    st.header("Layer 2: Consumi")
    st.caption("Reparto economato BRK (mensile per prodotto)")

    cost_brk = run_query(
        """
        SELECT anno,
               COUNT(DISTINCT codice_prodotto) AS n_prodotti,
               COUNT(*) AS righe,
               ROUND(SUM(importo), 0) AS cost
        FROM `hotelops-suite.hotelops.f_consumi_economato`
        WHERE reparto_id = 'BRK'
          AND NOT (anno = 2025 AND mese = 5 AND importo < 0)
        GROUP BY anno
        ORDER BY anno
        """
    )
    st.dataframe(cost_brk, hide_index=True, use_container_width=True)
    cost_totale = float(cost_brk[cost_brk["anno"] == 2025]["cost"].iloc[0])

    # ── Layer 3: Coperti ──
    st.header("Layer 3: Coperti")
    st.caption("Tipo pasto BRK (tutte BU)")

    coperti = run_query(
        """
        SELECT anno, business_unit_id,
               SUM(n_coperti) AS coperti
        FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
        WHERE tipo_pasto = 'BRK'
          AND anno = 2025
        GROUP BY anno, business_unit_id
        ORDER BY coperti DESC
        """
    )
    st.dataframe(coperti, hide_index=True, use_container_width=True)
    pax_totale = int(coperti["coperti"].sum())
    st.metric("Coperti breakfast 2025", f"{pax_totale:,}".replace(",", "."))

    # ── Layer 4: KPI ──
    st.header("Layer 4: KPI normalizzati")
    col1, col2, col3 = st.columns(3)
    kpi_cost_pax = cost_totale / pax_totale if pax_totale else 0
    kpi_ricavo_pax = ricavi_totale / pax_totale if pax_totale else 0
    kpi_fc = cost_totale / ricavi_totale if ricavi_totale else 0
    col1.metric("€ cost/coperto", f"€ {kpi_cost_pax:.2f}")
    col2.metric("€ ricavo/coperto", f"€ {kpi_ricavo_pax:.2f}")
    col3.metric("Food cost %", f"{kpi_fc*100:.1f}%")

    # ── Layer 5: Range industria ──
    st.header("Layer 5: Range industria — buffet hotel 4*")
    range_df = pd.DataFrame([
        {"Indicatore": "€ cost/pax", "Target": "€4-6", "Warning": "€6-8", "Investigate": ">€8 o <€3"},
        {"Indicatore": "€ ricavo/pax (scorporo)", "Target": "€8-12", "Warning": "€7-8 o €12-15", "Investigate": "<€7 o >€15"},
        {"Indicatore": "Food cost %", "Target": "30-50%", "Warning": "50-60%", "Investigate": ">60% o <30%"},
    ])
    st.dataframe(range_df, hide_index=True, use_container_width=True)

    # ── Layer 6: Alert ──
    st.header("Layer 6: Alert vs range")
    alert_df = pd.DataFrame([
        {"KPI": "€ cost/pax", "Valore": f"€ {kpi_cost_pax:.2f}",
         "Status": alert_color(kpi_cost_pax, 4.0, 6.0, 8.0)},
        {"KPI": "€ ricavo/pax", "Valore": f"€ {kpi_ricavo_pax:.2f}",
         "Status": alert_color(kpi_ricavo_pax, 8.0, 12.0, 15.0)},
        {"KPI": "Food cost %", "Valore": f"{kpi_fc*100:.1f}%",
         "Status": alert_color(kpi_fc*100, 30.0, 50.0, 60.0)},
    ])
    st.dataframe(alert_df, hide_index=True, use_container_width=True)
    st.caption("🟢 nel target · 🟡 warning · 🔴 investigate")

    # ── Andamento mensile ──
    st.header("Andamento mensile 2025")
    monthly = run_query(
        """
        SELECT mese,
               ROUND(costo_breakfast, 0) AS cost,
               pax_breakfast AS pax,
               ROUND(ricavi_breakfast, 0) AS ricavo
        FROM `hotelops-suite.hotelops.v_fb_kpi`
        WHERE anno = 2025 AND mese BETWEEN 4 AND 10
        ORDER BY mese
        """
    )
    fig = px.bar(
        monthly.melt(id_vars="mese", value_vars=["cost", "ricavo"]),
        x="mese", y="value", color="variable", barmode="group",
        labels={"mese": "Mese 2025", "value": "€", "variable": ""},
        title="Cost vs Ricavo breakfast — 2025 Apr-Oct",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Per la tua valutazione ──
    st.header("Per la tua valutazione")
    st.markdown(f"🔗 [Apri il Google Form — sezione B1 Breakfast]({FORM_URL})")
```

- [ ] **Step 2: Refresh streamlit and verify B1 page**

Cliccare "🥐 B1 — Breakfast". Verificare i 6 layer + andamento mensile + link Form.

Cross-check numerico atteso 2025:
- Ricavi breakfast ~€240k (HOTEL ~€236k SCBKFBB + briciole RES/ANG/CVM)
- Cost BRK ~€244k (post-storni esclusi)
- Coperti BRK ~24k
- €/coperto cost ~€10, ricavo ~€10, FC ~100% — fuori range investigate 🔴

(Aprile 2026 dovrebbe essere ~€4 cost/pax e ~€10 ricavo/pax — testarlo nel Task 8 smoke)

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): B1 Breakfast — 6 layer canonical"
```

---

## Task 4: B2 — Ristorante (vertical 6 layer)

**Files:**
- Modify: `verticals/condges/audit_consumi_dashboard.py` — replace `render_b2_ristorante()`

- [ ] **Step 1: Implement render_b2_ristorante()**

```python
def render_b2_ristorante() -> None:
    st.title("🍽️ B2 — Ristorante")
    st.markdown(
        "Vertical ristorante: ricavi food da pranzo, cena, bar, banchetti, eventi. "
        "Cost dal reparto CUCINA."
    )

    # ── Layer 1: Ricavi ──
    st.header("Layer 1: Ricavi food (multi-codice)")

    codici_food = (
        "'RISLFOOD', 'RISDFOOD', 'RISTLUNC', 'RISTDINN', 'DINFOOD', 'LUNBAR', "
        "'RISBFOOD', 'BAN', 'ROOMSERV', "
        "'FERRAD', 'FERRBA', 'PASQAD', 'PARTY', 'BRUNCH', 'APERIDIN'"
    )
    ricavi = run_query(
        f"""
        SELECT codice,
               ANY_VALUE(descrizione) AS descrizione,
               STRING_AGG(DISTINCT business_unit_id ORDER BY business_unit_id) AS bu,
               ROUND(SUM(netto), 0) AS netto_2025
        FROM `hotelops-suite.hotelops.f_ricavi_fb`
        WHERE codice IN ({codici_food})
          AND anno = 2025
        GROUP BY codice
        HAVING SUM(netto) > 0
        ORDER BY netto_2025 DESC
        """
    )
    st.dataframe(ricavi, hide_index=True, use_container_width=True)
    ricavi_totale = float(ricavi["netto_2025"].sum())
    st.metric("Ricavi ristorante totali 2025", f"€ {ricavi_totale:,.0f}".replace(",", "."))

    # ── Layer 2: Consumi ──
    st.header("Layer 2: Consumi reparto CUCINA")
    cost_cuc = run_query(
        """
        SELECT anno,
               COUNT(DISTINCT codice_prodotto) AS n_prodotti,
               COUNT(*) AS righe,
               ROUND(SUM(importo), 0) AS cost
        FROM `hotelops-suite.hotelops.f_consumi_economato`
        WHERE reparto_id = 'CUCINA'
          AND NOT (anno = 2025 AND mese = 5 AND importo < 0)
        GROUP BY anno
        ORDER BY anno
        """
    )
    st.dataframe(cost_cuc, hide_index=True, use_container_width=True)
    cost_totale = float(cost_cuc[cost_cuc["anno"] == 2025]["cost"].iloc[0])

    # ── Layer 3: Coperti ──
    st.header("Layer 3: Coperti (lunch + dinner)")
    coperti = run_query(
        """
        SELECT anno, tipo_pasto, business_unit_id,
               SUM(n_coperti) AS coperti
        FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
        WHERE tipo_pasto IN ('LUNCH', 'DINNER')
          AND anno = 2025
        GROUP BY anno, tipo_pasto, business_unit_id
        ORDER BY coperti DESC
        """
    )
    st.dataframe(coperti, hide_index=True, use_container_width=True)
    pax_totale = int(coperti["coperti"].sum())
    st.metric("Coperti ristorante 2025", f"{pax_totale:,}".replace(",", "."))

    # ── Layer 4: KPI ──
    st.header("Layer 4: KPI normalizzati")
    col1, col2, col3 = st.columns(3)
    kpi_cost_pax = cost_totale / pax_totale if pax_totale else 0
    kpi_ricavo_pax = ricavi_totale / pax_totale if pax_totale else 0
    kpi_fc = cost_totale / ricavi_totale if ricavi_totale else 0
    col1.metric("€ cost/coperto", f"€ {kpi_cost_pax:.2f}")
    col2.metric("€ ricavo/coperto", f"€ {kpi_ricavo_pax:.2f}")
    col3.metric("Food cost %", f"{kpi_fc*100:.1f}%")

    # ── Layer 5: Range industria ──
    st.header("Layer 5: Range industria")
    range_df = pd.DataFrame([
        {"Tipo struttura": "🍕 Pizzeria", "Food cost target": "~15%"},
        {"Tipo struttura": "🍝 Ristorante medio", "Food cost target": "25-35%"},
        {"Tipo struttura": "⭐⭐⭐ Michelin 3 stelle", "Food cost target": "~38%"},
        {"Tipo struttura": "🎯 Target Panorama (atteso)", "Food cost target": "25-35%"},
        {"Tipo struttura": "⚠️ Warning", "Food cost target": ">40%"},
        {"Tipo struttura": "🚨 Investigate", "Food cost target": ">50-60%"},
    ])
    st.dataframe(range_df, hide_index=True, use_container_width=True)

    # ── Layer 6: Alert ──
    st.header("Layer 6: Alert vs range")
    alert_df = pd.DataFrame([
        {"KPI": "Food cost %", "Valore": f"{kpi_fc*100:.1f}%",
         "Status": alert_color(kpi_fc*100, 25.0, 35.0, 50.0)},
        {"KPI": "€ cost/coperto", "Valore": f"€ {kpi_cost_pax:.2f}",
         "Status": "ℹ️ (no range fisso)"},
        {"KPI": "€ ricavo/coperto", "Valore": f"€ {kpi_ricavo_pax:.2f}",
         "Status": "ℹ️ (no range fisso)"},
    ])
    st.dataframe(alert_df, hide_index=True, use_container_width=True)
    st.caption("🟢 nel target · 🟡 warning · 🔴 investigate")

    st.subheader("Possibili cause food cost >50-60%")
    st.markdown(
        """
- pricing sbagliato
- porzioni eccessive
- furto
- sprechi
- mix prodotti (es. troppo pesce vs carne)
- menu engineering
- eventi sottocosto
- ricavi incompleti (es. cose pagate fuori sistema)
- consumi caricati male (es. cucina che assorbe banchetti senza separazione)
"""
    )

    # ── Andamento mensile ──
    st.header("Andamento mensile 2025")
    monthly = run_query(
        """
        SELECT mese,
               ROUND(costo_alacarte, 0) AS cost,
               ROUND(ricavi_alacarte_totali, 0) AS ricavo
        FROM `hotelops-suite.hotelops.v_fb_kpi`
        WHERE anno = 2025 AND mese BETWEEN 4 AND 10
        ORDER BY mese
        """
    )
    fig = px.bar(
        monthly.melt(id_vars="mese", value_vars=["cost", "ricavo"]),
        x="mese", y="value", color="variable", barmode="group",
        labels={"mese": "Mese 2025", "value": "€", "variable": ""},
        title="Cost CUCINA vs Ricavo ristorante — 2025 Apr-Oct",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.header("Per la tua valutazione")
    st.markdown(f"🔗 [Apri il Google Form — sezione B2 Ristorante]({FORM_URL})")
```

- [ ] **Step 2: Refresh streamlit and verify B2 page**

Cliccare "🍽️ B2". Verificare 6 layer + cause possibili + chart mensile.

Cross-check numerico atteso 2025:
- Ricavi food ~€135-200k (a seconda di se include BAR/eventi)
- Cost CUCINA ~€49k
- Coperti lunch+dinner ~3.6k
- FC ~25-37% (target 🟢 o appena fuori 🟡)

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): B2 Ristorante — 6 layer + range pizzeria/medio/michelin"
```

---

## Task 5: B3 — Bar / Beverage (vertical 6 layer)

**Files:**
- Modify: `verticals/condges/audit_consumi_dashboard.py` — replace `render_b3_bar()`

- [ ] **Step 1: Implement render_b3_bar()**

```python
def render_b3_bar() -> None:
    st.title("🍷 B3 — Bar / Beverage")
    st.markdown(
        "Vertical drink: bar standalone + bevande pranzo/cena + drink banchetti. "
        "Cost dal reparto CANTINA."
    )
    st.warning(
        "⚠️ Il beverage è il vertical più falsato: complimentary, staff drinks, "
        "eventi, minibar, stock movement, inventario inaccurato. Trattare con cautela."
    )

    # ── Layer 1: Ricavi ──
    st.header("Layer 1: Ricavi beverage")
    codici_bev = (
        "'BAR', 'BARHOTEL', 'RISLBEVE', 'RISLBEV', 'RISDBEV', 'DINBEV', "
        "'BANB', 'PROSECCO'"
    )
    ricavi = run_query(
        f"""
        SELECT codice,
               ANY_VALUE(descrizione) AS descrizione,
               STRING_AGG(DISTINCT business_unit_id ORDER BY business_unit_id) AS bu,
               ROUND(SUM(netto), 0) AS netto_2025
        FROM `hotelops-suite.hotelops.f_ricavi_fb`
        WHERE codice IN ({codici_bev})
          AND anno = 2025
        GROUP BY codice
        HAVING SUM(netto) > 0
        ORDER BY netto_2025 DESC
        """
    )
    st.dataframe(ricavi, hide_index=True, use_container_width=True)
    ricavi_totale = float(ricavi["netto_2025"].sum())
    st.metric("Ricavi beverage totali 2025", f"€ {ricavi_totale:,.0f}".replace(",", "."))

    # ── Layer 2: Consumi ──
    st.header("Layer 2: Consumi reparto CANTINA")
    cost_cant = run_query(
        """
        SELECT anno,
               COUNT(DISTINCT codice_prodotto) AS n_prodotti,
               COUNT(*) AS righe,
               ROUND(SUM(importo), 0) AS cost
        FROM `hotelops-suite.hotelops.f_consumi_economato`
        WHERE reparto_id = 'CANTINA'
          AND NOT (anno = 2025 AND mese = 5 AND importo < 0)
        GROUP BY anno
        ORDER BY anno
        """
    )
    st.dataframe(cost_cant, hide_index=True, use_container_width=True)
    cost_totale = float(cost_cant[cost_cant["anno"] == 2025]["cost"].iloc[0])

    # ── Layer 3: Coperti (proxy) ──
    st.header("Layer 3: Coperti (proxy lunch + dinner)")
    st.caption("Il drink al pasto è il caso più frequente — usiamo coperti lunch+dinner come proxy")
    coperti = run_query(
        """
        SELECT anno, tipo_pasto,
               SUM(n_coperti) AS coperti
        FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
        WHERE tipo_pasto IN ('LUNCH', 'DINNER')
          AND anno = 2025
        GROUP BY anno, tipo_pasto
        """
    )
    st.dataframe(coperti, hide_index=True, use_container_width=True)
    pax_totale = int(coperti["coperti"].sum())

    # ── Layer 4: KPI ──
    st.header("Layer 4: KPI normalizzati")
    col1, col2, col3 = st.columns(3)
    kpi_cost_pax = cost_totale / pax_totale if pax_totale else 0
    kpi_ricavo_pax = ricavi_totale / pax_totale if pax_totale else 0
    kpi_fc = cost_totale / ricavi_totale if ricavi_totale else 0
    col1.metric("€ cost/coperto (proxy)", f"€ {kpi_cost_pax:.2f}")
    col2.metric("€ ricavo/coperto (proxy)", f"€ {kpi_ricavo_pax:.2f}")
    col3.metric("Beverage cost %", f"{kpi_fc*100:.1f}%")

    # ── Layer 5: Range industria ──
    st.header("Layer 5: Range industria beverage")
    range_df = pd.DataFrame([
        {"Tipo": "💧 Beverage basic (acqua, bevande analcoliche)", "Cost target": "10-15%"},
        {"Tipo": "🍷 Beverage medio (vino, cocktail standard)", "Cost target": "15-25%"},
        {"Tipo": "🥃 Top-tier (alcolici premium, vini importanti)", "Cost target": "25-30%"},
        {"Tipo": "🎯 Target Panorama (atteso hotel mix)", "Cost target": "15-25%"},
        {"Tipo": "⚠️ Warning", "Cost target": ">30%"},
        {"Tipo": "🚨 Investigate", "Cost target": ">40% o <10%"},
    ])
    st.dataframe(range_df, hide_index=True, use_container_width=True)

    # ── Layer 6: Alert ──
    st.header("Layer 6: Alert vs range")
    alert_df = pd.DataFrame([
        {"KPI": "Beverage cost %", "Valore": f"{kpi_fc*100:.1f}%",
         "Status": alert_color(kpi_fc*100, 15.0, 25.0, 40.0)},
    ])
    st.dataframe(alert_df, hide_index=True, use_container_width=True)
    st.caption("🟢 nel target · 🟡 warning · 🔴 investigate")

    # ── Andamento mensile ──
    st.header("Andamento mensile 2025")
    monthly = run_query(
        """
        SELECT mese,
               ROUND(SUM(CASE WHEN reparto_id='CANTINA' THEN importo END), 0) AS cost
        FROM `hotelops-suite.hotelops.f_consumi_economato`
        WHERE anno = 2025 AND mese BETWEEN 4 AND 10
          AND NOT (anno = 2025 AND mese = 5 AND importo < 0)
        GROUP BY mese
        ORDER BY mese
        """
    )
    fig = px.bar(
        monthly, x="mese", y="cost",
        labels={"mese": "Mese 2025", "cost": "Cost CANTINA (€)"},
        title="Cost reparto CANTINA — 2025 Apr-Oct",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.header("Per la tua valutazione")
    st.markdown(f"🔗 [Apri il Google Form — sezione B3 Bar/Beverage]({FORM_URL})")
```

- [ ] **Step 2: Refresh streamlit and verify B3 page**

Cliccare "🍷 B3". Verificare warning beverage falsità + 6 layer + chart mensile.

Cross-check numerico atteso 2025:
- Ricavi beverage ~€110-120k (BAR €76k + altri bev)
- Cost CANTINA ~€35k
- Beverage cost % ~30% (range warning 🟡 o target alto 🟢)

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): B3 Bar/Beverage — 6 layer + warning falsità beverage"
```

---

## Task 6: Anomalie FYI page

**Files:**
- Modify: `verticals/condges/audit_consumi_dashboard.py` — replace `render_anomalie()`

- [ ] **Step 1: Implement render_anomalie()**

```python
def render_anomalie() -> None:
    st.title("⚠️ Anomalie FYI")
    st.markdown(
        "Non sono domande primarie. Ti facciamo sapere cosa abbiamo notato "
        "nei dati, ci basta una conferma rapida nel Form."
    )

    anomalie = pd.DataFrame([
        {
            "ID": "FYI-1",
            "Anomalia": "Storni UoM maggio 2025",
            "Cosa abbiamo notato": "15 righe negative -€166k su BRK/CUCINA/CANTINA in maggio 2025",
            "La nostra ipotesi": "Confusione kg vs grammi (caffè in grani comprato in kg, consumato in g)",
            "Implicazione": "Già flaggate is_anomalia, escluse di default dai KPI",
        },
        {
            "ID": "FYI-2",
            "Anomalia": "BANCHETTI reparto sotto-stimato",
            "Cosa abbiamo notato": "Cost €1.2k vs Revenue BAN €17k = food cost implicito 7%",
            "La nostra ipotesi": "Il cibo dei banchetti esce da CUCINA mescolato col ristorante",
            "Implicazione": "Non separabile a livello mensile, restano aggregati in B2",
        },
        {
            "ID": "FYI-3",
            "Anomalia": "BAR_HOTEL reparto vuoto",
            "Cosa abbiamo notato": "7 righe €0 cost vs revenue BAR €76k",
            "La nostra ipotesi": "Drink bar usa stock CANTINA, no magazzino dedicato",
            "Implicazione": "B3 unifica BAR_HOTEL+CANTINA come fonte cost",
        },
        {
            "ID": "FYI-4",
            "Anomalia": "Codici da sospendere",
            "Cosa abbiamo notato": "17 codici marcati 'da sospendere' nel tuo file `pianodeicontilavoro.xlsx`",
            "La nostra ipotesi": "Forward-only deprecati, storico mantenuto",
            "Implicazione": "Filtriamo da default Looker",
        },
        {
            "ID": "FYI-5",
            "Anomalia": "Codici orfani",
            "Cosa abbiamo notato": "ACCFCI (Acconto Fuori Campo Iva) €252 non in classe nota",
            "La nostra ipotesi": "Legacy, va in 07DIV o classe nuova",
            "Implicazione": "Trattati come '(da mappare)'",
        },
        {
            "ID": "FYI-6",
            "Anomalia": "Reparti operativi non-F&B",
            "Cosa abbiamo notato": "DIPEND €22k, HSK* €60k, MAN* €10k, DIREZIONE €13k, DEPERIMENTO €6k, D* dotazioni",
            "La nostra ipotesi": "Sono costi operativi reali (non food cost), vivono fuori P&L F&B",
            "Implicazione": "Pagina dashboard separata 'Costi operativi non-F&B'",
        },
        {
            "ID": "FYI-7",
            "Anomalia": "Carico magazzino stagionale",
            "Cosa abbiamo notato": "Picco cost BRK luglio €76k, €/coperto oscilla €3.6-€12.5",
            "La nostra ipotesi": "Acquisti concentrati luglio per servire fino a settembre",
            "Implicazione": "Lettura trimestrale > mensile per BRK",
        },
    ])
    st.dataframe(anomalie, hide_index=True, use_container_width=True)

    st.header("Per la tua valutazione")
    st.markdown(
        f"🔗 [Apri il Google Form — sezione Anomalie FYI]({FORM_URL})\n\n"
        "Per ogni anomalia: ✓ confermo / ✗ no + note opzionali."
    )
```

- [ ] **Step 2: Refresh and verify**

Cliccare "⚠️ Anomalie FYI". Verifica tabella 7 anomalie + link Form.

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): Anomalie FYI — 7 osservazioni rapide"
```

---

## Task 7: Recap + Form link page

**Files:**
- Modify: `verticals/condges/audit_consumi_dashboard.py` — replace `render_recap()`

- [ ] **Step 1: Implement render_recap()**

```python
def render_recap() -> None:
    st.title("📋 Recap + Form")
    st.markdown(
        "Grazie per aver navigato i 3 vertical + le anomalie. Adesso il prossimo "
        "passo è confermare i codici nel Google Form."
    )

    st.header("Cosa ti chiediamo nel Form")
    riepilogo = pd.DataFrame([
        {"Sezione": "S1 — Breakfast", "Cosa chiediamo": "Conferma codici ricavi + se aggregare BU"},
        {"Sezione": "S2 — Ristorante", "Cosa chiediamo": "Conferma codici food + dove vanno eventi e RISBFOOD"},
        {"Sezione": "S3 — Bar/Beverage", "Cosa chiediamo": "Conferma codici drink + se BARHOTEL=BAR"},
        {"Sezione": "S4 — Coperti mapping", "Cosa chiediamo": "Fonte coperti corretta + clienti vs esterni"},
        {"Sezione": "S5 — Range operativi", "Cosa chiediamo": "Target tuoi food/beverage cost per Panorama"},
        {"Sezione": "S6 — Anomalie FYI", "Cosa chiediamo": "Conferma rapida ✓/✗ per le 7 osservazioni"},
        {"Sezione": "S7 — Catch-all", "Cosa chiediamo": "Cosa manca? Codici da aggiungere?"},
    ])
    st.dataframe(riepilogo, hide_index=True, use_container_width=True)

    st.header("👉 Apri il Google Form")
    st.markdown(f"### 📝 [Clicca qui per rispondere]({FORM_URL})")
    st.caption(
        "Il link è un placeholder finché non generi la Form via Apps Script "
        "(`verticals/condges/audit_form.gs`). Una volta creata, aggiorna "
        "`FORM_URL` in `audit_consumi_dashboard.py`."
    )

    st.header("Cosa succede dopo")
    st.markdown(
        """
1. Le tue risposte vanno in un Google Sheet collegato alla Form
2. Stefano legge le risposte
3. Aggiorniamo il modello F&B (lista codici per vertical, range target)
4. Round successivo (se serve):
   - Chef per matrice categoria_prodotto → ricetta (KPI quantità/coperto)
   - POS Ristocube per separare drink bar/ristorante/banchetti

Grazie!
"""
    )
```

- [ ] **Step 2: Refresh and verify**

Cliccare "📋 Recap". Verifica tabella 7 sezioni + CTA Form + cosa-succede-dopo.

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "feat(audit): Recap page con link Form e sezioni preview"
```

---

## Task 8: Google Apps Script audit_form.gs

**Files:**
- Create: `verticals/condges/audit_form.gs`

- [ ] **Step 1: Write Apps Script**

```javascript
/**
 * Audit consumi F&B per la direzione — Hotel Panorama.
 *
 * Genera Google Form con 8 sezioni: Identità + 3 vertical + Coperti
 * mapping + Range operativi + Anomalie FYI + Catch-all.
 *
 * Setup:
 * 1. Vai su https://script.google.com
 * 2. Nuovo progetto
 * 3. Incolla TUTTO questo file
 * 4. Salva (Cmd+S)
 * 5. Esegui createAuditForm() (icona play)
 * 6. Autorizza Google Drive/Forms
 * 7. View > Logs (Cmd+Enter) → URL della Form + Sheet collegato
 * 8. Aggiorna FORM_URL in audit_consumi_dashboard.py
 */

function createAuditForm() {
  var form = FormApp.create('Audit consumi F&B — Hotel Panorama');
  form.setDescription(
    'Conferma i codici proposti per i 3 vertical F&B (Breakfast/Ristorante/Bar). ' +
    'Apri prima la Streamlit audit per vedere i numeri.'
  );
  form.setCollectEmail(true);
  form.setAllowResponseEdits(true);

  // --- S0: Identità
  form.addSectionHeaderItem().setTitle('Identità');
  form.addTextItem().setTitle('Nome e ruolo').setRequired(true);
  form.addDateItem().setTitle('Data di compilazione').setRequired(true);

  // --- S1: B1 Breakfast
  form.addPageBreakItem()
    .setTitle('S1 — Breakfast')
    .setHelpText('Vedi Streamlit pagina B1 Breakfast prima di rispondere.');

  form.addCheckboxItem()
    .setTitle('Quali codici TENI nel bucket Breakfast?')
    .setChoiceValues([
      'SCBKFBB — Scorpori Breakfast B&B (HOTEL)',
      'SCBKFHB — Scorpori Breakfast HB (CVM)',
      'BRKADULT — Breakfast Adult',
      'BRKBABY — Breakfast Child',
      'BRKEXT — Breakfast Esterni Adult',
      'BRKEXTC — Breakfast Esterni Child',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Le 4 BU (HOTEL+RES+ANG+CVM) le aggreghi tutte o le tieni separate?')
    .setChoiceValues([
      'a) Aggregate tutte in un unico bucket breakfast',
      'b) Separate per BU (HOTEL breakfast, RES breakfast, ANG breakfast, CVM breakfast)',
      'c) Solo HOTEL+CVM (RES e ANG non hanno breakfast vero)',
      'd) Altro',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Codici breakfast da aggiungere o note');

  // --- S2: B2 Ristorante
  form.addPageBreakItem()
    .setTitle('S2 — Ristorante')
    .setHelpText('Vedi Streamlit pagina B2 Ristorante prima di rispondere.');

  form.addCheckboxItem()
    .setTitle('Quali codici TENI nel bucket Ristorante Food?')
    .setChoiceValues([
      'RISLFOOD — Risto Lunch Food',
      'RISDFOOD — Risto Dinner Food',
      'RISTLUNC — Restaurant Lunch manuale',
      'RISTDINN — Restaurant Dinner manuale',
      'DINFOOD — Dinner Food generico',
      'LUNBAR — Lunch Bar',
      'RISBFOOD — Risto Bar Food',
      'BAN — Banqueting Food',
      'ROOMSERV — Room Service',
      'FERRAD — Party Ferragosto Adulti',
      'FERRBA — Party Ferragosto Bambini',
      'PASQAD — Pranzo di Pasqua',
      'PARTY — Party generico',
      'BRUNCH — Brunch Buffet',
      'APERIDIN — Aperidinner',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Gli eventi (FERRAD/FERRBA/PASQAD/PARTY/BRUNCH/APERIDIN) vanno…')
    .setChoiceValues([
      'a) Dentro B2 Ristorante (mescolati col regolare)',
      'b) Bucket "Eventi" separato',
      'c) Esclusi dal F&B (sono one-off)',
      'd) Misto',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('RISBFOOD (Risto Bar Food) — è food o bar?')
    .setChoiceValues([
      'a) Food (va in B2)',
      'b) Bar (va in B3)',
      'c) Misto',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Codici ristorante da aggiungere o note');

  // --- S3: B3 Bar/Beverage
  form.addPageBreakItem()
    .setTitle('S3 — Bar / Beverage')
    .setHelpText('Vedi Streamlit pagina B3 prima di rispondere.');

  form.addCheckboxItem()
    .setTitle('Quali codici TENI nel bucket Bar/Beverage?')
    .setChoiceValues([
      'BAR — Bar generico',
      'BARHOTEL — Bar Hotel',
      'RISLBEVE — Risto Lunch Beverage',
      'RISLBEV — Risto Lunch Beverage (variant)',
      'RISDBEV — Risto Dinner Beverage',
      'DINBEV — Dinner Beverage',
      'BANB — Banqueting Beverage',
      'PROSECCO — Bottiglia Prosecco',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('BARHOTEL e BAR sono lo stesso codice o due diversi?')
    .setChoiceValues([
      'a) Stesso, fondiamoli',
      'b) Diversi (BARHOTEL = bar dell hotel, BAR = generico)',
      'c) Non lo so, da verificare',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Codici beverage da aggiungere o note');

  // --- S4: Coperti mapping
  form.addPageBreakItem()
    .setTitle('S4 — Coperti mapping')
    .setHelpText('Da dove leggi i coperti accurati?');

  form.addMultipleChoiceItem()
    .setTitle('Fonte coperti più accurata')
    .setChoiceValues([
      'a) Hoxell',
      'b) Excel syncato (Google Sheet RistoCube)',
      'c) Entrambi',
      'd) Altro',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Coperti BRK includono…')
    .setChoiceValues([
      'a) Solo clienti hotel B&B',
      'b) Clienti hotel B&B + esterni paganti (BRKADULT/EXT)',
      'c) Anche staff/dipendenti',
      'd) Altro',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Coperti LUNCH e DINNER sono separati?')
    .setChoiceValues([
      'a) Sì, sempre',
      'b) No, brunch e altri ibridi non distinti',
      'c) Solo lunch+dinner regolari, eventi conta a parte',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Note coperti');

  // --- S5: Range operativi
  form.addPageBreakItem()
    .setTitle('S5 — Range operativi')
    .setHelpText('Quali sono i tuoi target food/beverage cost realistici?');

  form.addMultipleChoiceItem()
    .setTitle('Target Food cost ristorante Panorama (auto-valutazione)')
    .setChoiceValues([
      'a) Pizzeria-level (~15%) — siamo molto economici',
      'b) Ristorante medio (25-35%) — siamo standard',
      'c) Top-tier (~38%) — siamo premium',
      'd) Altro (specifica nelle note)',
    ])
    .setRequired(false);

  form.addMultipleChoiceItem()
    .setTitle('Target Beverage cost Panorama')
    .setChoiceValues([
      'a) Basic (10-15%)',
      'b) Medio (15-25%)',
      'c) Top-tier (25-30%)',
    ])
    .setRequired(false);

  form.addParagraphTextItem().setTitle('Target personali / esperienza diretta');

  // --- S6: Anomalie FYI
  form.addPageBreakItem()
    .setTitle('S6 — Anomalie FYI')
    .setHelpText('Conferma rapida delle 7 osservazioni dalla Streamlit.');

  var anomalie = [
    'FYI-1 — Storni UoM maggio 2025 (15 righe -€166k)',
    'FYI-2 — BANCHETTI reparto sotto-stimato vs revenue BAN',
    'FYI-3 — BAR_HOTEL reparto vuoto (drink da CANTINA)',
    'FYI-4 — 17 codici "da sospendere" da pianodeicontilavoro.xlsx',
    'FYI-5 — Codice orfano ACCFCI (€252) da classificare',
    'FYI-6 — Reparti non-F&B (DIPEND/HSK/MAN/etc) gestiti separati',
    'FYI-7 — Carico magazzino stagionale BRK luglio',
  ];
  for (var i = 0; i < anomalie.length; i++) {
    form.addMultipleChoiceItem()
      .setTitle(anomalie[i])
      .setChoiceValues(['✓ confermo', '✗ no, da rivedere', 'non lo so'])
      .setRequired(false);
  }
  form.addParagraphTextItem().setTitle('Note generali sulle anomalie');

  // --- S7: Catch-all
  form.addPageBreakItem().setTitle('S7 — Catch-all');
  form.addParagraphTextItem()
    .setTitle("C'è qualcosa che dovremmo guardare e non stiamo guardando? Codici/situazioni mancanti?");

  // Collega Google Sheet auto
  var ss = SpreadsheetApp.create('Audit consumi F&B — Risposte');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  Logger.log('Form URL: ' + form.getPublishedUrl());
  Logger.log('Form edit URL: ' + form.getEditUrl());
  Logger.log('Spreadsheet URL: ' + ss.getUrl());
}
```

- [ ] **Step 2: (Manual) test on script.google.com**

Stefano:
1. https://script.google.com → nuovo progetto
2. Incolla file
3. Salva, runna `createAuditForm()`
4. Autorizza Google
5. View > Logs → ottieni URL Form + Sheet
6. Apri Form e verifica 8 sezioni con domande corrette

- [ ] **Step 3: Commit**

```bash
git add verticals/condges/audit_form.gs
git commit -m "feat(audit): Apps Script Google Form 8 sezioni (S0-S7)"
```

---

## Task 9: Workflow documentation

**Files:**
- Create: `docs/audit_consumi_workflow.md`

- [ ] **Step 1: Write workflow doc**

```markdown
# Audit consumi F&B — Workflow

Strumento per raccogliere dalla direzione di Hotel Panorama l'interpretazione
del primo modello F&B (canonical-transformation-matrix a 6 layer × 3 vertical).

## Setup iniziale (1 volta)

1. **Genera Google Form** — Stefano:
   - Apri `verticals/condges/audit_form.gs`
   - Copia su https://script.google.com (nuovo progetto)
   - Esegui `createAuditForm()`, autorizza
   - Nei Log trovi `Form URL` + `Spreadsheet URL`
2. **Aggiorna `FORM_URL`** in `verticals/condges/audit_consumi_dashboard.py` con
   l'URL reale ottenuto
3. Commit del cambio

## Esecuzione audit

1. Stefano apre la Streamlit:
   ```bash
   streamlit run verticals/condges/audit_consumi_dashboard.py
   ```
2. Condivide URL (locale o tunnel) + link Form al direttore
3. Direttore:
   - Apre la Streamlit (~5 min Primer + ~15 min B1/B2/B3 + ~5 min anomalie)
   - Apre il Google Form e risponde (~15 min)
   - Tempo totale: 30-40 min

## Post-risposte

1. Stefano apre il Google Sheet collegato alla Form
2. Esporta CSV o copia/incolla risposte
3. Insieme a Claude:
   - **S1-S3 (vertical codici)**: aggiorniamo lista codici nelle SQL di
     `v_fb_kpi` o nuove view
   - **S4 (coperti)**: aggiorniamo logica per leggere coperti dalla fonte
     corretta (Hoxell vs Sheet)
   - **S5 (range)**: aggiorniamo `target_lo/target_hi/warning_hi` nei semafori
     della dashboard
   - **S6 (anomalie FYI)**: applichiamo i fix confermati, riapriamo quelle
     non confermate
   - **S7 (catch-all)**: nuove pagine/vertical/KPI se emergono
4. Stefano approva i cambi → implementazione

## File coinvolti

| File | Tipo | Scopo |
|---|---|---|
| `verticals/condges/audit_consumi_dashboard.py` | Streamlit | Read-only viewer 6 pagine |
| `verticals/condges/audit_form.gs` | Apps Script | Google Form 8 sezioni |
| `docs/superpowers/specs/2026-05-21-audit-consumi-fb-direzione-design.md` | Spec | Design canonical-transformation-matrix |
| `docs/superpowers/plans/2026-05-21-audit-consumi-fb-direzione.md` | Plan | Questo piano |

## Round successivi (out of scope ora)

- Chef → matrice `categoria_prodotto` → ricetta (KPI quantità/coperto)
- POS Ristocube → separare drink bar/ristorante/banchetti
- Streamlit Cloud hosting per accesso remoto direttore

## Possibili esiti dell'audit (azionabili)

- **Modifiche al piano dei conti HotelCube** (manuali, no API): ricalibrare
  scorporo SCBKFBB, sospendere codici ufficialmente, aggiungere scorporo cena,
  riclassificare codici orfani
- **Modifiche operative**: separazione magazzino banchetti, riduzione waste
  breakfast, training operatori per UoM, ecc.
- **Modifiche alla dashboard Looker**: filtri default, nuove pagine "Costi
  operativi non-F&B", soglie alert calibrate sui target del direttore
```

- [ ] **Step 2: Commit**

```bash
git add docs/audit_consumi_workflow.md
git commit -m "docs(audit): workflow setup + esecuzione + post-risposte"
```

---

## Task 10: Final smoke test

**Files:** nessuno

- [ ] **Step 1: Run Streamlit and click through all 6 pages**

```bash
streamlit run verticals/condges/audit_consumi_dashboard.py
```

Per ogni pagina:
- ✅ Si carica senza errori console
- ✅ Tutti i 6 layer visibili (per B1/B2/B3)
- ✅ Tabelle non vuote
- ✅ Scorecard hanno numeri sensati
- ✅ Chart renderizzati

Cross-check numerico atteso 2025 (post-storni esclusi):
- **B1**: ricavi ~€240k, cost BRK ~€244k, pax BRK ~24k, FC ~100% 🔴
- **B2**: ricavi food ~€135-200k, cost CUCINA ~€49k, pax lunch+dinner ~3.6k, FC ~25-37% 🟢🟡
- **B3**: ricavi beverage ~€110k, cost CANTINA ~€35k, beverage cost ~30% 🟡

Cross-check numerico atteso aprile 2026 (apertura stagione):
- **B1 mese 4**: cost ~€4/pax, ricavo ~€10/pax, FC ~40% (dovrebbe matchare l'esempio del direttore)

- [ ] **Step 2: Manual SQL cross-check**

Verifica con query manuali:

```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT mese,
       ROUND(costo_breakfast, 0) AS cost,
       pax_breakfast AS pax,
       ROUND(costo_breakfast / NULLIF(pax_breakfast, 0), 2) AS eur_pax
FROM `hotelops-suite.hotelops.v_fb_kpi`
WHERE anno = 2026 AND mese = 4
'
```

Atteso: cost ~€13853, pax ~1929, €/pax ~€7.18 — vicino al €4 del direttore
(la differenza viene dal carico stagionale che pesa). Confermare con utente.

- [ ] **Step 3: (Optional) Generate Google Form end-to-end**

Se vuoi testare la Form:
- Esegui `createAuditForm()` su script.google.com
- Apri Form, verifica 8 sezioni
- Aggiorna `FORM_URL` in `audit_consumi_dashboard.py`

- [ ] **Step 4: Final commit if FORM_URL update**

```bash
git add verticals/condges/audit_consumi_dashboard.py
git commit -m "chore(audit): aggiorna FORM_URL con link reale"
```

---

## Self-review

✅ **Spec coverage**: ogni vertical e sezione spec coperti:
- Mental model 6-layer → Task 2 (Primer) + Task 3-5 (B1/B2/B3)
- 3 vertical → Task 3 (B1), Task 4 (B2), Task 5 (B3)
- Range industria + Alert → embedded in Task 3-5
- Anomalie FYI → Task 6
- Recap + Form → Task 7
- Google Form 8 sezioni → Task 8
- Workflow doc → Task 9
- Acceptance criteria → Task 10

✅ **Placeholder scan**: nessun TBD/TODO. `FORM_URL` placeholder documentato in Task 8/10.

✅ **Type consistency**: `render_primer`, `render_b1_breakfast`, `render_b2_ristorante`, `render_b3_bar`, `render_anomalie`, `render_recap` consistenti tra skeleton (Task 1) e implementazioni (Task 2-7). Helper `get_bq_client`, `run_query`, `alert_color` definite nel Task 1.

✅ **No tests rationale**: dichiarato in Test strategy — UI tool one-off, verifica visiva via smoke test (Task 10) + acceptance criteria.
