"""Complete observations, atomic partition publication and lineage; synthetic only."""

from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from core import drive_health
from core.bq import write
from core.drive_map import DriveMap, DriveRoot
from ingest import drive_fetch as fetch
from ingest import drive_inventory as inv

DAY = date(2026, 10, 20)


class Drive:
    def __init__(self):
        self.tree = {
            "A": [
                {
                    "id": "B",
                    "name": "B",
                    "mimeType": inv.FOLDER_MIME,
                    "parents": ["A"],
                    "permissions": [],
                }
            ],
            "B": [
                {
                    "id": "F",
                    "name": "file",
                    "mimeType": "application/pdf",
                    "parents": ["B"],
                }
            ],
        }
        self.fail = None
        self.incomplete = False

    def about(self):
        return NS(
            get=lambda **kw: NS(
                execute=lambda: {"user": {"emailAddress": "robot@example.test"}}
            )
        )

    def files(self):
        return self

    def get(self, fileId, **kwargs):
        fid = "A" if fileId == "root" else fileId
        return NS(
            execute=lambda: {
                "id": fid,
                "name": fid,
                "mimeType": inv.FOLDER_MIME,
                "permissions": [],
            }
        )

    def list(self, q, **kwargs):
        folder = q.split("'")[1]

        def execute():
            if folder == self.fail:
                raise RuntimeError("synthetic unavailable root")
            return {
                "files": deepcopy(self.tree.get(folder, [])),
                "incompleteSearch": self.incomplete,
            }

        return NS(execute=execute)


def roots():
    return DriveMap(
        {"a": DriveRoot("a", "root", "A", True), "b": DriveRoot("b", "B", "B")},
        {},
        "example.test",
    )


class BQ:
    """Model the documented load-job commit boundary; never DELETE in advance."""

    def __init__(self):
        self.partitions = {"20261019": [{"file_id": "yesterday"}]}
        self.calls = []
        self.fail = False

    def load_table_from_json(self, rows, table, job_config):
        assert job_config.write_disposition == "WRITE_TRUNCATE"
        assert job_config.create_disposition == "CREATE_NEVER"
        assert job_config.autodetect is False
        day = table.split("$")[1]
        self.calls.append((day, deepcopy(rows)))

        def commit():
            if self.fail:
                raise RuntimeError("synthetic load failure")
            self.partitions[day] = deepcopy(rows)

        return NS(result=commit)


def test_complete_overlapping_roots_then_deleted_and_empty_replace_only_today(
    monkeypatch,
):
    svc, bq, raw = Drive(), BQ(), []
    monkeypatch.setattr(write, "get_client", lambda: bq)

    def capture(payload):
        raw.append(payload)
        return f"raw-observation-{len(raw)}"

    kwargs = {"snapshot_date": DAY, "lookup": lambda _: {}, "capture": capture}
    first = inv.run(svc, roots(), **kwargs)
    assert {r.file_id for r in first} == {"A", "B", "F"}
    assert next(r for r in first if r.file_id == "B").root_keys == ["a", "b"]
    assert next(r for r in first if r.file_id == "B").inventory_root_keys == ["b"]
    assert next(r for r in first if r.file_id == "B").in_inbox_root
    assert all(r.observation_raw_object_id == "raw-observation-1" for r in first)
    assert all(r.observer_email == "robot@example.test" for r in first)
    assert raw[0]["observations"][0]["method"] == "about.get"
    assert {o["method"] for o in raw[0]["observations"]} == {
        "about.get",
        "files.get",
        "files.list",
    }
    inv.run(svc, roots(), **kwargs)
    assert len(bq.partitions["20261020"]) == 3
    svc.tree = {"A": [], "B": []}
    empty = inv.run(svc, roots(), **kwargs)
    assert {r.file_id for r in empty} == {"A", "B"}
    assert {r["file_id"] for r in bq.partitions["20261020"]} == {"A", "B"}
    assert bq.partitions["20261019"] == [{"file_id": "yesterday"}]
    saved = deepcopy(bq.partitions)
    bq.fail = True
    with pytest.raises(write.BigQueryInsertError):
        inv.run(svc, roots(), **kwargs)
    assert bq.partitions == saved


