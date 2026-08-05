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


def _dati_whatsapp(n_importanti: int = 1, **over) -> dict:
    base = {
        "finestra": (datetime(2026, 8, 3), datetime(2026, 8, 4, 7, 0)),
        "importanti": [
            {"entity_id": "INTUR", "subject": f"Avviso {i}",
             "mittente": "ae@pec.agenziaentrate.it",
             "primary_category": "FISCO", "proiettato": True}
            for i in range(n_importanti)
        ],
        "anomalie_ricevute": [], "errori_parsing": [], "non_sincronizzati": [],
        "ambigui": [], "non_classificati": [], "risolti": [],
        "totali_per_casella": {"in.tur@pec.it": 6, "orti@pec.it": 3},
        "totali_per_entity": {"INTUR": 6, "ORTI": 3},
    }
    base.update(over)
    return base


def test_whatsapp_zero_importanti_dice_niente_di_rilevante():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=0))
    assert msg.splitlines()[0] == "PEC 04/08 — niente di rilevante"
    assert "•" not in msg


def test_whatsapp_riga_di_salute_sempre_presente():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=0))
    assert msg.splitlines()[-1] == "9 nuove (INTUR 6, ORTI 3) · 0 non classificate"


def test_whatsapp_un_importante():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=1))
    righe = msg.splitlines()
    assert righe[0] == "PEC 04/08 — 1 da guardare"
    assert righe[1] == "• INTUR [FISCO] Avviso 0 — da ae@pec.agenziaentrate.it"


def test_whatsapp_tronca_a_otto_e_conta_il_resto():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=9))
    righe = msg.splitlines()
    assert righe[0] == "PEC 04/08 — 9 da guardare"
    assert sum(1 for r in righe if r.startswith("•")) == 8
    assert "…e altre 1" in righe


def test_whatsapp_conta_i_non_classificati():
    dati = _dati_whatsapp(n_importanti=0, non_classificati=[
        {"entity_id": "ORTI", "subject": "x", "mittente": "a@b.it"},
        {"entity_id": "ORTI", "subject": "y", "mittente": "c@d.it"},
    ])
    assert _render_whatsapp(dati).splitlines()[-1].endswith("· 2 non classificate")


def test_whatsapp_nessun_messaggio_nella_finestra():
    dati = _dati_whatsapp(n_importanti=0, totali_per_casella={}, totali_per_entity={})
    assert _render_whatsapp(dati).splitlines()[-1] == "0 nuove · 0 non classificate"
