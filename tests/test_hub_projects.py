"""Raccordi per progetto e confine di accesso alla nuova superficie."""

from unittest.mock import MagicMock, patch

from verticals.hub.pages_ import projects
from verticals.hub.registry import APPS, pages_for
from verticals.hub.roles import OPERATIONS, _resolve
from verticals.projects.catalog import PROJECTS


def test_project_identity_routes_to_its_own_app_and_front():
    routes = {p.progetto_id: (p.app_url, p.regia_url) for p in PROJECTS}
    assert len(routes) == len(PROJECTS)
    assert routes == {
        "HPAN26SOFT": (
            "https://soft.panorama-host.com",
            "https://regia.panorama-host.com/?node=68079b85",
        ),
        "HPAN26PIANO3": (
            "https://hpan26.panorama-host.com",
            "https://regia.panorama-host.com/?node=ea45459f",
        ),
    }


def test_one_sensitive_surface_not_two_project_verticals():
    app = next(a for a in APPS if a.id == "projects")
    assert app.kind == "page" and app.sensitive
    assert app.target is projects.render
    assert "projects" not in OPERATIONS
    assert "projects" in _resolve("stefano@panoramagroup.it", False)
    assert "projects" not in _resolve("fom@panoramagroup.it", False)
    assert "projects" not in _resolve(None, False)
    assert not pages_for(frozenset())


def test_direct_render_denies_before_showing_links():
    with (
        patch("verticals.hub.roles.current_apps", return_value=frozenset()),
        patch.object(projects, "st", MagicMock()) as ui,
        patch.object(projects, "brand_header") as header,
    ):
        projects.render()
        ui.error.assert_called_once()
        ui.link_button.assert_not_called()
        header.assert_not_called()


def test_authorized_render_has_app_and_regia_links_for_each_project():
    with (
        patch("verticals.hub.roles.current_apps", return_value={"projects"}),
        patch.object(projects, "st", MagicMock()) as ui,
        patch.object(projects, "brand_header"),
    ):
        projects.render()
        urls = [call.args[1] for call in ui.link_button.call_args_list]
        assert urls == [url for p in PROJECTS for url in (p.app_url, p.regia_url)]
