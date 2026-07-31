"""PEC multi-casella — EntityId, schema righe, registry, parser generalizzato."""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from core.schemas import PecMessageRow, validate_batch


def _row(**over) -> dict:
    base = {
        "msgid": "m1@pec.aruba.it",
        "source_folder": "RECEIVED",
        "tipo": "POSTA_CERTIFICATA",
        "ref_msgid": None,
        "data_evento": datetime(2026, 7, 1, 10, 0),
        "data_certificata": True,
        "mittente": "x@pec.it",
        "destinatari": "orti@pec.it",
        "n_destinatari": 1,
        "subject": "s",
        "body_text": None,
        "provider": "pec.aruba.it",
        "casella": "orti@pec.it",
        "entity_id": "ORTI",
        "societa_id": "ORTI",
        "n_allegati": 0,
        "ha_postacert": False,
        "parse_warning": None,
        "hash_riga": "h1",
        "raw_object_id": "raw-1",
        "data_caricamento": datetime(2026, 7, 17, 12, 0),
    }
    base.update(over)
    return base


def test_entity_id_literal_completo():
    from core.schemas import EntityId
    from typing import get_args

    assert set(get_args(EntityId)) == {"INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"}


def test_societa_id_non_esteso():
    from core.schemas import SocietaId
    from typing import get_args

    assert set(get_args(SocietaId)) == {"ORTI", "INTUR"}


def test_riga_personale_senza_societa():
    row = _row(
        casella="stefanojunior.dellapietra@mpspec.it",
        entity_id="STEFANO_PERSONALE",
        societa_id=None,
    )
    validate_batch([row], PecMessageRow, context="test")


def test_riga_vigna_con_societa_rifiutata():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch(
            [_row(entity_id="VIGNA", societa_id="VIGNA")], PecMessageRow, context="test"
        )


def test_entity_id_obbligatorio():
    from core.schemas import SchemaViolationError

    row = _row()
    del row["entity_id"]
    with pytest.raises(SchemaViolationError):
        validate_batch([row], PecMessageRow, context="test")


# ── Step 1: Tests registry (falliscono finché non implemento Task 2) ──────────


def test_registry_quattro_sorgenti_pec():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    attese = {
        "PEC_MAILBOX_INTUR_APPEND": ("in.tur@pec.it", "INTUR", "hotelops-raw"),
        "PEC_MAILBOX_ORTI_APPEND": ("orti@pec.it", "ORTI", "orti-raw"),
        "PEC_MAILBOX_VIGNA_APPEND": ("vineyardamalficoast@pec.it", "VIGNA", "vigna-raw"),
        "PEC_MAILBOX_PERSONALE_APPEND": (
            "stefanojunior.dellapietra@mpspec.it",
            "STEFANO_PERSONALE",
            "stefano-raw",
        ),
    }
    for name, (casella, entity, bucket) in attese.items():
        s = reg.get(name)
        assert s is not None, name
        assert s.casella == casella
        assert s.entity_id == entity
        assert s.raw_storage.bucket == bucket
        assert s.parser_module == "ingest.flussi.ingest_pec_mbox"
        assert s.system == "PEC"


def test_registry_personale_accetta_eml():
    from core.lineage.source_resolver import load_registry

    s = load_registry().get("PEC_MAILBOX_PERSONALE_APPEND")
    assert "eml" in s.input_formats


def test_source_pec_senza_casella_rifiutata():
    from core.lineage.schemas import SourceDefinition
    from pydantic import ValidationError

    base = dict(
        source_name="PEC_MAILBOX_TEST_APPEND",
        system="PEC",
        dataset="MAILBOX",
        societa="INTUR",
        lifecycle="APPEND",
        canonical_table="f_pec_messages",
        parser_module="ingest.flussi.ingest_pec_mbox",
        promotion_policy="AUTO",
        detector_category="pec_mbox",
        raw_storage={"backend": "gcs", "bucket": "b", "path_template": "p"},
    )
    with pytest.raises(ValidationError):
        SourceDefinition(**base)  # PEC senza casella/entity_id


# ── Parser generalizzato ─────────────────────────────────────────────────────


def _make_eml(path: Path, from_addr: str, to_addr: str, subject: str,
              attach: tuple[str, bytes] | None = None) -> Path:
    m = EmailMessage()
    m["From"] = from_addr
    m["To"] = to_addr
    m["Subject"] = subject
    m["Message-ID"] = f"<{abs(hash((from_addr, subject)))}@test.pec.it>"
    m["Date"] = "Wed, 15 Jul 2026 16:38:59 +0200"
    m.set_content("corpo del messaggio")
    if attach:
        nome, contenuto = attach
        m.add_attachment(
            contenuto, maintype="application", subtype="pdf", filename=nome
        )
    path.write_bytes(bytes(m))
    return path


