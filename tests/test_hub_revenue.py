"""Pagina Revenue — verdetto puro + contratto di montaggio."""

import inspect

from verticals.hub.pages_.revenue import verdetto


def _base(**kw):
    d = dict(
        mese_consumato=False,
        prima_foto=False,
        pickup_notti=10.0,
        gap_target=50_000.0,
        gap_notti_target=300.0,
        adr_marginale=250.0,
        adr_richiesto=150.0,
    )
    d.update(kw)
    return d


def test_stati_preliminari_in_ordine():
    assert verdetto(**_base(mese_consumato=True)) == "CONSUNTIVO"
    assert verdetto(**_base(prima_foto=True)) == "DATI_INSUFFICIENTI"
    assert verdetto(**_base(pickup_notti=0.0)) == "DATI_INSUFFICIENTI"
    assert verdetto(**_base(pickup_notti=None)) == "DATI_INSUFFICIENTI"
    assert verdetto(**_base(gap_target=0.0)) == "TARGET_RAGGIUNTO"
    assert verdetto(**_base(gap_target=-1.0)) == "TARGET_RAGGIUNTO"
    assert verdetto(**_base(gap_notti_target=0.0)) == "TARGET_INCOERENTE"
    assert verdetto(**_base(adr_marginale=None)) == "NESSUN_CONFRONTO"
    assert verdetto(**_base(adr_richiesto=None)) == "NESSUN_CONFRONTO"


def test_tre_zone_calibrazione_11_07():
    # luglio 11/07: richiesto 218 vs marginale 476 -> 0.46 < 0.6
    assert (
        verdetto(**_base(adr_richiesto=218.0, adr_marginale=476.0)) == "TARGET_SCONTATO"
    )
    # ottobre 11/07: richiesto 175 vs marginale 206 -> 0.85, tra 0.6 e 1
    assert (
        verdetto(**_base(adr_richiesto=175.0, adr_marginale=206.0)) == "SERVE_DOMANDA"
    )
    # richiesto sopra il marginale
    assert (
        verdetto(**_base(adr_richiesto=250.0, adr_marginale=206.0)) == "SERVE_REPRICING"
    )


def test_render_montabile():
    from verticals.hub.pages_ import revenue

    assert callable(revenue.render)
    # contratto hub: render() non chiama set_page_config
    assert "set_page_config" not in inspect.getsource(revenue.render)


def test_registry_ha_revenue():
    from verticals.hub.registry import APPS, validate

    validate()
    app = {a.id: a for a in APPS}["revenue"]
    assert app.kind == "page" and app.group == "Finanza"
    assert app.sensitive is False
