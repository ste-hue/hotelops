"""Hub — contratto di montaggio del CdG: dal 2026-10-29 porta verso cdg.panorama-host.com."""

import inspect


def test_cdg_page_exists_and_callable():
    from verticals.hub.pages_ import cdg

    assert callable(cdg.render)
    assert cdg.CDG_URL == "https://cdg.panorama-host.com/"


def test_app_cdg_espone_render_e_main():
    from verticals.condges.app_cdg import main, render

    assert callable(render)
    assert callable(main)


def test_render_non_chiama_set_page_config():
    # set_page_config solo in main(): l'hub lo imposta già (Streamlit lo vieta 2 volte).
    from verticals.condges import app_cdg
    from verticals.hub.pages_ import cdg

    assert "st.set_page_config" not in inspect.getsource(app_cdg.render)
    assert "st.set_page_config" not in inspect.getsource(cdg.render)


def test_pagina_hub_e_una_porta_con_re_check_del_grant():
    # Niente embed, niente import dell'app Streamlit: solo link all'edge app + re-check (S1).
    from verticals.hub.pages_ import cdg

    src = inspect.getsource(cdg.render)
    assert "link_button" in src and "CDG_URL" in src
    assert "current_apps()" in src and '"cdg"' in src and "st.stop()" in src
    assert "app_cdg" not in src


def test_registry_cdg_acceso_come_page_sensibile():
    from verticals.hub.registry import APPS, by_group, pages

    app = next(a for a in APPS if a.id == "cdg")
    assert app.kind == "page" and app.sensitive is True and callable(app.target)
    assert "cdg" in {a.id for a in pages()}
    assert "cdg" in {a.id for a in by_group()["Finanza"]}
