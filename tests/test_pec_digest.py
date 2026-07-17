"""Digest PEC: finestra, formato, sezioni, checkpoint."""

from __future__ import annotations

from datetime import datetime

from ingest.pec.digest import _render_markdown, _percorso_file


def _dati_finti() -> dict:
    return {
        "finestra": (datetime(2026, 7, 10), datetime(2026, 7, 17)),
        "importanti": [
            {"entity_id": "ORTI", "subject": "Diffida", "mittente": "avv@legalmail.it",
             "primary_category": "LEGALE", "proiettato": True},
        ],
        "anomalie_ricevute": [
            {"entity_id": "INTUR", "subject": "x", "tipo": "ANOMALIA"},
        ],
        "errori_parsing": [], "non_sincronizzati": [],
        "ambigui": [], "non_classificati": [
            {"entity_id": "STEFANO_PERSONALE", "subject": "Ciao", "mittente": "a@b.it"},
        ],
        "risolti": [], "totali_per_casella": {"orti@pec.it": 12},
    }


def test_render_markdown_sezioni_in_ordine():
    md = _render_markdown(_dati_finti(), solo_anomalie=False)
    i_imp = md.index("## Messaggi importanti")
    i_ano = md.index("## Ricevute anomale")
    i_ncl = md.index("## Da rivedere")
    assert i_imp < i_ano < i_ncl
    assert "Diffida" in md and "STEFANO_PERSONALE" in md


def test_solo_anomalie_esclude_importanti():
    md = _render_markdown(_dati_finti(), solo_anomalie=True)
    assert "## Messaggi importanti" not in md
    assert "## Ricevute anomale" in md


def test_percorso_file_per_data():
    p = _percorso_file(datetime(2026, 7, 17))
    assert str(p).endswith("_digest/2026/07/2026-07-17.md")


def test_digest_run_row_valida():
    from core.schemas import PecDigestRunRow, validate_batch

    validate_batch([{
        "run_id": "d-1", "started_at": datetime(2026, 7, 17, 8, 0),
        "finished_at": None, "status": "RUNNING",
        "from_ts": datetime(2026, 7, 10), "to_ts": datetime(2026, 7, 17),
        "params": "{}",
    }], PecDigestRunRow, context="test")
