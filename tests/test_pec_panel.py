"""Projection pannello CEO: sanitizzazione, whitelist, idempotenza, traversal."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.pec.panel import (
    _destination_path,
    _sanitize_filename,
    projection_key,
)


def test_sanitize_basename_e_traversal():
    assert _sanitize_filename("../../evil.pdf") == "evil.pdf"
    assert _sanitize_filename("..\\..\\evil.pdf") == "evil.pdf"
    assert _sanitize_filename("a/b/c.pdf") == "c.pdf"
    assert ".." not in _sanitize_filename("do..c.pdf../..")
    assert _sanitize_filename("  ") == "allegato"


def test_sanitize_control_chars_e_lunghezza():
    assert "\n" not in _sanitize_filename("a\nb.pdf")
    lungo = "x" * 400 + ".pdf"
    out = _sanitize_filename(lungo)
    assert len(out) <= 180 and out.endswith(".pdf")


def test_destination_dentro_root():
    from datetime import datetime

    rel = _destination_path("ORTI", "LEGALE", datetime(2026, 7, 3), "diffida.pdf")
    assert rel == Path("ORTI/PEC/Legale/2026-07 - diffida.pdf")


def test_destination_entity_fuori_whitelist_rifiutata():
    from datetime import datetime

    with pytest.raises(ValueError, match="whitelist"):
        _destination_path("STEFANO_PERSONALE", "LEGALE", datetime(2026, 7, 3), "x.pdf")


def test_destination_traversal_nel_nome_resta_sotto_root():
    from datetime import datetime

    rel = _destination_path("ORTI", "BANCA", datetime(2026, 1, 1), "../../../etc/passwd")
    assert not str(rel).startswith("..")
    assert rel.parts[0] == "ORTI"


def test_projection_key_deterministica_e_sensibile():
    k1 = projection_key("m1", "sha", "ORTI/PEC/Banca/x.pdf")
    assert k1 == projection_key("m1", "sha", "ORTI/PEC/Banca/x.pdf")
    assert k1 != projection_key("m2", "sha", "ORTI/PEC/Banca/x.pdf")
    assert k1 != projection_key("m1", "sha", "ORTI/PEC/Banca/y.pdf")


def test_riga_projection_valida():
    from datetime import datetime

    from core.schemas import PecPanelProjectionRow, validate_batch

    validate_batch([{
        "projection_key": "k", "msgid": "m", "sha256": "s", "entity_id": "ORTI",
        "gcs_uri": "gs://orti-raw/x", "destination_path": "ORTI/PEC/Banca/x.pdf",
        "run_id": "r", "projected_at": datetime(2026, 7, 17), "status": "COPIED",
    }], PecPanelProjectionRow, context="test")


def test_riga_projection_personale_rifiutata():
    """I-PEC-3 anche a livello schema/whitelist: il runner non deve mai
    costruire path per STEFANO_PERSONALE (il test di _destination_path sopra);
    qui si verifica che la whitelist sia quella di config, non un'esclusione."""
    from core.config import PANEL_ENTITIES

    assert PANEL_ENTITIES == ["INTUR", "ORTI", "VIGNA"]
    assert "STEFANO_PERSONALE" not in PANEL_ENTITIES
