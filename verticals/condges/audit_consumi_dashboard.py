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

from core.config import DATASET, PROJECT

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


def render_anomalie() -> None:
    st.title("⚠️ Anomalie FYI")
    st.info("Pagina da implementare nel Task 6")


def render_recap() -> None:
    st.title("📋 Recap + Form")
    st.info("Pagina da implementare nel Task 7")


if __name__ == "__main__":
    main()
