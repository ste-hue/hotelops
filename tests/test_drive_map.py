"""Private map validation at read-only and publication boundaries; synthetic only."""

import json
import sys
from datetime import date

import pytest

from core import drive_health
from core.drive_map import load_drive_map

VALID = """roots:
  a:
    id: synthetic-root
    label: Synthetic root
    inbox_only: false
folders:
  archive:
    id: synthetic-archive
domain: example.test
"""
INVALID = [
    "roots: [",
    "roots:\n  a:\n    label: A\n",
    "[]",
    "roots: []",
    "roots: {a: null}",
    "roots: {a: {id: null}}",
    "roots: {a: {id: root, inbox_only: 'false'}}",
    VALID + "folders: []\n",
    VALID + "domain: []\n",
]


def test_valid_map_preserves_roots_folders_and_visibility_contract(tmp_path):
    path = tmp_path / "map.yaml"
    path.write_text(VALID)
    result = load_drive_map(path)
    assert set(result.roots) == {"a"}
    assert result.roots["a"].id == "synthetic-root"
    assert result.roots["a"].label == "Synthetic root"
    assert result.roots["a"].inbox_only is False
    assert result.folders == {"archive": "synthetic-archive"}
    assert result.domain == "example.test"


@pytest.mark.parametrize("content", INVALID)
def test_invalid_map_stops_inventory_before_any_effect(monkeypatch, tmp_path, content):
    from core.pipeline_run import PipelineRun
    from ingest import drive_fetch, drive_inventory

    path = tmp_path / "map.yaml"
    path.write_text(content)
    monkeypatch.setenv("HOTELOPS_DRIVE_MAP", str(path))
    monkeypatch.setattr(sys, "argv", ["ingest.drive_inventory"])

    def forbidden(*args, **kwargs):
        pytest.fail("invalid map reached a client, receipt or publication")

    monkeypatch.setattr(drive_fetch, "_drive_service", forbidden)
    monkeypatch.setattr(PipelineRun, "__enter__", forbidden)
    monkeypatch.setattr(drive_inventory, "capture_observation", forbidden)
    monkeypatch.setattr("core.bq.write.bq_write_validated", forbidden)
    with pytest.raises(ValueError):
        drive_inventory.main()


@pytest.mark.parametrize("content", [VALID, *INVALID[:2]])
def test_status_json_distinguishes_valid_and_unavailable_map(
    monkeypatch, tmp_path, capsys, content
):
    import cli

    path = tmp_path / "map.yaml"
    path.write_text(content)
    monkeypatch.setenv("HOTELOPS_DRIVE_MAP", str(path))
    monkeypatch.setattr(sys, "argv", ["hotelops", "drive", "status", "--json"])

    def query(sql):
        if sql == drive_health.SNAPSHOT_SQL:
            return [{"d": date(2026, 10, 20), "n": 1}]
        if sql == drive_health.COVERAGE_SQL:
            return [
                {
                    "root_key": "a",
                    "root_file_id": "synthetic-root",
                    "observer_email": "robot@example.test",
                    "permissions_observed": True,
                }
            ]
        return []

    monkeypatch.setattr(cli, "query", query)
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["objects"] == 1 and len(result["checks"]) == len(drive_health.CHECKS)
    unknown = any("mappa corrente non disponibile" in w for w in result["warnings"])
    assert unknown is (content != VALID)
