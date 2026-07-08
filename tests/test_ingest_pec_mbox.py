"""PEC mbox ingestion — schemi, parser, dedup, report."""

from __future__ import annotations

import email.message
from datetime import datetime, timezone

import pytest

from core.schemas import PecAllegatoRow, PecMessageRow, validate_batch


def _msg_row(**over) -> dict:
    base = {
        "msgid": "opec296.20240325@pec.aruba.it",
        "source_folder": "RECEIVED",
        "tipo": "POSTA_CERTIFICATA",
        "ref_msgid": None,
        "data_evento": datetime(2024, 3, 25, 10, 0, tzinfo=timezone.utc),
        "data_certificata": True,
        "mittente": "avvocato@pec.studiolegale.it",
        "destinatari": "in.tur@pec.it",
        "n_destinatari": 1,
        "subject": "Diffida",
        "body_text": "testo",
        "provider": "pec.aruba.it",
        "casella": "in.tur@pec.it",
        "societa_id": "INTUR",
        "n_allegati": 1,
        "ha_postacert": True,
        "parse_warning": None,
        "hash_riga": "abc123",
        "raw_object_id": "raw-001",
        "data_caricamento": datetime(2026, 7, 8, 12, 0),
    }
    base.update(over)
    return base


def test_pec_message_row_valida():
    validate_batch([_msg_row()], PecMessageRow, context="test")


def test_pec_message_row_rifiuta_source_folder_invalido():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch([_msg_row(source_folder="INBOX")], PecMessageRow, context="test")


def test_pec_message_row_rifiuta_msgid_vuoto():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch([_msg_row(msgid="  ")], PecMessageRow, context="test")


def test_pec_allegato_row_valida():
    row = {
        "msgid": "opec296.20240325@pec.aruba.it",
        "nome_file": "BILANCIO 2020.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 12345,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "is_firmato": False,
        "gcs_uri": "gs://hotelops-raw/PEC_MAILBOX_INTUR_APPEND/allegati/e3b0/BILANCIO 2020.pdf",
        "hash_riga": "def456",
        "raw_object_id": "raw-001",
        "data_caricamento": datetime(2026, 7, 8, 12, 0),
    }
    validate_batch([row], PecAllegatoRow, context="test")


def test_registry_pec_mailbox_intur():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    s = reg.resolve("pec_mbox", "INTUR")
    assert s.source_name == "PEC_MAILBOX_INTUR_APPEND"
    assert s.canonical_table == "f_pec_messages"
    assert s.parser_module == "ingest.flussi.ingest_pec_mbox"
    assert s.promotion_policy == "AUTO"
    assert s.loop_targets == ["pec_archive"]


DATICERT_CONSEGNA = b"""<?xml version="1.0" encoding="UTF-8"?>
<postacert tipo="avvenuta-consegna" errore="nessuno">
  <intestazione>
    <mittente>in.tur@pec.it</mittente>
    <destinatari tipo="certificato">controparte@pec.it</destinatari>
    <oggetto>Disdetta contratto</oggetto>
  </intestazione>
  <dati>
    <gestore-emittente>Aruba PEC S.p.A.</gestore-emittente>
    <data zona="+0200"><giorno>25/03/2024</giorno><ora>10:15:32</ora></data>
    <identificativo>opec296.consegna.123@pec.aruba.it</identificativo>
    <msgid>&lt;original.msgid.456@pec.it&gt;</msgid>
    <ricevuta tipo="completa"/>
    <consegna>controparte@pec.it</consegna>
  </dati>
</postacert>"""


def test_parse_daticert_consegna():
    from ingest.flussi.ingest_pec_mbox import parse_daticert

    d = parse_daticert(DATICERT_CONSEGNA)
    assert d["tipo_raw"] == "avvenuta-consegna"
    assert d["msgid"] == "opec296.consegna.123@pec.aruba.it"
    assert d["ref_msgid"] == "original.msgid.456@pec.it"  # senza <>
    assert d["mittente"] == "in.tur@pec.it"
    assert d["destinatari"] == ["controparte@pec.it"]
    assert d["data_evento"].year == 2024 and d["data_evento"].month == 3


def test_parse_daticert_malformato_ritorna_none():
    from ingest.flussi.ingest_pec_mbox import parse_daticert

    assert parse_daticert(b"not xml at all <<<") is None


def test_is_busta():
    import email.message

    from ingest.flussi.ingest_pec_mbox import is_busta

    busta = email.message.EmailMessage()
    busta["From"] = "Per conto di X <posta-certificata@pec.aruba.it>"
    inviata = email.message.EmailMessage()
    inviata["From"] = "in.tur <in.tur@pec.it>"
    assert is_busta(busta) is True
    assert is_busta(inviata) is False


