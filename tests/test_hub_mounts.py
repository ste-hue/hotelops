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
