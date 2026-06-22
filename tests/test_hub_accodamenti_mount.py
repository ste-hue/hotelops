"""Hub — contratto di montaggio dell'ingestore Accodamenti (vertical condges)."""

import inspect


def test_accodamenti_page_exists_and_callable():
    from verticals.hub.pages_ import accodamenti

    assert callable(accodamenti.render)


def test_app_accodamenti_espone_render_e_main():
    from verticals.condges.app_accodamenti import main, render

    assert callable(render)
    assert callable(main)


def test_render_non_chiama_set_page_config():
    # set_page_config solo in main(): l'hub lo imposta già (Streamlit lo vieta 2 volte).
    from verticals.condges import app_accodamenti

    src = inspect.getsource(app_accodamenti.render)
    assert "st.set_page_config" not in src


def test_registry_monta_accodamenti_in_finanza():
    from verticals.hub.registry import by_group, pages

    assert "accodamenti" in {a.id for a in pages()}
    assert "accodamenti" in {a.id for a in by_group()["Finanza"]}
