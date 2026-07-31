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


# --- Fix post-review: retry delle proiezioni FAILED (idempotenza) ---------


def test_gia_proiettate_filtra_su_status_copied_o_skipped():
    """La query di _gia_proiettate deve escludere le FAILED dal set 'già
    fatto', altrimenti una proiezione fallita non verrebbe mai ritentata."""
    from ingest.pec.panel import _gia_proiettate

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def result(self):
            return self._rows

    class _FakeClient:
        def __init__(self):
            self.ultima_sql = None

        def query(self, sql):
            self.ultima_sql = sql
            return _FakeResult([])

    client = _FakeClient()
    _gia_proiettate(client)
    assert "WHERE status IN" in client.ultima_sql
    assert "COPIED" in client.ultima_sql and "SKIPPED_EXISTS" in client.ultima_sql
    assert "FAILED" not in client.ultima_sql


def test_sync_panel_download_fallito_rimuove_file_parziale_e_segna_failed(
    tmp_path, monkeypatch
):
    """Un download GCS che scrive parte del file e poi solleva non deve
    lasciare un file parziale sul disco (verrebbe scambiato per
    SKIPPED_EXISTS al prossimo run): va ripulito e la riga marcata FAILED."""
    import ingest.pec.panel as panel
    from datetime import datetime
    from types import SimpleNamespace

    monkeypatch.setattr(panel, "PANEL_ROOT", str(tmp_path))

    cand = SimpleNamespace(
        msgid="m1", sha256="s1", nome_file="doc.pdf",
        gcs_uri="gs://bucket/doc.pdf", size_bytes=10,
        entity_id="ORTI", data_evento=datetime(2026, 7, 1),
        primary_category="LEGALE",
    )
    monkeypatch.setattr(panel, "_candidati", lambda client: [cand])
    monkeypatch.setattr(panel, "_gia_proiettate", lambda client: set())

    def _download_scrive_e_fallisce(gcs_uri, dest):
        dest.write_bytes(b"parziale")
        raise RuntimeError("connessione GCS interrotta")

    monkeypatch.setattr(panel, "_download_gcs", _download_scrive_e_fallisce)

    written_rows = []
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, mode="append": written_rows.extend(rows),
    )
    fake_client = SimpleNamespace(query=lambda sql: SimpleNamespace(result=lambda: []))
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    report = panel.sync_panel(dry_run=False, verify=False)

    dest_rel = panel._destination_path(
        cand.entity_id, cand.primary_category, cand.data_evento, cand.nome_file
    )
    dest_abs = tmp_path / dest_rel
    assert not dest_abs.exists(), "il file parziale deve essere rimosso"
    assert report["falliti"] == 1
    assert report["copiati"] == 0
    assert len(written_rows) == 1
    assert written_rows[0].status == "FAILED"


def test_sync_panel_ritenta_dopo_failed_precedente(tmp_path, monkeypatch):
    """Integrazione dei due fix: una proiezione FAILED in un run precedente
    viene ritentata (e questa volta riesce) in un run successivo, perché
    _gia_proiettate non la conta come 'già fatta'."""
    import ingest.pec.panel as panel
    from datetime import datetime
    from types import SimpleNamespace

    monkeypatch.setattr(panel, "PANEL_ROOT", str(tmp_path))

    cand = SimpleNamespace(
        msgid="m1", sha256="s1", nome_file="doc.pdf",
        gcs_uri="gs://bucket/doc.pdf", size_bytes=10,
        entity_id="ORTI", data_evento=datetime(2026, 7, 1),
        primary_category="LEGALE",
    )
    monkeypatch.setattr(panel, "_candidati", lambda client: [cand])

    tabella: list[dict] = []

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def result(self):
            return self._rows

    class _FakeClient:
        def query(self, sql):
            if "projection_key FROM" in sql:
                allowed = {"COPIED", "SKIPPED_EXISTS"}
                rows = [
                    SimpleNamespace(projection_key=r["projection_key"])
                    for r in tabella if r["status"] in allowed
                ]
                return _FakeResult(rows)
            return _FakeResult([])  # _scrivi_indice: non rilevante qui

    fake_client = _FakeClient()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, mode="append": tabella.extend(
            {"projection_key": r.projection_key, "status": r.status} for r in rows
        ),
    )

    # Run 1: il download fallisce e lascia (per un istante) un file parziale.
    def _download_fallisce(gcs_uri, dest):
        dest.write_bytes(b"parziale")
        raise RuntimeError("errore transitorio")

    monkeypatch.setattr(panel, "_download_gcs", _download_fallisce)
    report1 = panel.sync_panel(dry_run=False, verify=False)
    assert report1["falliti"] == 1
    assert tabella[-1]["status"] == "FAILED"

    dest_rel = panel._destination_path(
        cand.entity_id, cand.primary_category, cand.data_evento, cand.nome_file
    )
    dest_abs = tmp_path / dest_rel
    assert not dest_abs.exists()

    # Run 2: stesso candidato, ma stavolta il download riesce.
    def _download_riesce(gcs_uri, dest):
        dest.write_bytes(b"contenuto completo")

    monkeypatch.setattr(panel, "_download_gcs", _download_riesce)
    report2 = panel.sync_panel(dry_run=False, verify=False)

    assert report2["copiati"] == 1
    assert report2["falliti"] == 0
    assert dest_abs.exists()
    assert tabella[-1]["status"] == "COPIED"


