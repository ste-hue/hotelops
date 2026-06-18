from verticals.condges.services.intents import (
    BudgetRiga,
    SaveBudgetIntent,
    SavePrevisioneIntent,
    SaveResult,
)


def test_intents_construct():
    riga = BudgetRiga(
        mese=4,
        codice_conto="570913",
        descrizione="Utenze",
        tipo_costo="VARIABILE",
        categoria_ce="COSTI",
        business_unit_id="HOTEL",
        importo=22000.0,
    )
    b = SaveBudgetIntent(societa_id="ORTI", anno=2026, righe=[riga])
    assert b.fonte == "APP_BUDGET"
    assert b.righe[0].mese == 4

    p = SavePrevisioneIntent(
        societa_id="ORTI", voce_id="USCITE_UTENZE", mesi=[4, 5], importo=22000.0, anno=2026,
    )
    assert p.fonte == "NANOCLAW"

    r = SaveResult(table="t", rows_written=2, natural_key=["a"])
    assert r.rows_written == 2
