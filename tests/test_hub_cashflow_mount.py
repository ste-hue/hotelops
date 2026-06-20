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
