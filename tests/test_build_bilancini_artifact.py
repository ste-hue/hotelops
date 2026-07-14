"""Tests per le funzioni pure del builder artifact bilancini (v1: solo numeri veri)."""

from verticals.condges.build_bilancini_artifact import build_payload, compute_delta


def test_compute_delta_first_month_is_ytd():
    ytd = {"2026-01": 100.0, "2026-02": 250.0, "2026-04": 400.0}
    delta = compute_delta(ytd)
    assert delta["2026-01"] == 100.0
    assert delta["2026-02"] == 150.0
    # mese mancante (2026-03): delta di 2026-04 = 400 − 250 (dall'ultimo mese presente)
    assert delta["2026-04"] == 150.0


def test_build_payload_signs_and_presence():
    bilancino = [
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "47.91.01",
         "descrizione": "Ricavi alloggi", "tipo_conto": "CE", "sezione": "Ricavi", "saldo": -1000.0},
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "67.03.94",
         "descrizione": "Vestiario dipendenti", "tipo_conto": "CE", "sezione": "Costi", "saldo": 80.0},
    ]
    payload = build_payload(bilancino)
    orti = {c["codice"]: c for c in payload["societa"]["ORTI"]["conti"]}
    # saldo bilancino a segno grezzo nel payload (ricavi negativi): il raddrizzamento è del renderer
    assert orti["47.91.01"]["ytd"]["2026-05"] == -1000.0
    assert orti["47.91.01"]["delta"]["2026-05"] == -1000.0
    assert orti["67.03.94"]["ytd"]["2026-05"] == 80.0
    assert "budget" not in payload  # v1: solo numeri veri, nessuna stima
    assert payload["gruppi"] == {}  # nessun gruppi passato → default vuoto


def test_build_payload_includes_gruppi_descriptions():
    bilancino = [
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "47.91.01",
         "descrizione": "Ricavi alloggi", "tipo_conto": "CE", "sezione": "Ricavi", "saldo": -1000.0},
    ]
    gruppi = {"47.91": "Ricavi Hotel", "47": "RICAVI DELLE VENDITE E DELLE PRESTAZIONI"}
    payload = build_payload(bilancino, gruppi)
    assert payload["gruppi"] == gruppi
    # label fallback: un codice gruppo assente in DATA.gruppi resta il codice stesso
    # (comportamento lato JS: DATA.gruppi[codice] || codice) — qui verifichiamo solo
    # che il payload trasporti il dict così com'è, senza mutazioni.
    assert payload["gruppi"].get("99.99") is None
