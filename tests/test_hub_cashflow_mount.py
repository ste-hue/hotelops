import ast
from pathlib import Path


def test_cashflow_page_exists_and_callable():
    from verticals.hub.pages_ import cashflow

    assert callable(cashflow.render)


def test_hub_app_registers_cashflow():
    src = Path("verticals/hub/app.py").read_text()
    assert "cashflow" in src, (
        "hub/app.py deve importare e registrare la pagina cashflow"
    )
    # parse-only sanity
    ast.parse(src)