def _src_personale():
    from ingest.flussi.ingest_pec_mbox import resolve_pec_source

    return resolve_pec_source("PEC_MAILBOX_PERSONALE_APPEND")


def test_resolve_pec_source_orti():
    from ingest.flussi.ingest_pec_mbox import resolve_pec_source

    src = resolve_pec_source("PEC_MAILBOX_ORTI_APPEND")
    assert src.casella == "orti@pec.it"
    assert src.entity_id == "ORTI"
    assert src.bucket == "orti-raw"


def test_resolve_pec_source_rifiuta_non_pec():
    from ingest.flussi.ingest_pec_mbox import resolve_pec_source

    with pytest.raises((KeyError, ValueError)):
        resolve_pec_source("ESOLVER_MOVIMENTI_ORTI_APPEND")


def test_ingest_eml_personale(tmp_path):
    from ingest.flussi.ingest_pec_mbox import ingest_file

    src = _src_personale()
    eml = _make_eml(
        tmp_path / "msg.eml",
        "stefanojunior.dellapietra@mpspec.it",
        "controparte@pec.it",
        "Test invio",
    )
    report = ingest_file(eml, src, dry_run=True)
    assert report["messaggi_letti"] == 1
    assert report["righe_messaggi"] == 1


def test_entity_dal_registry_mai_dal_contenuto(tmp_path):
    """I-PEC-2: un .eml 'della casella sbagliata' resta attribuito alla
    sorgente dichiarata, con warning — mai riattribuito a un'altra entity."""

    from ingest.flussi.ingest_pec_mbox import extract_message, AllegatiStore

    eml = _make_eml(
        tmp_path / "alien.eml", "orti@pec.it", "x@pec.it", "Da altra casella"
    )
    import email as email_pkg

    msg = email_pkg.message_from_bytes(eml.read_bytes())
    src = _src_personale()
    store = AllegatiStore(bucket_name=src.bucket, prefix=src.source_name, dry_run=True)
    riga, _ = extract_message(msg, src, "raw-x", store, datetime(2026, 7, 17))
    assert riga["entity_id"] == "STEFANO_PERSONALE"
    assert riga["casella"] == "stefanojunior.dellapietra@mpspec.it"
    assert "from!=casella" in (riga["parse_warning"] or "")


def test_formato_non_ammesso_rifiutato(tmp_path):
    from ingest.flussi.ingest_pec_mbox import ingest_file, resolve_pec_source

    src = resolve_pec_source("PEC_MAILBOX_ORTI_APPEND")  # solo mbox
    eml = _make_eml(tmp_path / "x.eml", "orti@pec.it", "y@pec.it", "s")
    with pytest.raises(ValueError, match="formato"):
        ingest_file(eml, src, dry_run=True)


def test_allegati_store_prefix_per_source():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    store = AllegatiStore(bucket_name="orti-raw", prefix="PEC_MAILBOX_ORTI_APPEND", dry_run=True)
    sha, uri = store.store("doc.pdf", b"contenuto")
    assert uri.startswith("gs://orti-raw/PEC_MAILBOX_ORTI_APPEND/allegati/")


def test_promotion_passa_source_alle_pec(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    from ingest.promotion import _invoke_parser

    catturato = {}

    def fake_run(cmd, **kw):
        catturato["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    f = tmp_path / "x.mbox"
    f.write_bytes(b"")

    sd_pec = SimpleNamespace(
        system="PEC", societa="ORTI", source_name="PEC_MAILBOX_ORTI_APPEND",
        parser_module="ingest.flussi.ingest_pec_mbox",
    )
    _invoke_parser("ingest.flussi.ingest_pec_mbox", f"file://{f}", sd_pec,
                   raw_object_id="raw-1")
    assert "--source" in catturato["cmd"]
    assert "PEC_MAILBOX_ORTI_APPEND" in catturato["cmd"]
    assert "--societa" not in catturato["cmd"]

    sd_altro = SimpleNamespace(
        system="ESOLVER", societa="ORTI", source_name="ESOLVER_X_ORTI_APPEND",
        parser_module="ingest.flussi.qualcosa",
    )
    _invoke_parser("ingest.flussi.qualcosa", f"file://{f}", sd_altro)
    assert "--societa" in catturato["cmd"]
    assert "--source" not in catturato["cmd"]


def test_bonifica_richiede_tutte_le_verifiche():
    from scripts.bonifica_pec_manuali import puo_rimuovere

    ok = dict(promoted=True, canonico_esiste=True, hash_combacia=True,
              lineage_persistita=True)
    assert puo_rimuovere(**ok)
    for k in ok:
        kw = {**ok, k: False}
        assert not puo_rimuovere(**kw), f"doveva bloccare con {k}=False"
