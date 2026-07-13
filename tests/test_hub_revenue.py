"""Pagina Revenue — logica pura + contratto di montaggio."""

import inspect

from verticals.hub.pages_.revenue import calendario_confrontabile


def test_calendario_confrontabile():
    # aprile: 2025 aperto 16/4 (15 gg operativi) vs 2026 dal 3/4 (28 gg)
    assert calendario_confrontabile(15, 28) is False
    # maggio/giugno: mesi pieni in entrambi gli anni
    assert calendario_confrontabile(31, 31) is True
    assert calendario_confrontabile(30, 30) is True
    # entro la tolleranza del 15%
    assert calendario_confrontabile(30, 27) is True
    assert calendario_confrontabile(30, 25) is False
    # dati mancanti = non confrontabile, mai default silenzioso
    assert calendario_confrontabile(None, 30) is False
    assert calendario_confrontabile(30, None) is False
    assert calendario_confrontabile(0, 30) is False


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
