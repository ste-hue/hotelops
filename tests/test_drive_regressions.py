"""Regression coverage for the six independently reproduced PR155 failures.

Only Drive/BQ boundaries are synthetic. Product traversal, orchestration,
config imports, receipt handling, and response construction run unchanged.
"""

import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

from core import drive_health
from core.drive_map import DriveMap, DriveRoot
from ingest import drive_fetch as fetch
from ingest import drive_inventory as inv

DAY = date(2026, 10, 20)


class Drive:
    def __init__(self, tree):
        self.tree = tree

    def files(self):
        return self

    def list(self, **kwargs):
        key = re.match(r"'([^']+)'", kwargs["q"]).group(1)
        return NS(execute=lambda: {"files": self.tree.get(key, [])})

    def get(self, **kwargs):
        item = next(
            x
            for children in self.tree.values()
            for x in children
            if x["id"] == kwargs["fileId"]
        )
        return NS(execute=lambda: item)


def drive_map():
    return DriveMap({"a": DriveRoot("a", "root-a", "A")}, {}, "example.test")


def test_default_inventory_lookup_reaches_injected_client(monkeypatch):
    calls = []

    def query(sql, **kwargs):
        calls.append(sql)
        return NS(
            result=lambda: [
                NS(content_hash="synthetic-md5", raw_object_id="raw-fixture")
            ]
        )

    monkeypatch.setattr("core.bq.client.get_client", lambda: NS(query=query))
    svc = Drive(
        {
            "root-a": [
                {
                    "id": "file-a",
                    "name": "fixture.bin",
                    "md5Checksum": "synthetic-md5",
                    "mimeType": "application/octet-stream",
                }
            ]
        }
    )
    rows = inv.run(svc, drive_map(), snapshot_date=DAY, dry_run=True)
    assert rows[0].raw_object_id == "raw-fixture"
    assert len(calls) == 1


def test_inventory_cli_dry_run_must_not_insert_receipt(monkeypatch):
    writes = []
    client = NS(insert_rows_json=lambda table, rows: writes.append((table, rows)) or [])
    monkeypatch.setattr("core.bq.client.get_client", lambda: client)
    monkeypatch.setattr(inv, "load_drive_map", drive_map)
    svc = Drive(
        {
            "root-a": [
                {
                    "id": "file-a",
                    "name": "fixture",
                    "mimeType": "application/vnd.google-apps.document",
                }
            ]
        }
    )
    monkeypatch.setattr(fetch, "_drive_service", lambda *_: svc)
    monkeypatch.setattr(
        sys,
        "argv",
        ["drive_inventory", "--dry-run", "--key", "/nonexistent/fixture-key"],
    )
    inv.main()
    assert writes == [], f"dry run attempted pipeline writes: {writes}"


def test_overlapping_roots_must_not_duplicate_snapshot_keys():
    svc = Drive(
        {
            "root-a": [{"id": "root-b", "name": "B", "mimeType": inv.FOLDER_MIME}],
            "root-b": [
                {"id": "file-a", "name": "fixture", "mimeType": "application/pdf"}
            ],
        }
    )
    dmap = DriveMap(
        {"a": DriveRoot("a", "root-a", "A"), "b": DriveRoot("b", "root-b", "B")},
        {},
        "example.test",
    )
    rows = inv.run(svc, dmap, snapshot_date=DAY, dry_run=True)
    keys = [(r.snapshot_date, r.file_id) for r in rows]
    assert len(keys) == len(set(keys)), f"duplicate snapshot keys: {keys}"


def test_unknown_permissions_must_differ_from_observed_empty_permissions():
    meta = {"id": "file-a", "name": "fixture", "mimeType": "application/pdf"}
    args = {
        "snapshot_date": DAY,
        "path": "A/fixture",
        "root_key": "a",
        "domain": "example.test",
    }
    unknown = inv.build_row(meta, **args)
    empty = inv.build_row({**meta, "permissions": []}, **args)
    assert unknown.model_dump() != empty.model_dump(), (
        "unknown permission coverage equals observed empty"
    )


def test_failed_promotion_must_not_become_silent_success_on_retry(
    monkeypatch, tmp_path
):
    svc = Drive(
        {
            "root-a": [
                {
                    "id": "file-a",
                    "name": "fixture.bin",
                    "mimeType": "application/octet-stream",
                    "md5Checksum": "synthetic-md5",
                }
            ]
        }
    )
    source = NS(
        source_name="SYNTHETIC",
        drive_file_id="file-a",
        drive_folder_id=None,
        drive_export_mime=None,
    )
    known = set()
    attempts = []

    def download(svc, fid, dest, export_mime=None):
        Path(dest).write_bytes(b"synthetic")
        return dest

    def intake(path, source_name):
        known.add("synthetic-md5")
        return NS(raw_object_id="raw-fixture", deduped=False)

    def promote(rid):
        attempts.append(rid)
        return NS(status="REJECTED", reason="synthetic policy denial")

    monkeypatch.setattr(fetch, "_download", download)
    options = {
        "hash_exists": lambda h: h in known,
        "intake": intake,
        "promote": promote,
        "tmp_dir": tmp_path,
    }
    first = fetch.sync_source(source, svc, **options)
    second = fetch.sync_source(source, svc, **options)
    assert first.errors and first.promoted == 0 and attempts == ["raw-fixture"]
    assert second.errors, f"unresolved rejection disappeared: {second}"


def test_missing_health_view_must_return_unavailable_instead_of_crash():
    def query(sql):
        if sql == drive_health.SNAPSHOT_SQL:
            return [{"d": DAY, "n": 1}]
        raise RuntimeError("synthetic missing view")

    health = drive_health.compute(query)
    assert health.error or len(health.checks) < len(drive_health.CHECKS)
