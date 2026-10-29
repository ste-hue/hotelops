import pytest
from pydantic import ValidationError

from core.config import P_SCENARI
from core.schemas import ProgettoPagamentoRow, ScenarioFlussoRow, ScenarioRow


def riga_ok(**kw):
    base = dict(
        scenario_id="s1",
        societa_id="ORTI",
        mese="2026-11",
        voce_id="v1",
        importo_cent=1050,
        direzione="E",
        origine="pf",
        raw_object_id="r1",
        hash_riga="h",
        data_caricamento="2026-10-29T00:00:00Z",
    )
    base.update(kw)
    return base


def pag_ok(**kw):
    base = dict(
        scenario_id="s1",
        progetto_id="p1",
        pagamento="acconto",
        mese="2026-11",
        importo_netto_cent=100000,
        aliquota_iva=22,
        stato="previsto",
        fornitore_id=None,
        societa_id="INTUR",
        raw_object_id="r1",
        hash_riga="h",
        data_caricamento="2026-10-29T00:00:00Z",
    )
    base.update(kw)
    return base


def test_tabelle_previsioni_qualificate():
    assert P_SCENARI == "hotelops-suite.hotelops_previsioni.p_scenari"


def test_righe_valide():
    ScenarioFlussoRow(**riga_ok())
    ProgettoPagamentoRow(**pag_ok())
    ScenarioRow(
        scenario_id="s1",
        nome="n",
        creato_il="2026-10-29T00:00:00Z",
        autore="a",
        schema_doc="1",
        base="{}",
        parametri="{}",
        progetti_accesi=["p1"],
        note=None,
        raw_object_id="r1",
        hash_riga="h",
        data_caricamento="2026-10-29T00:00:00Z",
    )


def test_scenario_flusso_rifiuta_origine_sconosciuta_e_importo_float():
    with pytest.raises(ValidationError):
        ScenarioFlussoRow(**riga_ok(origine="boh"))
    with pytest.raises(ValidationError):
        ScenarioFlussoRow(**riga_ok(importo_cent=10.5))


def test_mese_formato():
    with pytest.raises(ValidationError):
        ScenarioFlussoRow(**riga_ok(mese="2026-1"))
    with pytest.raises(ValidationError):
        ProgettoPagamentoRow(**pag_ok(mese="nov-2026"))


def test_pagamento_rifiuta_aliquota_fuori_lista():
    with pytest.raises(ValidationError):
        ProgettoPagamentoRow(**pag_ok(aliquota_iva=4))
