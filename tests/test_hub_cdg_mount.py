"""Hub — contratto di montaggio del CdG (vertical condges)."""

import inspect


def test_cdg_page_exists_and_callable():
    from verticals.hub.pages_ import cdg

    assert callable(cdg.render)


def test_app_cdg_espone_render_e_main():
    from verticals.condges.app_cdg import main, render

    assert callable(render)
    assert callable(main)


def test_render_non_chiama_set_page_config():
    # set_page_config solo in main(): l'hub lo imposta già (Streamlit lo vieta 2 volte).
    from verticals.condges import app_cdg

    src = inspect.getsource(app_cdg.render)
    assert "st.set_page_config" not in src


def test_registry_cdg_spento_come_soon():
    # 2026-07-05: CdG smontato dalla nav ("troppi dati, semplifichiamo"),
    # resta tile "coming soon" in Finanza finché non atterra il redesign.
    from verticals.hub.registry import APPS, by_group, pages

    assert "cdg" not in {a.id for a in pages()}
    assert "cdg" in {a.id for a in by_group()["Finanza"]}
    assert next(a for a in APPS if a.id == "cdg").kind == "soon"
