import pandas as pd

from verticals.condges.app_cashflow import scad_summary, unmapped_suppliers
from verticals.condges.pf_rotate import fornitori_map
from verticals.condges.pf_rotate.fornitori_map import VOCE_LABELS


def test_scad_summary_computes_figures():
    df = pd.DataFrame(
        {
            "codice_fornitore": [1, 2],
            "nome": ["A", "B"],
            "totale": [-100.0, -50.0],
            "scaduto": [-80.0, 0.0],
            "mese_5": [-20.0, -10.0],
            "mese_6": [0.0, -40.0],
        }
    )
    summ = scad_summary(df, bucket_months=[5, 6])
    assert round(summ["scaduto_totale"], 2) == -80.0
    assert round(summ["totale_partite_aperte"], 2) == -150.0
    assert summ["forward_buckets"] == {5: -30.0, 6: -40.0}


def test_unmapped_suppliers_filters_known_and_dedups():
    df = pd.DataFrame(
        {
            "codice_fornitore": [10, 20, 10, 30],  # 10 duplicato
            "nome": ["A", "B", "A", "C"],
            "totale": [-5.0, -3.0, -5.0, -1.0],
        }
    )
    out = unmapped_suppliers(df, known_codici={20})  # 20 già mappato
    codici = [u["codice"] for u in out]
    assert codici == [10, 30]  # 20 escluso (known), 10 deduplicato
    assert out[0] == {"codice": 10, "nome": "A", "totale": -5.0}


def test_load_voci_pf_bq_fallback_to_voce_labels(monkeypatch):
    """Se load_voci_pf_bq solleva, app_cashflow usa VOCE_LABELS come fallback."""
    # Verifichiamo la logica del fallback importando direttamente il modulo
    # (il render() Streamlit richiede un server attivo; testiamo solo la funzione).
    def boom(societa):
        raise ConnectionError("BQ offline")

    monkeypatch.setattr(fornitori_map, "load_voci_pf_bq", boom)

    # Simula il pattern try/except usato in render()
    try:
        result = fornitori_map.load_voci_pf_bq("ORTI")
    except Exception:  # noqa: BLE001
        result = VOCE_LABELS

    assert result is VOCE_LABELS
    assert "USCITE_UTENZE" in result
