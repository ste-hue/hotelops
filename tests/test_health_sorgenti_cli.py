"""cmd_health --json stampa il blocco SORGENTI e si ferma (spec 2026-09-09 §7)."""

import json
from argparse import Namespace
from datetime import date
from unittest.mock import patch

from core.freshness import SourceFreshness


def _item(name, status):
    return SourceFreshness(
        source_name=name,
        tier="E",
        mode="SEMI",
        owner="Stefano",
        status=status,
        covered_through=date(2026, 6, 30),
        expected_through=date(2026, 8, 31),
        age_days=71,
        last_raw_at=None,
        per_dim=[],
        blocks=["cash_control"],
        action="→ x\n  poi: y",
    )


def test_health_json_stampa_solo_sorgenti(capsys):
    from verticals.condges.cli_commands import cmd_health

    with (
        patch(
            "core.freshness.compute",
            return_value=[_item("MPS_BANCA_ORTI_APPEND", "STALE")],
        ) as comp,
        patch("core.lineage.source_resolver.load_registry") as lr,
        patch("cli.query") as q,
    ):
        cmd_health(Namespace(json=True, source=None, all=False))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["source_name"] == "MPS_BANCA_ORTI_APPEND"
    assert data[0]["status"] == "STALE"
    assert comp.called and lr.called
    assert not q.called  # con --json nessun altro blocco viene eseguito


def test_health_source_filtra_una_riga(capsys):
    from verticals.condges.cli_commands import cmd_health

    items = [
        _item("MPS_BANCA_ORTI_APPEND", "STALE"),
        _item("SELLA_BANCA_INTUR_APPEND", "OK"),
    ]
    with (
        patch("core.freshness.compute", return_value=items),
        patch("core.lineage.source_resolver.load_registry"),
        patch("cli.query"),
    ):
        cmd_health(Namespace(json=True, source="SELLA_BANCA_INTUR_APPEND", all=False))
    data = json.loads(capsys.readouterr().out)
    assert [d["source_name"] for d in data] == ["SELLA_BANCA_INTUR_APPEND"]