def test_sync_panel_collisione_contenuti_diversi_disambigua(tmp_path, monkeypatch):
    """Due allegati con stesso nome nello stesso mese ma contenuto diverso
    (es. tre RicevutaCu.pdf di pratiche camerali distinte) devono finire
    ENTRAMBI nel pannello: il secondo con suffisso disambiguante, mai
    silenziosamente perso come SKIPPED_EXISTS."""
    import ingest.pec.panel as panel
    from datetime import datetime
    from types import SimpleNamespace

    monkeypatch.setattr(panel, "PANEL_ROOT", str(tmp_path))

    contenuti = {"gs://b/uno.pdf": b"pratica uno", "gs://b/due.pdf": b"pratica due"}
    import hashlib as _hl
    cands = [
        SimpleNamespace(
            msgid=f"m{i}", sha256=_hl.sha256(body).hexdigest(),
            nome_file="RicevutaCu.pdf", gcs_uri=uri, size_bytes=len(body),
            entity_id="INTUR", data_evento=datetime(2025, 3, 10 + i),
            primary_category="REGISTRO_IMPRESE",
        )
        for i, (uri, body) in enumerate(contenuti.items())
    ]
    monkeypatch.setattr(panel, "_candidati", lambda client: cands)
    monkeypatch.setattr(panel, "_gia_proiettate", lambda client: set())
    monkeypatch.setattr(
        panel, "_download_gcs",
        lambda gcs_uri, dest: dest.write_bytes(contenuti[gcs_uri]),
    )
    written_rows = []
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, mode="append": written_rows.extend(rows),
    )
    fake_client = SimpleNamespace(query=lambda sql: SimpleNamespace(result=lambda: []))
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    report = panel.sync_panel(dry_run=False, verify=False)

    assert report["copiati"] == 2
    assert report["skippati"] == 0
    cartella = tmp_path / "INTUR" / "PEC" / "Registro Imprese"
    files = sorted(p.name for p in cartella.iterdir())
    assert len(files) == 2, f"attesi 2 file distinti, trovati: {files}"
    assert "2025-03 - RicevutaCu.pdf" in files
    sha8 = cands[1].sha256[:8]
    assert f"2025-03 - RicevutaCu ({sha8}).pdf" in files
    # la riga BQ del secondo deve registrare il path davvero usato
    paths = {r.destination_path for r in written_rows}
    assert f"INTUR/PEC/Registro Imprese/2025-03 - RicevutaCu ({sha8}).pdf" in paths


def _due_candidati_stesso_contenuto():
    from datetime import datetime
    from types import SimpleNamespace
    import hashlib as _hl

    body = b"stessa fattura allegata a inviata e ricevuta di consegna"
    sha = _hl.sha256(body).hexdigest()
    return body, [
        SimpleNamespace(
            msgid=f"m{i}", sha256=sha, nome_file="FT 31.pdf",
            gcs_uri="gs://b/ft31.pdf", size_bytes=len(body),
            entity_id="ORTI", data_evento=datetime(2026, 6, 5 + i),
            primary_category="LEGALE",
        )
        for i in range(2)
    ]


def test_sync_panel_collisione_stesso_contenuto_dedup(tmp_path, monkeypatch):
    """Stesso allegato presente in due messaggi (inviata + ricevuta): un solo
    file nel pannello, il secondo candidato SKIPPED_EXISTS."""
    import ingest.pec.panel as panel
    from types import SimpleNamespace

    monkeypatch.setattr(panel, "PANEL_ROOT", str(tmp_path))
    body, cands = _due_candidati_stesso_contenuto()
    monkeypatch.setattr(panel, "_candidati", lambda client: cands)
    monkeypatch.setattr(panel, "_gia_proiettate", lambda client: set())
    monkeypatch.setattr(
        panel, "_download_gcs", lambda gcs_uri, dest: dest.write_bytes(body)
    )
    written_rows = []
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, mode="append": written_rows.extend(rows),
    )
    fake_client = SimpleNamespace(query=lambda sql: SimpleNamespace(result=lambda: []))
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    report = panel.sync_panel(dry_run=False, verify=False)

    assert report["copiati"] == 1
    assert report["skippati"] == 1
    cartella = tmp_path / "ORTI" / "PEC" / "Legale"
    assert [p.name for p in cartella.iterdir()] == ["2026-06 - FT 31.pdf"]


def test_sync_panel_dry_run_conta_come_il_run_reale(tmp_path, monkeypatch):
    """Il dry-run deve simulare le collisioni coi claim in-run: stessi
    contatori del run reale, così il numero mostrato al gate è quello vero."""
    import ingest.pec.panel as panel
    from types import SimpleNamespace

    monkeypatch.setattr(panel, "PANEL_ROOT", str(tmp_path))
    body, cands = _due_candidati_stesso_contenuto()
    monkeypatch.setattr(panel, "_candidati", lambda client: cands)
    monkeypatch.setattr(panel, "_gia_proiettate", lambda client: set())
    monkeypatch.setattr(
        "core.bq.write.bq_write_validated",
        lambda table, rows, mode="append": None,
    )
    fake_client = SimpleNamespace(query=lambda sql: SimpleNamespace(result=lambda: []))
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    report = panel.sync_panel(dry_run=True, verify=False)

    assert report["copiati"] == 1
    assert report["skippati"] == 1
    assert not any(tmp_path.rglob("*.pdf")), "dry-run non deve scrivere file"
