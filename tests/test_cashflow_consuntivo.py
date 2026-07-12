"""Test Livello B — matcher trasferimenti interni e consolidato società."""

from datetime import date

from verticals.condges.cashflow_consuntivo_data import (
    carica_voci_patterns,
    classifica_registrazione,
    consolidato_societa,
    detect_trasferimenti_interni,
)


def _mov(idx, banca, giorno, importo, descr="BONIFICO"):
    return {
        "id_movimento": f"m{idx}",
        "banca_id": banca,
        "data_operazione": date(2026, 6, giorno),
        "importo_netto": importo,
        "descrizione": descr,
    }


def test_coppia_cross_banca_univoca_e_auto():
    movs = [
        _mov(1, "INTESA", 10, -100_000.0, "Bon. a vostro favore"),
        _mov(2, "MPS", 11, +100_000.0, "Bonifico in entrata"),
        _mov(3, "MPS", 12, -500.0, "F24"),
    ]
    out = detect_trasferimenti_interni(movs)
    by_id = {m["id_movimento"]: m for m in out}
    assert by_id["m1"]["transfer_status"] == "AUTO"
    assert by_id["m2"]["transfer_status"] == "AUTO"
    assert by_id["m1"]["transfer_group"] == by_id["m2"]["transfer_group"]
    assert by_id["m3"]["transfer_status"] is None


def test_fuori_finestra_non_matcha():
    movs = [
        _mov(1, "INTESA", 1, -50_000.0),
        _mov(2, "MPS", 20, +50_000.0),
    ]
    out = detect_trasferimenti_interni(movs, window_days=3)
    assert all(m["transfer_status"] is None for m in out)


def test_ambiguo_diventa_candidate_mai_auto():
    movs = [
        _mov(1, "INTESA", 10, -10_000.0),
        _mov(2, "MPS", 10, +10_000.0),
        _mov(3, "SELLA", 11, +10_000.0),
    ]
    out = detect_trasferimenti_interni(movs)
    assert {m["transfer_status"] for m in out} == {"CANDIDATE"}
    assert all(m["transfer_group"] is None for m in out)


def test_stessa_banca_solo_con_pattern_causale():
    con_pattern = [
        _mov(1, "MPS", 5, -20_000.0, "Emissione ass. circolari"),
        _mov(2, "MPS", 7, +20_000.0, "Versamento ns. a/c"),
    ]
    out = detect_trasferimenti_interni(con_pattern)
    assert all(m["transfer_status"] == "AUTO" for m in out)

    senza_pattern = [
        _mov(1, "MPS", 5, -20_000.0, "Pagamento fornitore"),
        _mov(2, "MPS", 7, +20_000.0, "Incasso cliente"),
    ]
    out2 = detect_trasferimenti_interni(senza_pattern)
    assert all(m["transfer_status"] is None for m in out2)


def test_greedy_preferisce_distanza_minore():
    movs = [
        _mov(1, "INTESA", 10, -5_000.0),
        _mov(2, "MPS", 10, +5_000.0),
        _mov(3, "INTESA", 15, -5_000.0),
        _mov(4, "MPS", 16, +5_000.0),
    ]
    out = detect_trasferimenti_interni(movs, window_days=3)
    by_id = {m["id_movimento"]: m for m in out}
    assert by_id["m1"]["transfer_group"] == by_id["m2"]["transfer_group"]
    assert by_id["m3"]["transfer_group"] == by_id["m4"]["transfer_group"]
    assert by_id["m1"]["transfer_group"] != by_id["m3"]["transfer_group"]


def test_consolidato_neutralizza_solo_auto_caso_zia():
    """Caso canonico: 2M in/out come giro → variazione netta = solo flussi esterni."""
    movs = [
        _mov(1, "MPS", 10, +2_000_000.0, "Versamento ns. a/c assegni circolari"),
        _mov(2, "MPS", 12, -2_000_000.0, "Emissione ass. circolari"),
        _mov(3, "MPS", 15, +40_000.0, "POS incassi"),
        _mov(4, "INTESA", 20, -100_000.0, "Pagamento fornitori"),
    ]
    tagged = detect_trasferimenti_interni(movs)
    cons = consolidato_societa(tagged)
    assert cons["trasferimenti_interni"] == 4_000_000.0  # lordo movimentato nei giri
    assert cons["incassi_esterni"] == 40_000.0
    assert cons["pagamenti_esterni"] == 100_000.0
    assert cons["variazione_netta"] == -60_000.0


def test_consolidato_candidate_resta_nei_flussi_esterni():
    """I CANDIDATE non vengono neutralizzati (naming honesty: solo AUTO esce dal consolidato)."""
    movs = [
        _mov(1, "INTESA", 10, -10_000.0),
        _mov(2, "MPS", 10, +10_000.0),
        _mov(3, "SELLA", 11, +10_000.0),
    ]
    tagged = detect_trasferimenti_interni(movs)
    cons = consolidato_societa(tagged)
    assert cons["trasferimenti_interni"] == 0.0
    assert cons["candidati_trasferimento"] == 30_000.0
    assert cons["incassi_esterni"] == 20_000.0
    assert cons["pagamenti_esterni"] == 10_000.0


def test_pagina_hub_importabile_e_senza_page_config():
    """render() esiste e il modulo non chiama st.set_page_config (vincolo hub)."""
    import inspect

    from verticals.hub.pages_ import cassa_consuntivo

    assert callable(cassa_consuntivo.render)
    src = inspect.getsource(cassa_consuntivo)
    assert "set_page_config" not in src


