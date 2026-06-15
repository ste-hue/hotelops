"""Exporter static-edge — contratti di shape (offline, righe sintetiche, no BQ)."""

import json
from pathlib import Path

from verticals.hub.publish.export import shape_meta


def test_shape_meta_contract():
    out = shape_meta(
        generated_at="2026-06-13T03:00:00Z",
        fresh={"fb": {"giorni": 12}, "reviews": {"giorni": 2, "media_mese": 8.0}},
    )
    assert out["schema"] == 1
    assert out["generated_at"] == "2026-06-13T03:00:00Z"
    assert out["surfaces"]["fb"]["semaforo"] in ("🟢", "🟡", "🔴")
    assert out["surfaces"]["reviews"]["media_mese"] == 8.0
    assert "fb" in out["surfaces"]
    assert "reviews" in out["surfaces"]


def test_export_all_produces_only_meta(tmp_path):
    """export_all (dry_run) returns only _meta — fb.json and reviews.json removed."""
    from unittest.mock import patch

    fake_fresh = {"fb": {"giorni": 12}, "reviews": {"giorni": 3, "media_mese": 8.5}}
    with patch("verticals.hub.freshness.carica_freshness", return_value=fake_fresh):
        from verticals.hub.publish.export import export_all
        result = export_all(str(tmp_path), "2026-06-14T00:00:00Z", dry_run=True)

    assert set(result.keys()) == {"_meta"}, f"export_all produced unexpected keys: {set(result.keys())}"
    assert result["_meta"]["surfaces"]["fb"]["giorni"] == 12
    assert result["_meta"]["surfaces"]["reviews"]["media_mese"] == 8.5


_SITE = Path(__file__).resolve().parents[1] / "verticals/hub/publish/site"

def test_apps_manifest_valid():
    manifest = json.loads((_SITE / "apps.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    apps = manifest["apps"]
    assert apps, "manifest vuoto"
    ids = [a["id"] for a in apps]
    assert len(ids) == len(set(ids)), "id duplicati nel manifest"
    for a in apps:
        assert a["kind"] in ("internal", "external"), a
        if a["kind"] == "internal":
            assert "view" in a and "kpi_from" in a, f"internal senza view/kpi_from: {a}"
        else:
            assert a["url"].startswith("http"), f"external senza url valido: {a}"

def test_internal_cards_reference_exported_surfaces():
    # ogni card internal.kpi_from deve essere una surface che _meta.json espone
    fresh = {"fb": {"giorni": 10}, "reviews": {"giorni": 2, "media_mese": 8.1}}
    meta = shape_meta("2026-01-01T00:00:00Z", fresh)
    surfaces = set(meta["surfaces"].keys())
    manifest = json.loads((_SITE / "apps.json").read_text(encoding="utf-8"))
    for a in manifest["apps"]:
        if a["kind"] == "internal":
            assert a["kpi_from"] in surfaces, f"{a['id']} punta a surface assente: {a['kpi_from']}"
