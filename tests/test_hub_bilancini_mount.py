"""Hub — contratto di montaggio della pagina Bilancini (embed HTML da BQ)."""

import inspect


def test_bilancini_page_importabile():
    from verticals.hub.pages_ import bilancini

    assert callable(bilancini.render)


def test_render_non_chiama_set_page_config():
    from verticals.hub.pages_ import bilancini

    src = inspect.getsource(bilancini.render)
    assert "set_page_config" not in src


def test_payload_riusa_il_builder_condges():
    # niente reimplementazione: fetch_bilancino/fetch_gruppi/build_payload/render_html
    # vengono dal builder condges (verticals/condges/build_bilancini_artifact).
    from verticals.hub.pages_ import bilancini

    src = inspect.getsource(bilancini)
    assert "build_bilancini_artifact" in src
    assert "fetch_bilancino" in src and "fetch_gruppi" in src and "build_payload" in src
    assert "render_html" in src


def test_registry_ha_bilancini():
    from verticals.hub.registry import APPS, validate

    validate()
    app = {a.id: a for a in APPS}["bilancini"]
    assert app.kind == "page" and app.group == "Finanza"
    # dati riservati (bilancio di verifica), come cassa-consuntivo: sensibile (S1)
    assert app.sensitive is True


def test_admin_vede_bilancini():
    # stesse email che vedono cassa-consuntivo (solo ALL/admin oggi) vedono bilancini.
    from verticals.hub.roles import _resolve

    for email in ("stefano@panoramagroup.it", "ste.dellapietra@gmail.com"):
        assert "bilancini" in _resolve(email, allow_all=False)
