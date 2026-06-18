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


def test_mutui_page_importabile():
    # caso B1: embed di un artifact esterno (Worker Cloudflare) in iframe.
    from verticals.hub.pages_ import mutui

    assert callable(mutui.render)
    assert mutui.MUTUI_URL.startswith("https://")


def test_home_render_audience_param():
    from verticals.hub import home

    import inspect

    sig = inspect.signature(home.render)
    assert "audience" in sig.parameters


def test_spiaggia_page_importabile():
    from verticals.hub.pages_ import spiaggia

    assert callable(spiaggia.render)


def test_spiaggia_render_non_chiama_set_page_config():
    # set_page_config deve stare SOLO in __main__ (contratto hub-bind):
    # render() montata dal hub non può richiamarlo (Streamlit lo vieta 2 volte).
    # Usiamo "st.set_page_config" per evitare falsi positivi da docstring/commenti.
    import inspect

    from verticals.spiaggia import app

    src = inspect.getsource(app.render)
    assert "st.set_page_config" not in src


def test_viewer_app_no_ingest_page():
    # l'app viewer non deve MONTARE la pagina Ingest (superficie di scrittura).
    # Controlla import effettivo + assenza di st.Page(ingest...), non la docstring.
    from pathlib import Path

    src = Path("verticals/hub/app_viewer.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "import fb" in code and "reviews" in code
    assert "ingest.render" not in code
    assert "import ingest" not in code and "pages_ import fb, ingest" not in code
