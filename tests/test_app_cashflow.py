import pandas as pd

from verticals.condges.app_cashflow import build_cash_run_intent


class _FakeResult:
    n_controlli_ok = 22
    n_controlli_err = 1
    n_controlli_indet = 0


def test_build_cash_run_intent_computes_figures():
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
    intent = build_cash_run_intent(
        societa_id="ORTI",
        anno=2026,
        mese_chiuso=4,
        data_saldo="2026-04-30",
        saldi={"MPS": 245171.52, "INTESA": 87439.92},
        scad_df=df,
        bucket_months=[5, 6],
        result=_FakeResult(),
    )
    assert intent.societa_id == "ORTI"
    assert intent.mese_chiuso == 4
    assert round(intent.saldo_cutover, 2) == 332611.44
    assert round(intent.scaduto_totale, 2) == -80.0
    assert round(intent.totale_partite_aperte, 2) == -150.0
    assert intent.forward_buckets == {5: -30.0, 6: -40.0}
    assert intent.n_controlli_err == 1
    assert intent.fonte == "APP_CASHFLOW"
