import os

PROJECT = "hotelops-suite"
DATASET = "hotelops"

def _t(name: str) -> str:
    return f"{PROJECT}.{DATASET}.{name}"

# Fact tables
F_BANCHE_MOVIMENTI          = _t("f_banche_movimenti")
F_SALDI_BANCA_SNAPSHOT      = _t("f_saldi_banca_snapshot")
F_SALDI_BANCA_CHIUSURA_MENSILE = _t("f_saldi_banca_chiusura_mensile")
F_MOVIMENTI_CONTABILI       = _t("f_movimenti_contabili")
F_BUDGET_MENSILE            = _t("f_budget_mensile")
F_PIANO_FINANZIARIO_INPUT   = _t("f_piano_finanziario_input")
F_ACCODAMENTI               = _t("f_accodamenti")
F_BILANCINO                 = _t("f_bilancino")
F_CONSUMI_ECONOMATO         = _t("f_consumi_economato")
F_COPERTI_GIORNALIERI       = _t("f_coperti_giornalieri")
F_RICAVI_FB                 = _t("f_ricavi_fb")
F_CHIUSURA_MENSILE          = _t("f_chiusura_mensile")
F_PARTITE_APERTE_FORNITORI  = _t("f_partite_aperte_fornitori")
F_RICAVI_STORICI            = _t("f_ricavi_storici")
F_COEFFICIENTI_CONSUMO      = _t("f_coefficienti_consumo")
F_PMS_STATISTICHE           = _t("f_pms_statistiche")
F_PRODUZIONE_PMS            = _t("f_produzione_pms")
F_REVIEWS                   = _t("f_reviews")
F_APIFY_RUNS                = _t("f_apify_runs")
F_RISTOCUBE_ORDERS          = _t("f_ristocube_orders")
F_MENU_ENGINEERING          = _t("f_menu_engineering")
F_VENDITE_FB                = _t("f_vendite_fb")
F_FATTURE_RIGHE             = _t("f_fatture_righe")
F_PIPELINE_RUNS             = _t("f_pipeline_runs")
F_BILANCI_ANNUALI           = _t("f_bilanci_annuali")
F_PROGETTO_VOCI             = _t("f_progetto_voci")
F_PROGETTO_EVENTI           = _t("f_progetto_eventi")
F_SPIAGGIA_RESERVATIONS     = _t("f_spiaggia_reservations")
F_SPIAGGIA_CASH_FLOWS       = _t("f_spiaggia_cash_flows")
F_SPIAGGIA_SPOTS            = _t("f_spiaggia_spots")
F_SPIAGGIA_CORRISPETTIVI    = _t("f_spiaggia_corrispettivi")
F_SPIAGGIA_FB_ORDINI        = _t("f_spiaggia_fb_ordini")
F_PEC_MESSAGES              = _t("f_pec_messages")
F_PEC_ALLEGATI              = _t("f_pec_allegati")
F_PEC_CLASSIFICAZIONI       = _t("f_pec_classificazioni")
F_PF_ROTAZIONI              = _t("f_pf_rotazioni")
F_PRENOTAZIONI_OTB          = _t("f_prenotazioni_otb")
F_BOOKINGS_TIPOLOGIA        = _t("f_bookings_tipologia")
F_CONSPREV_MENSILE          = _t("f_consprev_mensile")

# Dimension tables
D_VOCI_PIANO_FINANZIARIO    = _t("d_voci_piano_finanziario")
D_PIANO_CONTI               = _t("d_piano_conti")
D_CATEGORIE_CONTI           = _t("d_categorie_conti")
D_FORNITORI                 = _t("d_fornitori")
D_ANAGRAFICA_FORNITORI      = _t("d_anagrafica_fornitori")
D_MAPPING_PIANO_FINANZIARIO = _t("d_mapping_piano_finanziario")
D_COEFFICIENTI_STAGIONALITA = _t("d_coefficienti_stagionalita")
D_PROGETTI                  = _t("d_progetti")
D_CAMERE                    = _t("d_camere")
D_PMS_CODICI                = _t("d_pms_codici")
D_PEC_PERSONE               = _t("d_pec_persone")

# Views
V_PIANO_FINANZIARIO_MENSILE = _t("v_piano_finanziario_mensile")
V_BUDGET_VS_CONSUNTIVO      = _t("v_budget_vs_consuntivo")
V_PIANO_FINANZIARIO_CONSUNTIVO = _t("v_piano_finanziario_consuntivo")
V_PREVISIONE_CASSA          = _t("v_previsione_cassa")
V_PL_MOVIMENTI               = _t("v_pl_movimenti")
V_CASHFLOW_MENSILE           = _t("v_cashflow_mensile")
V_INCASSI_PER_CANALE         = _t("v_incassi_per_canale")
V_BOOKING_CURVE              = _t("v_booking_curve")
V_PROGETTO_VOCI_STATO        = _t("v_progetto_voci_stato")
V_PEC_CONVERSAZIONI          = _t("v_pec_conversazioni")
V_CASH_POSITION              = _t("v_cash_position")

# Looker Studio views
V_CONDGES_BUDGET_CONSUNTIVO  = _t("v_condges_budget_consuntivo")
V_CONDGES_PF_MENSILE         = _t("v_condges_pf_mensile")
V_CONDGES_CASHFLOW           = _t("v_condges_cashflow")
V_ECONOMATO_CONSUMI          = _t("v_economato_consumi")
V_ECONOMATO_PARETO           = _t("v_economato_pareto")
V_BUDGET                     = _t("v_budget")
V_FB_KPI                     = _t("v_fb_kpi")
V_FB_CONSUMI                 = _t("v_fb_consumi")
V_FB_RICAVI                  = _t("v_fb_ricavi")
V_FB_PASTI                   = _t("v_fb_pasti")
V_CE_MENSILE_BILANCINO       = _t("v_ce_mensile_bilancino")

# ── Pannello CEO (projection PEC su Drive) — spec 2026-07-17 ─────────────────
F_PEC_PANEL_PROJECTIONS     = _t("f_pec_panel_projections")
F_PEC_DIGEST_RUNS           = _t("f_pec_digest_runs")

# Whitelist POSITIVA delle entity ammesse nel pannello (I-PEC-3): una entity
# nuova NON entra finché non viene aggiunta qui deliberatamente.
PANEL_ENTITIES = ["INTUR", "ORTI", "VIGNA"]

# Root della projection: mirror locale Drive di 01_societario/AMM_CEO.
# Override nei test/ambienti: env HOTELOPS_PANEL_ROOT.
PANEL_ROOT = os.environ.get(
    "HOTELOPS_PANEL_ROOT",
    "/Users/stefanodellapietra/My Drive (stefano@panoramagroup.it)/01_societario/AMM_CEO",
)

# Cartelle leggibili per categoria (decisione spec: nomi umani, enum nel dato)
PANEL_CATEGORY_FOLDERS = {
    "BANCA": "Banca", "LEGALE": "Legale", "FISCO": "Fisco",
    "REGISTRO_IMPRESE": "Registro Imprese", "ASSICURAZIONE": "Assicurazione",
    "PA": "PA", "FORNITORE": "Fornitori", "ALTRO": "Altro",
}

PANEL_MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024