def test_voci_patterns_orti_prefix_match():
    from verticals.condges.cashflow_consuntivo_data import (
        carica_voci_patterns,
        voce_per_conto,
    )

    patterns = carica_voci_patterns("ORTI")
    assert voce_per_conto("750198", patterns) == "USCITE_SPESE_BANCARIE"  # pat 7501
    assert voce_per_conto("570913", patterns) == "USCITE_UTENZE"  # pat 5709
    assert (
        voce_per_conto("651101", patterns) == "USCITE_CANONE_PASSIVO"
    )  # pat 6511, riga ORTI
    assert voce_per_conto("479102", patterns) == "ENTRATE_HOTEL"  # pat 4791
    assert voce_per_conto("390701", patterns) is None  # nessun pattern (fino al Task 4)


def test_voci_patterns_filtra_societa():
    from verticals.condges.cashflow_consuntivo_data import (
        carica_voci_patterns,
        voce_per_conto,
    )

    patterns_intur = carica_voci_patterns("INTUR")
    # ENTRATE_HOTEL è riga solo-ORTI: non deve matchare per INTUR
    assert voce_per_conto("479102", patterns_intur) != "ENTRATE_HOTEL"
    # le righe a società vuota valgono per entrambe
    assert voce_per_conto("750198", patterns_intur) == "USCITE_SPESE_BANCARIE"


def _riga(conto, dare, avere, partitario=None):
    return {
        "cod_conto": conto,
        "cod_partitario": partitario,
        "imp_dare": dare,
        "imp_avere": avere,
    }


def _patterns_orti():
    return carica_voci_patterns("ORTI")


def test_classifica_acconto_stipendio_anatomia_reale():
    """PNC 11 del 08/06 ORTI: banca -560,70 = personale 560 (non mappato fino a Task 4) + spese 0,70."""
    righe = [
        _riga("390701", 560.0, 0.0),
        _riga("190101", 0.0, 560.70, partitario="2"),
        _riga("750198", 0.70, 0.0),
    ]
    out = classifica_registrazione(righe, {}, _patterns_orti())
    assert out["tipo"] == "NORMALE"
    assert out["flusso_banca"] == -560.70
    assert ("NON_MAPPATO_CONTO", -560.0) in out["allocazioni"]
    assert ("USCITE_SPESE_BANCARIE", -0.70) in out["allocazioni"]
    assert abs(sum(i for _, i in out["allocazioni"]) - out["flusso_banca"]) < 0.01


def test_classifica_pagamento_fornitore_via_partitario():
    """Pagamento fattura: banca in avere, debito fornitore in dare, voce da d_fornitori."""
    righe = [
        _riga("330301", 1000.0, 0.0, partitario="18"),
        _riga("190101", 0.0, 1000.0, partitario="2"),
    ]
    out = classifica_registrazione(righe, {18: "USCITE_UTENZE"}, _patterns_orti())
    assert out["allocazioni"] == [("USCITE_UTENZE", -1000.0)]


def test_classifica_fornitore_sconosciuto():
    righe = [
        _riga("330301", 500.0, 0.0, partitario="9999"),
        _riga("190101", 0.0, 500.0, partitario="2"),
    ]
    out = classifica_registrazione(righe, {18: "USCITE_UTENZE"}, _patterns_orti())
    assert out["allocazioni"] == [("NON_MAPPATO_FORNITORE", -500.0)]


def test_classifica_incasso_entrata():
    """Cassa hotel: banca in dare, ricavo in avere → allocazione positiva."""
    righe = [
        _riga("190101", 1135.0, 0.0, partitario="2"),
        _riga("479102", 0.0, 1135.0),
    ]
    out = classifica_registrazione(righe, {}, _patterns_orti())
    assert out["flusso_banca"] == 1135.0
    assert out["allocazioni"] == [("ENTRATE_HOTEL", 1135.0)]


def test_classifica_giro_registrato():
    """Giroconto fra banche: 2 bracci 1901 opposti, nessuna sorella → GIRO_REGISTRATO."""
    righe = [
        _riga("190101", 0.0, 50_000.0, partitario="2"),
        _riga("190102", 50_000.0, 0.0, partitario="1"),
    ]
    out = classifica_registrazione(righe, {}, _patterns_orti())
    assert out["tipo"] == "GIRO_REGISTRATO"
    assert out["allocazioni"] == [("TRASFERIMENTO_INTERNO", 50_000.0)]
    assert out["banca_id"] == "MULTI"


def test_classifica_cespite_con_partitario_usa_pattern_conto():
    """Partitario numerico su conto NON-33 (cespite): la voce viene dal pattern conto."""
    righe = [
        _riga("550711", 772.57, 0.0, partitario="20"),
        _riga("190101", 0.0, 772.57, partitario="2"),
    ]
    out = classifica_registrazione(righe, {20: "USCITE_UTENZE"}, _patterns_orti())
    assert out["allocazioni"] == [("USCITE_MATERIE_PRIME", -772.57)]


def test_classifica_incasso_cliente_non_ruba_voce_fornitore():
    """Partitario cliente che collide con un codice fornitore: MAI la voce del fornitore."""
    righe = [
        _riga("190101", 500.0, 0.0, partitario="2"),
        _riga("110301", 0.0, 500.0, partitario="18"),
    ]
    out = classifica_registrazione(righe, {18: "USCITE_UTENZE"}, _patterns_orti())
    assert out["allocazioni"] != [("USCITE_UTENZE", 500.0)]
    assert out["allocazioni"] == [("NON_MAPPATO_CONTO", 500.0)]
