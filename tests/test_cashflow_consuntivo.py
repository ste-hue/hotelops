"""Test Livello B — matcher trasferimenti interni e consolidato società."""

from datetime import date

from verticals.condges.cashflow_consuntivo_data import (
    consolidato_societa,  # noqa: F401 — usata dai test del Task 3
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