@pytest.mark.parametrize("failure", ["partial", "unavailable", "incomplete"])
def test_partial_or_failed_traversal_never_captures_or_publishes(monkeypatch, failure):
    svc, bq, captured = Drive(), BQ(), []
    monkeypatch.setattr(write, "get_client", lambda: bq)
    kwargs = {}
    if failure == "partial":
        kwargs["roots"] = ["a"]
    elif failure == "unavailable":
        svc.fail = "B"
    else:
        svc.incomplete = True
    with pytest.raises((ValueError, RuntimeError)):
        inv.run(
            svc,
            roots(),
            snapshot_date=DAY,
            lookup=lambda _: {},
            capture=lambda p: captured.append(p),
            **kwargs,
        )
    assert not bq.calls and not captured


def test_dry_run_cannot_capture_or_publish(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run side effect")

    monkeypatch.setattr(write, "get_client", forbidden)
    rows = inv.run(
        Drive(),
        roots(),
        roots=["a"],
        snapshot_date=DAY,
        dry_run=True,
        lookup=lambda _: {},
        capture=forbidden,
    )
    assert rows and all(r.observation_raw_object_id is None for r in rows)


def test_partition_scope_validated_before_client(monkeypatch):
    def forbidden():
        pytest.fail("client obtained before scope validation")

    monkeypatch.setattr(write, "get_client", forbidden)
    row = inv.build_row(
        {"id": "F", "name": "F"},
        snapshot_date=DAY,
        path="A/F",
        root_key="a",
        domain="example.test",
    )
    with pytest.raises(ValueError, match="outside"):
        write.bq_write_validated(
            "example.dataset.inventory",
            [row],
            mode="snapshot",
            natural_key=["snapshot_date"],
            snapshot_partition=date(2026, 10, 19),
        )


@pytest.mark.parametrize(
    "mode, keys, partition",
    [
        ("append", ["snapshot_date"], DAY),
        ("snapshot", [], DAY),
        ("snapshot", ["snapshot_date", "file_id"], DAY),
        ("snapshot", ["snapshot_date"], "2026-10-20"),
    ],
)
def test_partition_option_cannot_bypass_gate_scope(monkeypatch, mode, keys, partition):
    def forbidden():
        pytest.fail("invalid publication scope obtained a client")

    monkeypatch.setattr(write, "get_client", forbidden)
    row = inv.build_row(
        {"id": "F", "name": "F"},
        snapshot_date=DAY,
        path="A/F",
        root_key="a",
        domain="example.test",
    )
    with pytest.raises(ValueError):
        write.bq_write_validated(
            "example.dataset.inventory",
            [row],
            mode=mode,
            natural_key=keys,
            snapshot_partition=partition,
        )


def test_capture_uses_existing_intake_and_rejects_noncanonical_gcs(monkeypatch):
    from ingest import intake, promotion

    calls = []

    def capture(path, source_name, actor):
        calls.append((Path(path).read_text(), source_name, actor))
        return NS(raw_object_id="raw-observation")

    monkeypatch.setattr(intake, "intake_file", capture)
    raw = NS(
        source_name=inv.INVENTORY_SOURCE,
        raw_backend="gcs",
        raw_uri=f"gs://hotelops-raw/{inv.INVENTORY_SOURCE}/2026/10/drive-inventory.json",
        gcs_generation=42,
    )
    monkeypatch.setattr(promotion, "_fetch_raw_object", lambda rid: raw)
    assert (
        inv.capture_observation({"observations": [{"response": {"files": []}}]})
        == "raw-observation"
    )
    assert calls[0][1] == inv.INVENTORY_SOURCE and '"files": []' in calls[0][0]
    raw.raw_uri = "gs://hotelops-raw/wrong-source/metadata.json"
    with pytest.raises(ValueError, match="canonical GCS"):
        inv.capture_observation({"observations": []})


def test_rejected_known_raw_stays_visible_until_canonical_state_changes(
    monkeypatch, tmp_path
):
    source = NS(
        source_name="SYNTHETIC",
        drive_file_id="F",
        drive_folder_id=None,
        drive_export_mime=None,
    )
    monkeypatch.setattr(
        fetch,
        "list_candidates",
        lambda *_: [fetch.DriveCandidate("F", "file", "x", "hash")],
    )
    current = {
        "raw_object_id": "raw-existing",
        "source_name": "SYNTHETIC",
        "current_status": "REJECTED",
        "last_rejection_reason": "VALIDATE_FAIL",
    }

    def forbidden(*args):
        pytest.fail("known raw must not be downloaded, ingested or re-promoted")

    monkeypatch.setattr(fetch, "_download", forbidden)
    args = {
        "hash_exists": lambda _: True,
        "known_lookup": lambda *_: current,
        "intake": forbidden,
        "promote": forbidden,
        "tmp_dir": tmp_path,
    }
    for _ in range(2):
        report = fetch.sync_source(source, None, **args)
        assert "REJECTED" in report.errors[0] and "VALIDATE_FAIL" in report.errors[0]
    current["current_status"] = (
        "CLASSIFIED"  # explicit reclassification is not promotion
    )
    assert fetch.sync_source(source, None, **args).errors
    current["current_status"] = "PROMOTED"  # governed recovery completed elsewhere
    assert fetch.sync_source(source, None, **args).errors == []


def test_health_scopes_current_snapshot_and_reports_root_unknowns_and_age():
    def query(sql):
        if sql == drive_health.SNAPSHOT_SQL:
            assert "v_drive_inventory_current" in sql
            return [{"d": DAY, "n": 3}]
        if sql == drive_health.COVERAGE_SQL:
            return [
                {
                    "root_key": "a",
                    "root_file_id": "A",
                    "objects": 3,
                    "observer_email": "robot@example.test",
                    "permissions_observed": False,
                    "permissions_unknown": 2,
                }
            ]
        return []

    report = drive_health.compute(query, today=date(2026, 10, 22))
    assert report.objects == 3 and report.age_days == 2
    assert report.coverage[0]["root_file_id"] == "A"
    assert any("audit incompleto" in w for w in report.warnings)


def test_capture_real_intake_and_storage_path_with_synthetic_clients(monkeypatch):
    import json

    from core.lineage import raw_storage
    from core.pipeline_run import PipelineRun

    registered, blobs = {}, {}

    class Client:
        def query(self, sql, **kwargs):
            if "SELECT *" in sql:
                return NS(result=lambda: [NS(**next(iter(registered.values())))])
            return NS(result=list)

        def load_table_from_json(self, rows, table, job_config):
            assert job_config.write_disposition == "WRITE_APPEND"
            if table.endswith("f_raw_objects"):
                for row in rows:
                    registered[row["raw_object_id"]] = row
            return NS(result=lambda: None)

    class Blob:
        generation = 42

        def __init__(self, key):
            self.key = key

        def upload_from_filename(self, filename, **kwargs):
            blobs[self.key] = Path(filename).read_bytes()

    client = Client()
    monkeypatch.setattr("core.bq.client.get_client", lambda: client)
    monkeypatch.setattr(write, "get_client", lambda: client)
    monkeypatch.setattr(PipelineRun, "_insert_final", lambda self: None)
    monkeypatch.setattr(
        raw_storage, "_storage_client", lambda: NS(bucket=lambda bucket: NS(blob=Blob))
    )
    payload = {"observations": [{"method": "files.list", "response": {"files": []}}]}
    rid = inv.capture_observation(payload)
    row = registered[rid]
    assert row["raw_backend"] == "gcs" and row["gcs_generation"] == 42
    key = next(iter(blobs))
    assert key.startswith(inv.INVENTORY_SOURCE + "/") and key.endswith(
        "/drive-inventory.json"
    )
    assert row["raw_uri"] == "gs://hotelops-raw/" + key
    assert json.loads(blobs[key]) == payload


def test_permission_identity_hidden_is_not_a_clean_audit():
    row = inv.build_row(
        {"id": "F", "name": "F", "permissions": [{"type": "user"}]},
        snapshot_date=DAY,
        path="A/F",
        root_key="a",
        domain="example.test",
    )
    assert not row.permissions_observed


def test_health_empty_exception_and_new_configured_root_are_explicit():
    def query(sql):
        if sql == drive_health.SNAPSHOT_SQL:
            return [{"d": DAY, "n": 1}]
        if sql == drive_health.COVERAGE_SQL:
            return []
        raise RuntimeError()

    report = drive_health.compute(query, today=DAY, expected_roots={"new": "NEW"})
    assert "RuntimeError" in report.error
    assert any("new: radice configurata non coperta" in w for w in report.warnings)
