"""Tests per le funzioni pure del builder artifact bilancini."""

from verticals.condges.build_bilancini_artifact import (
    budget_per_conto,
    build_payload,
    compute_delta,
)


def test_compute_delta_first_month_is_ytd():
    ytd = {"2026-01": 100.0, "2026-02": 250.0, "2026-04": 400.0}
    delta = compute_delta(ytd)
    assert delta["2026-01"] == 100.0
    assert delta["2026-02"] == 150.0
    # mese mancante (2026-03): delta di 2026-04 = 400 − 250 (dall'ultimo mese presente)
    assert delta["2026-04"] == 150.0


def test_budget_per_conto_aggregates_months():
    rows = [
        {"codice_conto": "55.01.90", "mese": 5, "importo": 100.0, "categoria_ce": "Costi Produttivi"},
        {"codice_conto": "55.01.90", "mese": 5, "importo": 50.0, "categoria_ce": "Costi Produttivi"},
        {"codice_conto": "55.01.90", "mese": 6, "importo": 70.0, "categoria_ce": "Costi Produttivi"},
    ]
    out = budget_per_conto(rows)
    assert out["55.01.90"] == {5: 150.0, 6: 70.0}


def test_build_payload_signs_and_fuori_budget():
    bilancino = [
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "47.91.01",
         "descrizione": "Ricavi alloggi", "tipo_conto": "CE", "sezione": "Ricavi", "saldo": -1000.0},
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "67.03.94",
         "descrizione": "Conto fuori budget", "tipo_conto": "CE", "sezione": "Costi", "saldo": 80.0},
    ]
    budget = [{"codice_conto": "47.91.01", "mese": 5, "importo": 900.0, "categoria_ce": "Ricavi"}]
    payload = build_payload(bilancino, budget, incidenza={})
    orti = {c["codice"]: c for c in payload["societa"]["ORTI"]["conti"]}
    assert orti["47.91.01"]["ytd"]["2026-05"] == -1000.0
    assert "67.03.94" in orti                      # presente anche senza budget
    assert payload["budget"]["per_conto"]["47.91.01"][5] == 900.0
    assert "67.03.94" not in payload["budget"]["per_conto"]  # il renderer lo marca Fuori budget