def test_map_tipo():
    from ingest.flussi.ingest_pec_mbox import map_tipo

    assert map_tipo("posta-certificata", "x", True) == "POSTA_CERTIFICATA"
    assert map_tipo("accettazione", "x", True) == "ACCETTAZIONE"
    assert map_tipo("avvenuta-consegna", "x", True) == "CONSEGNA"
    assert map_tipo("errore-consegna", "x", True) == "ANOMALIA"
    # fallback dal subject quando daticert manca
    assert map_tipo(None, "CONSEGNA: Disdetta", True) == "CONSEGNA"
    assert map_tipo(None, "ACCETTAZIONE: Disdetta", True) == "ACCETTAZIONE"
    assert map_tipo(None, "POSTA CERTIFICATA: Diffida", True) == "POSTA_CERTIFICATA"
    assert map_tipo(None, "qualunque", True) == "ALTRO"
    # inviata: sempre MESSAGGIO_INVIATO
    assert map_tipo(None, "qualunque", False) == "MESSAGGIO_INVIATO"


def _busta_con_postacert() -> "email.message.EmailMessage":
    inner = email.message.EmailMessage()
    inner["From"] = "avvocato@pec.studiolegale.it"
    inner["To"] = "in.tur@pec.it"
    inner["Subject"] = "Diffida"
    inner["Message-ID"] = "<original.msgid.456@pec.it>"
    inner.set_content("Testo della diffida.")
    inner.add_attachment(
        b"%PDF-fake", maintype="application", subtype="pdf", filename="Diffida.pdf"
    )
    inner.add_attachment(
        b"firmato",
        maintype="application",
        subtype="pkcs7-mime",
        filename="Delega.pdf.p7m",
    )

    busta = email.message.EmailMessage()
    busta["From"] = "Per conto di: avvocato <posta-certificata@pec.aruba.it>"
    busta["To"] = "in.tur@pec.it"
    busta["Subject"] = "POSTA CERTIFICATA: Diffida"
    busta.set_content("Messaggio di posta certificata (corpo busta).")
    busta.add_attachment(
        DATICERT_CONSEGNA,
        maintype="application",
        subtype="xml",
        filename="daticert.xml",
    )
    busta.add_attachment(
        inner.as_bytes(), maintype="message", subtype="rfc822", filename="postacert.eml"
    )
    return busta


def test_inner_message_spacchetta_postacert():
    from ingest.flussi.ingest_pec_mbox import inner_message

    inner, ha_postacert = inner_message(_busta_con_postacert())
    assert ha_postacert is True
    assert inner["Subject"] == "Diffida"


def test_inner_message_senza_postacert_ritorna_busta():
    import email.message

    from ingest.flussi.ingest_pec_mbox import inner_message

    busta = email.message.EmailMessage()
    busta["From"] = "posta-certificata@pec.aruba.it"
    busta["Subject"] = "ACCETTAZIONE: x"
    busta.set_content("ricevuta")
    inner, ha_postacert = inner_message(busta)
    assert ha_postacert is False
    assert inner is busta


def test_inner_message_rfc822_letterale_payload_lista():
    """Negli export reali il postacert è message/rfc822 letterale (non base64):
    get_payload(decode=True) è None e il payload è una lista di Message."""
    import email

    from ingest.flussi.ingest_pec_mbox import inner_message

    raw = (
        b"From: posta-certificata@pec.aruba.it\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: POSTA CERTIFICATA: Diffida\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BB"\r\n'
        b"\r\n"
        b"--BB\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"corpo busta\r\n"
        b"--BB\r\n"
        b'Content-Type: message/rfc822; name="postacert.eml"\r\n'
        b'Content-Disposition: attachment; filename="postacert.eml"\r\n'
        b"\r\n"
        b"From: avvocato@pec.studiolegale.it\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: Diffida\r\n"
        b"\r\n"
        b"Testo della diffida.\r\n"
        b"--BB--\r\n"
    )
    busta = email.message_from_bytes(raw)
    part = [p for p in busta.walk() if (p.get_filename() or "") == "postacert.eml"][0]
    assert part.get_payload(decode=True) is None  # precondizione: ramo lista
    inner, ha_postacert = inner_message(busta)
    assert ha_postacert is True
    assert inner["Subject"] == "Diffida"


def test_iter_allegati_reali_esclude_artefatti():
    from ingest.flussi.ingest_pec_mbox import inner_message, iter_allegati_reali

    inner, _ = inner_message(_busta_con_postacert())
    allegati = iter_allegati_reali(inner)
    nomi = [a[0] for a in allegati]
    assert nomi == ["Diffida.pdf", "Delega.pdf.p7m"]
    assert allegati[0][1] == b"%PDF-fake"
    assert allegati[0][2] == "application/pdf"


def test_estrai_body_text():
    from ingest.flussi.ingest_pec_mbox import estrai_body_text, inner_message

    inner, _ = inner_message(_busta_con_postacert())
    assert "Testo della diffida" in estrai_body_text(inner)
