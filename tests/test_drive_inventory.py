"""drive_inventory: righe dall'API, percorso, permessi, ponte per hash
(spec 2026-10-17 drive-agent-friendly, P4/P7). Nessuna rete."""

from datetime import date

from core.drive_map import DriveMap, DriveRoot, load_drive_map
from ingest.drive_inventory import attach_raw_object_ids, build_row, walk_root

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
D = date(2026, 10, 17)
DOMAIN = "example.org"

TREE = {
    "root1": [
        {
            "id": "f06",
            "name": "documents",
            "mimeType": FOLDER,
            "parents": ["root1"],
            "owners": [{"emailAddress": "owner@example.org"}],
            "permissions": [
                {"type": "user", "emailAddress": "owner@example.org"}
            ],
        },
        {
            "id": "loose",
            "name": "Example.docx",
            "mimeType": "application/x",
            "size": "44241",
            "md5Checksum": "m9",
            "createdTime": "2026-10-01T10:00:00Z",
            "parents": ["root1"],
            "owners": [{"emailAddress": "owner@example.org"}],
        },
    ],
    "f06": [
        {
            "id": "c1",
            "name": "example.pdf",
            "mimeType": "application/pdf",
            "size": "100",
            "md5Checksum": "mc",
            "sha256Checksum": "sc",
            "modifiedTime": "2026-10-16T13:46:14.701Z",
            "createdTime": "2026-10-16T13:47:21.441Z",
            "parents": ["f06"],
            "owners": [{"emailAddress": "owner@example.org"}],
            "permissions": [
                {"type": "anyone"},
                {"type": "user", "emailAddress": "owner@example.org"},
                {"type": "user", "emailAddress": "banca@mps.it"},
            ],
        },
        {
            "id": "s1",
            "name": "example.pdf",
            "mimeType": SHORTCUT,
            "parents": ["f06"],
            "shortcutDetails": {"targetId": "c1"},
        },
        {"id": "loop", "name": "loop", "mimeType": FOLDER, "parents": ["f06"]},
    ],
    "loop": [
        {
            "id": "f06",
            "name": "documents",
            "mimeType": FOLDER,
            "parents": ["loop"],
        },  # ciclo
    ],
}


def _list(svc, folder_id):
    return TREE.get(folder_id, [])


def test_walk_percorso_tipi_e_ciclo():
    root = DriveRoot(key="investimenti", id="root1", label="Workspace")
    rows = walk_root(None, root, snapshot_date=D, domain=DOMAIN, list_fn=_list)
    by_id = {r.file_id: r for r in rows}
    assert by_id["c1"].path == "Workspace/documents/example.pdf"
    assert by_id["f06"].is_folder and by_id["s1"].is_shortcut
    assert by_id["s1"].shortcut_target_id == "c1"
    assert (
        by_id["loose"].parent_id == "root1"
        and by_id["loose"].root_key == "investimenti"
    )
    # il ciclo loop → f06 non rientra: f06 è elencato due volte come riga ma visitato una volta sola
    assert sum(1 for r in rows if r.file_id == "f06") == 2
    assert len(rows) == 6


def test_permessi_anyone_e_fuori_dominio():
    r = build_row(
        TREE["f06"][0], snapshot_date=D, path="x", root_key="k", domain=DOMAIN
    )
    assert r.perm_anyone is True
    assert r.perm_outside_domain == ["banca@mps.it"]
    assert r.size_bytes == 100 and r.md5 == "mc" and r.sha256 == "sc"
    assert r.modified_time.isoformat().startswith("2026-10-16T13:46:14")


def test_file_nativo_senza_hash_e_senza_size():
    meta = {
        "id": "g",
        "name": "Doc",
        "mimeType": "application/vnd.google-apps.document",
    }
    r = build_row(meta, snapshot_date=D, path="x", root_key="k", domain=DOMAIN)
    assert r.md5 is None and r.size_bytes is None and not r.perm_anyone


def test_ponte_per_hash_assegna_raw_object_id():
    root = DriveRoot(key="investimenti", id="root1", label="Workspace")
    rows = walk_root(None, root, snapshot_date=D, domain=DOMAIN, list_fn=_list)
    asked: list[list[str]] = []

    def lookup(hashes):
        asked.append(hashes)
        return {"mc": "raw-example"}

    attach_raw_object_ids(rows, lookup)
    assert asked == [["m9", "mc"]]  # una sola query, hash ordinati, niente None
    by_id = {r.file_id: r for r in rows}
    assert by_id["c1"].raw_object_id == "raw-example"
    assert by_id["loose"].raw_object_id is None


def test_drive_map_private_runtime_override(monkeypatch, tmp_path):
    p = tmp_path / "drive-map.yaml"
    p.write_text(
        "roots:\n  synthetic:\n    id: fixture-root\n    inbox_only: true\nfolders: {}\ndomain: example.test\n"
    )
    monkeypatch.setenv("HOTELOPS_DRIVE_MAP", str(p))
    m = load_drive_map()
    assert isinstance(m, DriveMap)
    assert m.roots["synthetic"].id == "fixture-root"
    assert m.roots["synthetic"].inbox_only is True
    assert m.domain == "example.test"


def test_public_template_requires_explicit_runtime_roots(monkeypatch):
    import pytest

    monkeypatch.delenv("HOTELOPS_DRIVE_MAP", raising=False)
    with pytest.raises(ValueError, match="HOTELOPS_DRIVE_MAP"):
        load_drive_map()
