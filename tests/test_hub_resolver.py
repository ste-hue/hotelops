from verticals.hub.registry import APPS
from verticals.hub.resolver import validate_resolution


def test_validate_resolution_ok():
    validate_resolution()


def test_tutte_le_page_hanno_route_e_resolver():
    validate_resolution()
    page_ids = {app.id for app in APPS if app.kind == "page"}
    assert "bilancini" in page_ids
