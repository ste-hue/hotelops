"""Sezione DRIVE di health e manifest di cartella con query finta
(spec 2026-10-17 drive-agent-friendly)."""

import json
from argparse import Namespace
from unittest.mock import patch

from core import drive_health
from core.drive_manifest import render_manifest


class FakeQuery:
    def __init__(self, by_view: dict[str, list[dict]], snapshot=("2026-10-17", 1234)):
        self.by_view, self.snapshot = by_view, snapshot
        self.calls: list[str] = []

    def __call__(self, sql: str) -> list[dict]:
        self.calls.append(sql)
        if (
            "FROM `hotelops-suite.hotelops`.f_drive_inventory" in sql
            and "MAX(snapshot_date)" in sql
        ):
            d, n = self.snapshot
            return [{"d": d, "n": n}]
        for name, rows in self.by_view.items():
            if f"v_drive_{name}" in sql:
                return rows
        return []


def test_compute_conta_gruppi_distinti_per_i_duplicati():
    q = FakeQuery(
        {
            "duplicati": [
                {
                    "md5": "x",
                    "copie": 3,
                    "path": "A/example.pdf",
                    "name": "example.pdf",
                    "e_la_prima": True,
                },
                {
                    "md5": "x",
                    "copie": 3,
                    "path": "B/example.pdf",
                    "name": "example.pdf",
                    "e_la_prima": False,
                },
                {
                    "md5": "x",
                    "copie": 3,
                    "path": "C/example.pdf",
                    "name": "example.pdf",
                    "e_la_prima": False,
                },
            ],
            "permessi": [
                {
                    "path": "ExampleFolder",
                    "esposizione": "ANYONE",
                    "perm_outside_domain": [],
                }
            ],
            "radice": [],
            "lineage": [],
        }
    )
    h = drive_health.compute(q)
    counts = {c.name: c.count for c in h.checks}
    assert counts == {"duplicati": 1, "permessi": 1, "radice": 0, "lineage": 0}
    assert h.snapshot_date == "2026-10-17" and h.objects == 1234


def test_render_mostra_i_primi_e_i_segni():
    q = FakeQuery(
        {
            "duplicati": [
                {
                    "md5": "x",
                    "copie": 3,
                    "path": "A/example.pdf",
                    "name": "c",
                    "e_la_prima": True,
                }
            ],
            "permessi": [
                {
                    "path": "ExampleFolder",
                    "esposizione": "ANYONE",
                    "perm_outside_domain": [],
                }
            ],
            "radice": [{"name": "Example.docx", "giorni_in_radice": 12}],
            "lineage": [],
        }
    )
    out = drive_health.render_text(drive_health.compute(q))
    assert "DRIVE" in out and "fotografia 2026-10-17 · 1234 oggetti" in out
    assert "🔴   1 oggetti visibili fuori" in out
    assert "ExampleFolder  [ANYONE]" in out
    assert "A/example.pdf  (×3)" in out
    assert "✓    0 file in attesa" in out


def test_senza_fotografia_dice_che_il_job_non_e_mai_girato():
    q = FakeQuery({}, snapshot=(None, 0))
    h = drive_health.compute(q)
    assert h.snapshot_date is None and h.checks == []
    assert "mai girato" in drive_health.render_text(h)


def test_tabella_assente_non_esplode():
    def boom(sql):
        raise RuntimeError("Not found: Table f_drive_inventory")

    h = drive_health.compute(boom)
    assert h.error and "Not found" in h.error
    assert "non disponibile" in drive_health.render_text(h)


def test_health_testo_include_la_sezione_drive(capsys):
    from verticals.condges.cli_commands import cmd_health

    with (
        patch("core.freshness.compute", return_value=[]),
        patch("core.lineage.source_resolver.load_registry"),
        patch("cli.bq"),
        patch("core.pipeline_run.check_pipeline_staleness", return_value=[]),
        patch("core.pipeline_run.check_watermark_staleness", return_value=[]),
        patch(
            "cli.query",
            side_effect=lambda sql: (
                [{"d": None, "n": 0}] if "f_drive_inventory" in sql else []
            ),
        ),
    ):
        cmd_health(Namespace(json=False, source=None, all=False))
    out = capsys.readouterr().out
    assert "DRIVE" in out and "mai girato" in out


def test_health_json_resta_la_lista_sorgenti(capsys):
    from verticals.condges.cli_commands import cmd_health

    with (
        patch("core.freshness.compute", return_value=[]),
        patch("core.lineage.source_resolver.load_registry"),
        patch("cli.query"),
    ):
        cmd_health(Namespace(json=True, source=None, all=False))
    assert json.loads(capsys.readouterr().out) == []


def test_manifest_render():
    rows = [
        {
            "snapshot_date": "2026-10-17",
            "file_id": "c1",
            "name": "example.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1048576,
            "sha256": "012345671234567890",
            "md5": "m",
            "modified_time": "2026-10-16 13:46:14+00:00",
            "owner_email": "owner@example.org",
            "is_folder": False,
            "is_shortcut": False,
            "shortcut_target_id": None,
            "perm_anyone": False,
            "perm_outside_domain": [],
            "raw_object_id": "12345678-abc",
            "copie": 3,
            "source_name": None,
        },
        {
            "snapshot_date": "2026-10-17",
            "file_id": "f1",
            "name": "sample_folder",
            "mime_type": FOLDER_MIME,
            "size_bytes": None,
            "sha256": None,
            "md5": None,
            "modified_time": None,
            "owner_email": None,
            "is_folder": True,
            "is_shortcut": False,
            "shortcut_target_id": None,
            "perm_anyone": True,
            "perm_outside_domain": [],
            "raw_object_id": None,
            "copie": 1,
            "source_name": None,
        },
    ]

    def q(sql):
        if "WHERE file_id =" in sql:
            return [
                {
                    "path": "Workspace/documents",
                    "name": "documents",
                }
            ]
        return rows

    md = render_manifest(q, "folder-example")
    assert md.startswith("# Manifest — Workspace/documents")
    assert (
        "| [example.pdf](https://drive.google.com/file/d/c1) | pdf | 1.0 MB | 2026-10-16 | `012345671234` | 12345678 | 3 | - |"
        in md
    )
    assert (
        "[sample_folder](https://drive.google.com/drive/folders/f1) | cartella"
        in md
        and "ANYONE" in md
    )
    assert "Oggetti: 2 · con copie altrove: 1 · pubblici: 1." in md


FOLDER_MIME = "application/vnd.google-apps.folder"
