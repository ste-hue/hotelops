import ast
from pathlib import Path


def test_cashflow_page_exists_and_callable():
    from verticals.hub.pages_ import cashflow

    assert callable(cashflow.render)


def test_hub_app_registers_cashflow():
    # La registrazione vive nel registry (app.py costruisce la nav da lì).
    from verticals.hub.registry import pages

    assert "cashflow" in {a.id for a in pages()}, (
        "il registry deve montare la pagina cashflow come kind=page"
    )
    # app.py resta parsabile e costruisce la nav dal registry.
    src = Path("verticals/hub/app.py").read_text()
    ast.parse(src)
    assert "registry" in src


def test_app_filtra_la_nav_su_current_apps():
    from pathlib import Path

    src = Path("verticals/hub/app.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "current_apps" in code
    assert "pages_for" in code
    # la Home riceve anche le app concesse, non solo page_objs
    assert "home.render(_page_objs, allowed)" in code


def test_superfici_scrittura_ricontrollano_il_grant():
    import inspect

    from verticals.hub.pages_ import cashflow, ingest

    for mod, app_id in ((cashflow, "cashflow"), (ingest, "ingest")):
        src = inspect.getsource(mod.render)
        assert "current_apps()" in src, f"{app_id}: manca il re-check"
        assert f'"{app_id}"' in src
        assert "st.stop()" in src
