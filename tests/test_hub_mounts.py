"""Hub — contratti di montaggio delle pagine."""


def test_reviews_render_importabile():
    from verticals.reviews.app import render, main

    assert callable(render)
    assert callable(main)


def test_reviews_render_non_chiama_set_page_config():
    # set_page_config deve stare SOLO in main() (contratto fb_dashboard):
    # render() montata dal hub non può richiamarlo (Streamlit lo vieta 2 volte).
    import inspect

    from verticals.reviews import app

    src = inspect.getsource(app.render)
    assert "set_page_config" not in src


def test_pagine_hub_importabili():
    from verticals.hub import home
    from verticals.hub.pages_ import fb, reviews

    assert callable(home.render)
    assert callable(fb.render)
    assert callable(reviews.render)


def test_fb_degrada_senza_fb_dashboard():
    # fb_dashboard non è ancora su main: l'import della PAGINA non deve esplodere
    # (il fallback vive dentro render(), non a import-time).
    import importlib

    from verticals.hub.pages_ import fb

    importlib.reload(fb)


def test_ingest_page_importabile():
    from verticals.hub.pages_ import ingest

    assert callable(ingest.render)
