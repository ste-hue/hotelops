"""Digest PEC: finestra, formato, sezioni, checkpoint."""

from __future__ import annotations

from datetime import datetime

from ingest.pec.digest import _render_markdown, _percorso_file, _render_whatsapp


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


def _dati_novita(n: int = 1, **over) -> dict:
    base = {
        "finestra": (datetime(2026, 8, 5), datetime(2026, 8, 6, 7, 0)),
        "in_arrivo": 17,
        "novita": [
            {"entity_id": "INTUR", "mittente": f"nuovo{i}@pec.it",
             "subject": f"Sollecito {i}", "allegati": ["Sollecito.pdf"],
             "mittente_nuovo": True, "oggetto_nuovo": True, "allegati_nuovi": True}
            for i in range(n)
        ],
    }
    base.update(over)
    return base


def test_whatsapp_zero_novita_una_riga_sola():
    msg = _render_whatsapp(_dati_novita(n=0))
    assert msg == "PEC 06/08 — niente di nuovo · 17 in arrivo"


def test_whatsapp_una_novita_mittente_nuovo():
    righe = _render_whatsapp(_dati_novita(n=1)).splitlines()
    assert righe[0] == "PEC 06/08 — 1 novità"
    assert righe[1] == "• INTUR — mittente nuovo: nuovo0@pec.it"
    assert righe[2] == '  "Sollecito 0" [Sollecito.pdf]'
    assert righe[-1] == "17 in arrivo."


def test_whatsapp_motivo_oggetto_quando_il_mittente_e_noto():
    dati = _dati_novita(n=1)
    dati["novita"][0].update(mittente_nuovo=False, allegati_nuovi=False)
    assert _render_whatsapp(dati).splitlines()[1] == (
        "• INTUR — oggetto nuovo da nuovo0@pec.it")


def test_whatsapp_motivo_allegati_quando_mittente_e_oggetto_sono_noti():
    dati = _dati_novita(n=1)
    dati["novita"][0].update(mittente_nuovo=False, oggetto_nuovo=False)
    assert _render_whatsapp(dati).splitlines()[1] == (
        "• INTUR — allegati nuovi da nuovo0@pec.it")


def test_whatsapp_senza_allegati_nessuna_parentesi():
    dati = _dati_novita(n=1)
    dati["novita"][0]["allegati"] = []
    assert _render_whatsapp(dati).splitlines()[2] == '  "Sollecito 0"'


def test_whatsapp_tronca_a_otto_e_conta_il_resto():
    righe = _render_whatsapp(_dati_novita(n=10)).splitlines()
    assert righe[0] == "PEC 06/08 — 10 novità"
    assert sum(1 for r in righe if r.startswith("•")) == 8
    assert "…e altre 2" in righe
