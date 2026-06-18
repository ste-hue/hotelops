import pandas as pd

from verticals.condges.app_cashflow import scad_summary


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
