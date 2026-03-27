PROJECT = "hotelops-suite"
DATASET = "hotelops"

def _t(name: str) -> str:
    return f"{PROJECT}.{DATASET}.{name}"

# Fact tables
F_BANCHE_MOVIMENTI          = _t("f_banche_movimenti")
F_SALDI_BANCA_SNAPSHOT      = _t("f_saldi_banca_snapshot")
F_MOVIMENTI_CONTABILI       = _t("f_movimenti_contabili")
F_BUDGET_MENSILE            = _t("f_budget_mensile")
F_PIANO_FINANZIARIO_INPUT   = _t("f_piano_finanziario_input")
F_ACCODAMENTI               = _t("f_accodamenti")
F_BILANCINO                 = _t("f_bilancino")
F_CONSUMI_ECONOMATO         = _t("f_consumi_economato")
F_COPERTI_GIORNALIERI       = _t("f_coperti_giornalieri")
F_CHIUSURA_MENSILE          = _t("f_chiusura_mensile")
F_PARTITE_APERTE_FORNITORI  = _t("f_partite_aperte_fornitori")
F_RICAVI_STORICI            = _t("f_ricavi_storici")
F_COEFFICIENTI_CONSUMO      = _t("f_coefficienti_consumo")
F_PMS_STATISTICHE           = _t("f_pms_statistiche")

# Dimension tables
D_VOCI_PIANO_FINANZIARIO    = _t("d_voci_piano_finanziario")
D_PIANO_CONTI               = _t("d_piano_conti")
D_CATEGORIE_CONTI           = _t("d_categorie_conti")
D_FORNITORI                 = _t("d_fornitori")
D_ANAGRAFICA_FORNITORI      = _t("d_anagrafica_fornitori")
D_MAPPING_PIANO_FINANZIARIO = _t("d_mapping_piano_finanziario")
D_COEFFICIENTI_STAGIONALITA = _t("d_coefficienti_stagionalita")

# Views
V_PIANO_FINANZIARIO_MENSILE = _t("v_piano_finanziario_mensile")
V_BUDGET_VS_CONSUNTIVO      = _t("v_budget_vs_consuntivo")
V_PIANO_FINANZIARIO_CONSUNTIVO = _t("v_piano_finanziario_consuntivo")
V_PREVISIONE_CASSA          = _t("v_previsione_cassa")
