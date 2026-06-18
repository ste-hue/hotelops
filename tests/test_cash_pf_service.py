from unittest.mock import patch

from core.schemas import BudgetMensileRow, PianoFinanziarioInputRow
from verticals.condges.services import cash_pf_service
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


def test_save_budget_calls_gate_snapshot():
    intent = SaveBudgetIntent(
        societa_id="ORTI",
        anno=2026,
        righe=[
            BudgetRiga(
                mese=4,
                codice_conto="570913",
                descrizione="Utenze",
                tipo_costo="VARIABILE",
                categoria_ce="COSTI",
                business_unit_id="HOTEL",
                importo=22000.0,
            ),
            BudgetRiga(mese=5, codice_conto="570913", importo=21000.0),
        ],
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        result = cash_pf_service.save_budget(intent)

    gate.assert_called_once()
    args, kwargs = gate.call_args
    table, rows = args[0], args[1]
    assert table.endswith("f_budget_mensile")
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["societa_id", "anno", "fonte"]
    assert all(isinstance(r, BudgetMensileRow) for r in rows)
    assert rows[0].fonte == "APP_BUDGET"
    assert rows[0].data_caricamento  # required field popolato
    assert result.rows_written == 2


def test_save_budget_rejects_bad_row():
    import pytest

    bad = SaveBudgetIntent(
        societa_id="ORTI",
        anno=2026,
        righe=[BudgetRiga(mese=13, codice_conto="570913", importo=1.0)],  # mese fuori range
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        with pytest.raises(Exception):
            cash_pf_service.save_budget(bad)
        gate.assert_not_called()  # fallisce alla validazione, prima del gate


def test_save_previsione_calls_gate_snapshot():
    intent = SavePrevisioneIntent(
        societa_id="ORTI",
        voce_id="USCITE_UTENZE",
        mesi=[4, 5, 6],
        importo=22000.0,
        anno=2026,
    )
    with patch.object(cash_pf_service, "bq_write_validated") as gate:
        result = cash_pf_service.save_previsione(intent)

    args, kwargs = gate.call_args
    table, rows = args[0], args[1]
    assert table.endswith("f_piano_finanziario_input")
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["societa_id", "voce_id", "anno", "mese", "fonte"]
    assert all(isinstance(r, PianoFinanziarioInputRow) for r in rows)
    assert {r.mese for r in rows} == {4, 5, 6}
    # hash deterministico e stabile per (societa, voce, anno, mese, fonte)
    assert rows[0].hash_riga and len(rows[0].hash_riga) == 32
    assert result.rows_written == 3
