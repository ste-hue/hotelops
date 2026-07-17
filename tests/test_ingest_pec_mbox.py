"""PEC mbox ingestion — schemi, parser, dedup, report."""

from __future__ import annotations

import email.message
from datetime import datetime, timezone

import pytest

from core.schemas import PecAllegatoRow, PecMessageRow, validate_batch
from ingest.flussi.ingest_pec_mbox import PecSource

SRC_INTUR = PecSource(
    source_name="PEC_MAILBOX_INTUR_APPEND",
    casella="in.tur@pec.it",
    entity_id="INTUR",
    bucket="hotelops-raw",
    input_formats=("mbox",),
)


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
        "entity_id": "INTUR",
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


def _busta_con_postacert() -> "email.message.Message":
    """RFC822 busta con postacert preservata attraverso mbox serialization."""
    import email as email_pkg

    raw = (
        b"From: Per conto di: avvocato <posta-certificata@pec.aruba.it>\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: POSTA CERTIFICATA: Diffida\r\n"
        b"Message-ID: <busta.consegna.001@pec.aruba.it>\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BB"\r\n'
        b"\r\n"
        b"--BB\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Messaggio di posta certificata (corpo busta).\r\n"
        b"--BB\r\n"
        b'Content-Type: application/xml; name="daticert.xml"\r\n'
        b'Content-Disposition: attachment; filename="daticert.xml"\r\n'
        b"\r\n"
    )
    raw += DATICERT_CONSEGNA
    raw += (
        b"\r\n--BB\r\n"
        b'Content-Type: message/rfc822; name="postacert.eml"\r\n'
        b'Content-Disposition: attachment; filename="postacert.eml"\r\n'
        b"\r\n"
        b"From: avvocato@pec.studiolegale.it\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: Diffida\r\n"
        b"Message-ID: <original.msgid.456@pec.it>\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="CC"\r\n'
        b"\r\n"
        b"--CC\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Testo della diffida.\r\n"
        b"--CC\r\n"
        b"Content-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="Diffida.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"JVBERi1mYWtl\r\n"
        b"--CC\r\n"
        b"Content-Type: application/pkcs7-mime\r\n"
        b'Content-Disposition: attachment; filename="Delega.pdf.p7m"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"ZmlybWF0bw==\r\n"
        b"--CC--\r\n"
        b"--BB--\r\n"
    )
    return email_pkg.message_from_bytes(raw)


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


def test_inner_message_rfc822_base64_payload_bytes():
    """Alcuni provider incapsulano postacert.eml come application/octet-stream
    base64 (non message/rfc822 letterale): get_payload(decode=True) ritorna
    bytes (non None) → ramo else di inner_message."""
    import base64
    import email as email_pkg

    from ingest.flussi.ingest_pec_mbox import inner_message

    inner_raw = (
        b"From: avvocato@pec.studiolegale.it\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: Diffida base64\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Testo della diffida.\r\n"
    )
    encoded = base64.b64encode(inner_raw)
    encoded_lines = b"\r\n".join(
        encoded[i : i + 76] for i in range(0, len(encoded), 76)
    )

    raw = (
        b"From: posta-certificata@pec.aruba.it\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: POSTA CERTIFICATA: Diffida base64\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BB"\r\n'
        b"\r\n"
        b"--BB\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"corpo busta\r\n"
        b"--BB\r\n"
        b'Content-Type: application/octet-stream; name="postacert.eml"\r\n'
        b'Content-Disposition: attachment; filename="postacert.eml"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n" + encoded_lines + b"\r\n"
        b"--BB--\r\n"
    )
    busta = email_pkg.message_from_bytes(raw)
    part = [p for p in busta.walk() if (p.get_filename() or "") == "postacert.eml"][0]
    assert part.get_payload(decode=True) is not None  # precondizione: ramo bytes

    inner, ha_postacert = inner_message(busta)
    assert ha_postacert is True
    assert inner["Subject"] == "Diffida base64"


def test_iter_allegati_reali_esclude_artefatti():
    from ingest.flussi.ingest_pec_mbox import inner_message, iter_allegati_reali

    inner, _ = inner_message(_busta_con_postacert())
    allegati = iter_allegati_reali(inner)
    nomi = [a[0] for a in allegati]
    assert nomi == ["Diffida.pdf", "Delega.pdf.p7m"]
    assert allegati[0][1] == b"%PDF-fake"
    assert allegati[0][2] == "application/pdf"


def test_iter_allegati_include_inline_con_filename():
    """Una parte inline CON filename è un documento, non va scartata."""
    import email as email_pkg

    from ingest.flussi.ingest_pec_mbox import iter_allegati_reali

    raw = (
        b"From: in.tur@pec.it\r\n"
        b"Subject: x\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="EE"\r\n'
        b"\r\n"
        b"--EE\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"corpo\r\n"
        b"--EE\r\n"
        b"Content-Type: application/pdf\r\n"
        b'Content-Disposition: inline; filename="Planimetria.pdf"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"JVBERi1mYWtl\r\n"
        b"--EE--\r\n"
    )
    allegati = iter_allegati_reali(email_pkg.message_from_bytes(raw))
    assert [a[0] for a in allegati] == ["Planimetria.pdf"]
    assert allegati[0][1] == b"%PDF-fake"


def _inviata_con_eml_annidato() -> "email.message.Message":
    """Inviata con allegato message/rfc822 (non postacert): payload non
    decodificabile via get_payload(decode=True)."""
    import email as email_pkg

    raw = (
        b"From: in.tur@pec.it\r\n"
        b"To: controparte@pec.it\r\n"
        b"Subject: inoltro\r\n"
        b"Message-ID: <sent.fwd.001@pec.it>\r\n"
        b"Date: Tue, 25 Jun 2024 10:00:00 +0200\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="FF"\r\n'
        b"\r\n"
        b"--FF\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"vedi allegato\r\n"
        b"--FF\r\n"
        b'Content-Type: message/rfc822; name="vecchia_mail.eml"\r\n'
        b'Content-Disposition: attachment; filename="vecchia_mail.eml"\r\n'
        b"\r\n"
        b"From: terzo@pec.it\r\n"
        b"Subject: vecchia\r\n"
        b"\r\n"
        b"testo vecchio\r\n"
        b"--FF--\r\n"
    )
    return email_pkg.message_from_bytes(raw)


def test_extract_allegato_non_estraibile_riga_tracciata():
    """Payload non decodificabile → riga f_pec_allegati senza gcs_uri, sha256
    placeholder deterministico, warning sul messaggio (no-silent-skips)."""
    import hashlib

    riga, allegati = _extract(_inviata_con_eml_annidato())
    assert riga["n_allegati"] == 1
    assert "allegato non estraibile: vecchia_mail.eml" in riga["parse_warning"]
    a = allegati[0]
    assert a["nome_file"] == "vecchia_mail.eml"
    assert a["gcs_uri"] is None
    assert a["size_bytes"] == 0
    expected_sha = hashlib.sha256(
        f"{riga['msgid']}|vecchia_mail.eml".encode()
    ).hexdigest()
    assert a["sha256"] == expected_sha  # deterministico tra run
    validate_batch(allegati, PecAllegatoRow, context="test")

    # idempotenza: seconda estrazione → stesso sha256 e hash_riga
    _, allegati2 = _extract(_inviata_con_eml_annidato())
    assert allegati2[0]["sha256"] == a["sha256"]
    assert allegati2[0]["hash_riga"] == a["hash_riga"]


def test_estrai_body_text():
    from ingest.flussi.ingest_pec_mbox import estrai_body_text, inner_message

    inner, _ = inner_message(_busta_con_postacert())
    assert "Testo della diffida" in estrai_body_text(inner)


# GCS mock classes for AllegatiStore tests
class _FakeBlob:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def exists(self):
        return self.path in self.store

    def upload_from_string(self, data, content_type=None):
        self.store[self.path] = data


class _FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, path):
        return _FakeBlob(self.store, path)


class _FakeGcsClient:
    def __init__(self):
        self.store = {}

    def bucket(self, name):
        return _FakeBucket(self.store)


def test_allegati_store_content_addressed():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    client = _FakeGcsClient()
    s = AllegatiStore(
        bucket_name="hotelops-raw", prefix="PEC_MAILBOX_INTUR_APPEND", dry_run=False, client=client
    )
    sha1, uri1 = s.store("Diffida.pdf", b"%PDF-fake")
    sha2, uri2 = s.store("Copia di Diffida.pdf", b"%PDF-fake")  # stesso contenuto
    assert sha1 == sha2
    assert len(client.store) == 2  # due path (nome diverso) ...
    assert uri1.startswith("gs://hotelops-raw/PEC_MAILBOX_INTUR_APPEND/allegati/")
    assert sha1[:8] in uri1
    # ... ma ricaricare lo stesso (nome, contenuto) non riscrive
    before = dict(client.store)
    s.store("Diffida.pdf", b"%PDF-fake")
    assert client.store == before


def test_allegati_store_dry_run_non_tocca_rete():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    s = AllegatiStore(
        bucket_name="hotelops-raw", prefix="PEC_MAILBOX_INTUR_APPEND", dry_run=True, client=None
    )  # client None: se lo tocca, esplode
    sha, uri = s.store("x.pdf", b"abc")
    assert uri.startswith("gs://")


def _extract(msg):
    from datetime import datetime

    from ingest.flussi.ingest_pec_mbox import AllegatiStore, extract_message

    return extract_message(
        msg,
        SRC_INTUR,
        raw_object_id="raw-001",
        store=AllegatiStore(bucket_name="hotelops-raw", prefix="PEC_MAILBOX_INTUR_APPEND", dry_run=True),
        now=datetime(2026, 7, 8, 12, 0),
    )


def test_extract_busta_completa():
    riga, allegati = _extract(_busta_con_postacert())
    assert riga["source_folder"] == "RECEIVED"
    assert riga["tipo"] == "CONSEGNA"  # dal daticert (autoritativo), non dal subject
    assert riga["msgid"] == "busta.consegna.001@pec.aruba.it"  # envelope Message-ID
    assert riga["ref_msgid"] == "original.msgid.456@pec.it"
    assert riga["mittente"] == "in.tur@pec.it"  # dal daticert, non dalla busta
    assert riga["data_certificata"] is True
    assert riga["provider"] == "pec.aruba.it"
    assert riga["ha_postacert"] is True
    assert riga["subject"] == "Diffida"  # del messaggio reale
    assert riga["n_allegati"] == 2
    assert riga["parse_warning"] is None
    assert len(allegati) == 2
    assert allegati[1]["is_firmato"] is True  # .p7m
    assert allegati[0]["gcs_uri"].startswith("gs://")


def test_extract_inviata():
    import email.message

    inviata = email.message.EmailMessage()
    inviata["From"] = "in.tur@pec.it"
    inviata["To"] = "a@pec.it, b@pec.it"
    inviata["Subject"] = "Disdetta"
    inviata["Message-ID"] = "<sent.789@pec.it>"
    inviata["Date"] = "Mon, 25 Mar 2024 10:00:00 +0100"
    inviata.set_content("testo disdetta")

    riga, allegati = _extract(inviata)
    assert riga["source_folder"] == "SENT"
    assert riga["tipo"] == "MESSAGGIO_INVIATO"
    assert riga["msgid"] == "sent.789@pec.it"
    assert riga["data_certificata"] is False  # Date header, non daticert
    assert riga["n_destinatari"] == 2
    assert riga["provider"] is None
    assert allegati == []


def test_extract_data_utc_convertita_a_wall_time_roma():
    """Date header in UTC → DATETIME naive in ora di Roma (pinned, non fuso
    della macchina): giugno = CEST, +2h."""
    import email.message
    from datetime import datetime

    inviata = email.message.EmailMessage()
    inviata["From"] = "in.tur@pec.it"
    inviata["To"] = "a@pec.it"
    inviata["Subject"] = "x"
    inviata["Message-ID"] = "<sent.utc.001@pec.it>"
    inviata["Date"] = "Tue, 25 Jun 2024 10:00:00 +0000"
    inviata.set_content("testo")

    riga, _ = _extract(inviata)
    assert riga["data_evento"] == datetime(2024, 6, 25, 12, 0)
    assert riga["data_evento"].tzinfo is None


def test_extract_busta_senza_daticert_ha_warning_e_msgid_sintetico():
    import email.message

    busta = email.message.EmailMessage()
    busta["From"] = "posta-certificata@pec.aruba.it"
    busta["Subject"] = "ACCETTAZIONE: Disdetta"
    busta["Date"] = "Mon, 25 Mar 2024 10:00:00 +0100"
    busta.set_content("ricevuta di accettazione")

    riga, _ = _extract(busta)
    assert riga["tipo"] == "ACCETTAZIONE"  # fallback dal subject
    assert riga["parse_warning"] is not None
    assert riga["msgid"]  # sintetico ma presente (sha256 del raw)
    assert riga["data_certificata"] is False


def _busta_ricevuta_con_daticert(
    daticert_bytes: bytes, message_id: str, subject: str, to: str = "in.tur@pec.it"
):
    """Busta minima con daticert.xml, senza postacert.eml — per test sulla
    priorità del msgid (envelope Message-ID vs daticert identificativo)."""
    import email as email_pkg

    raw = (
        b"From: Per conto di: avvocato <posta-certificata@pec.aruba.it>\r\n"
        b"To: " + to.encode() + b"\r\n"
        b"Subject: " + subject.encode() + b"\r\n"
    )
    if message_id:
        raw += b"Message-ID: <" + message_id.encode() + b">\r\n"
    raw += (
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BB"\r\n'
        b"\r\n"
        b"--BB\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Ricevuta.\r\n"
        b"--BB\r\n"
        b'Content-Type: application/xml; name="daticert.xml"\r\n'
        b'Content-Disposition: attachment; filename="daticert.xml"\r\n'
        b"\r\n"
    )
    raw += daticert_bytes
    raw += b"\r\n--BB--\r\n"
    return email_pkg.message_from_bytes(raw)


def test_extract_busta_senza_message_id_usa_identificativo_tipo():
    """Senza envelope Message-ID, il fallback è l'identificativo daticert
    COMPOSTO col tipo (l'identificativo da solo è l'id della catena, non
    dell'evento)."""
    busta = _busta_ricevuta_con_daticert(
        DATICERT_CONSEGNA, message_id=None, subject="AVVENUTA CONSEGNA: Diffida"
    )
    riga, _ = _extract(busta)
    assert riga["msgid"] == "opec296.consegna.123@pec.aruba.it#CONSEGNA"


def test_extract_catena_ricevute_eventi_distinti():
    """Il daticert `identificativo` è lo stesso per l'intera catena di ricevute
    (ACCETTAZIONE + CONSEGNA); l'envelope Message-ID (per-evento) deve produrre
    msgid e hash_riga distinti — altrimenti 2 fatti legali collassano in 1."""
    daticert_accettazione = DATICERT_CONSEGNA.replace(
        b'tipo="avvenuta-consegna"', b'tipo="accettazione"'
    )

    riga_consegna, _ = _extract(
        _busta_ricevuta_con_daticert(
            DATICERT_CONSEGNA,
            message_id="busta.consegna.001@pec.aruba.it",
            subject="AVVENUTA CONSEGNA: Diffida",
        )
    )
    riga_accettazione, _ = _extract(
        _busta_ricevuta_con_daticert(
            daticert_accettazione,
            message_id="busta.accettazione.002@pec.aruba.it",
            subject="ACCETTAZIONE: Diffida",
        )
    )

    assert riga_consegna["tipo"] == "CONSEGNA"
    assert riga_accettazione["tipo"] == "ACCETTAZIONE"
    assert riga_consegna["msgid"] != riga_accettazione["msgid"]
    assert riga_consegna["hash_riga"] != riga_accettazione["hash_riga"]


def test_extract_non_busta_from_estraneo_diventa_altro():
    """Un raw (non-busta) è MESSAGGIO_INVIATO solo se From = casella;
    altrimenti tipo ALTRO + warning (identità dal contenuto, non silenzio)."""
    import email.message

    estranea = email.message.EmailMessage()
    estranea["From"] = "Qualcuno <estraneo@pec.altro.it>"
    estranea["To"] = "in.tur@pec.it"
    estranea["Subject"] = "x"
    estranea["Message-ID"] = "<estraneo.001@pec.altro.it>"
    estranea["Date"] = "Mon, 25 Mar 2024 10:00:00 +0100"
    estranea.set_content("testo")

    riga, _ = _extract(estranea)
    assert riga["tipo"] == "ALTRO"
    assert "from!=casella" in riga["parse_warning"]


def test_extract_busta_posta_certificata_casella_assente_warning():
    """POSTA_CERTIFICATA in cui NÉ i destinatari daticert NÉ l'envelope To
    contengono la casella → warning (warning, non abort)."""
    daticert = DATICERT_CONSEGNA.replace(
        b'tipo="avvenuta-consegna"', b'tipo="posta-certificata"'
    )  # destinatari daticert = controparte@pec.it (non la casella)
    busta = _busta_ricevuta_con_daticert(
        daticert,
        message_id="busta.pc.003@pec.aruba.it",
        subject="POSTA CERTIFICATA: x",
        to="altra.casella@pec.it",
    )
    riga, _ = _extract(busta)
    assert riga["tipo"] == "POSTA_CERTIFICATA"
    assert "casella non tra i destinatari" in riga["parse_warning"]

    # ... ma se l'envelope To contiene la casella, nessun warning
    busta_ok = _busta_ricevuta_con_daticert(
        daticert,
        message_id="busta.pc.004@pec.aruba.it",
        subject="POSTA CERTIFICATA: x",
    )
    riga_ok, _ = _extract(busta_ok)
    assert riga_ok["parse_warning"] is None


def test_extract_ricevute_senza_casella_nei_destinatari_nessun_warning():
    """ACCETTAZIONE/CONSEGNA: i destinatari daticert sono quelli del messaggio
    ORIGINALE (la controparte) — è normale, mai warning."""
    busta = _busta_ricevuta_con_daticert(
        DATICERT_CONSEGNA,
        message_id="busta.consegna.005@pec.aruba.it",
        subject="AVVENUTA CONSEGNA: Diffida",
        to="altra.casella@pec.it",
    )
    riga, _ = _extract(busta)
    assert riga["tipo"] == "CONSEGNA"
    assert riga["parse_warning"] is None


def test_extract_idempotente_hash_stabile():
    r1, _ = _extract(_busta_con_postacert())
    r2, _ = _extract(_busta_con_postacert())
    assert r1["hash_riga"] == r2["hash_riga"]


def test_estrai_body_text_charset_bogus_fallback_latin1():
    import email as email_pkg

    from ingest.flussi.ingest_pec_mbox import estrai_body_text

    raw = (
        b"From: x@y.it\r\n"
        b'Content-Type: text/plain; charset="bogus-charset-xyz"\r\n'
        b"\r\n"
        b"testo caff\xe8\r\n"
    )
    msg = email_pkg.message_from_bytes(raw)
    assert estrai_body_text(msg) == "testo caffè"  # latin-1 fallback


def test_riga_fallback_deterministica():
    from datetime import datetime

    from ingest.flussi.ingest_pec_mbox import _riga_fallback

    now = datetime(2026, 7, 8, 12, 0)
    riga = _riga_fallback(_busta_con_postacert(), SRC_INTUR, "raw-001", now, ValueError("boom"))
    assert riga["msgid"] == "busta.consegna.001@pec.aruba.it"  # header preservato
    assert riga["tipo"] == "ALTRO"
    assert riga["source_folder"] == "RECEIVED"
    assert riga["parse_warning"].startswith("extract_fail: ValueError: boom")
    assert riga["raw_object_id"] == "raw-001"
    validate_batch([riga], PecMessageRow, context="test")


def test_ingest_file_extract_fail_non_abortisce(tmp_path, monkeypatch):
    """extract_message che esplode su un messaggio → riga fallback + counter,
    mai abort dell'intero file."""
    import mailbox

    from ingest.flussi import ingest_pec_mbox as mod

    mbox_path = tmp_path / "t.mbox"
    mb = mailbox.mbox(str(mbox_path))
    mb.add(_busta_con_postacert())
    mb.flush()

    def boom(msg, src, raw_object_id, store, now):
        raise RuntimeError("parser rotto")

    monkeypatch.setattr(mod, "extract_message", boom)
    report = mod.ingest_file(mbox_path, SRC_INTUR, raw_object_id="raw-001", dry_run=True)
    assert report["estrazioni_fallite"] == 1
    assert report["righe_messaggi"] == 1  # la riga fallback c'è
    assert report["con_warning"] == 1
    assert report["per_tipo"] == {"ALTRO": 1}


def test_coverage_gaps():
    from datetime import date

    from ingest.flussi.ingest_pec_mbox import coverage_gaps

    dates = [date(2024, 1, 1), date(2024, 1, 5), date(2024, 2, 20), date(2024, 2, 25)]
    gaps = coverage_gaps(dates, min_gap_days=14)
    assert gaps == [(date(2024, 1, 5), date(2024, 2, 20), 46)]
    assert coverage_gaps([], min_gap_days=14) == []


def test_ingest_file_dry_run_su_mbox_sintetico(tmp_path, monkeypatch):
    import mailbox

    from ingest.flussi import ingest_pec_mbox as mod

    mbox_path = tmp_path / "test.mbox"
    mb = mailbox.mbox(str(mbox_path))
    mb.add(_busta_con_postacert())
    mb.add(_busta_con_postacert())  # duplicato esatto: stesso msgid
    mb.flush()

    report = mod.ingest_file(mbox_path, SRC_INTUR, raw_object_id="raw-001", dry_run=True)
    assert report["messaggi_letti"] == 2
    assert report["righe_messaggi"] == 1  # dedup in-file su msgid
    assert report["dedup_in_file"] == 1
    assert report["righe_allegati"] == 2
    assert report["con_warning"] == 0
    assert report["per_tipo"] == {"CONSEGNA": 1}


def test_decode_header():
    from ingest.flussi.ingest_pec_mbox import _decode_header

    assert _decode_header(None) == ""
    assert _decode_header("normale.pdf") == "normale.pdf"
    assert (
        _decode_header("=?utf-8?Q?Richiesta=5Fautorizzazione=2Epdf?=")
        == "Richiesta_autorizzazione.pdf"
    )
    # charset sconosciuto → fallback latin-1, mai LookupError
    assert _decode_header("=?bogus-xyz?Q?caff=E8?=") == "caffè"
    # control char del folding collassati in uno spazio
    assert _decode_header("riga\r\n\tpiegata") == "riga piegata"


def _inviata_rfc2047() -> "email.message.Message":
    """Messaggio inviato con subject folded RFC2047 + filename RFC2047."""
    import email as email_pkg

    raw = (
        b"From: in.tur@pec.it\r\n"
        b"To: controparte@pec.it\r\n"
        b"Subject: =?utf-8?Q?Richiesta_autorizzazione?=\r\n"
        b" =?utf-8?Q?_scarico_a_mare?=\r\n"
        b"Message-ID: <sent.enc.001@pec.it>\r\n"
        b"Date: Tue, 25 Jun 2024 10:00:00 +0200\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="DD"\r\n'
        b"\r\n"
        b"--DD\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"In allegato la richiesta.\r\n"
        b"--DD\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment;"
        b' filename="=?utf-8?Q?Richiesta=5Fautorizzazione=2Epdf?="\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"JVBERi1mYWtl\r\n"
        b"--DD--\r\n"
    )
    return email_pkg.message_from_bytes(raw)


def test_extract_decodifica_rfc2047_subject_e_filename():
    riga, allegati = _extract(_inviata_rfc2047())
    assert riga["subject"] == "Richiesta autorizzazione scarico a mare"
    assert len(allegati) == 1
    assert allegati[0]["nome_file"] == "Richiesta_autorizzazione.pdf"
    # il nome decodificato fluisce anche nel path GCS
    assert allegati[0]["gcs_uri"].endswith("/Richiesta_autorizzazione.pdf")


def test_ingest_file_dedup_allegati_indipendente_dai_messaggi(tmp_path, monkeypatch):
    """Messaggi tutti già in BQ ma allegati assenti: le righe allegato vengono
    scritte comunque (backfill) — il dedup allegati è sul loro hash_riga,
    non sulla novità del msgid."""
    import mailbox

    from core.bq import dedup as dedup_mod
    from core.bq import write as write_mod
    from ingest.flussi import ingest_pec_mbox as mod

    mbox_path = tmp_path / "t.mbox"
    mb = mailbox.mbox(str(mbox_path))
    mb.add(_busta_con_postacert())
    mb.flush()

    def fake_filter(table, rows, hash_column):
        # tutti i messaggi sono dedup; tutti gli allegati sono nuovi
        return [] if "f_pec_messages" in table else list(rows)

    written: dict[str, list] = {}

    def fake_write(table, rows, mode=None):
        written[table] = rows

    monkeypatch.setattr(dedup_mod, "filter_new_rows_by_hash", fake_filter)
    monkeypatch.setattr(write_mod, "bq_write_validated", fake_write)
    monkeypatch.setattr(mod.AllegatiStore, "_get_client", lambda self: _FakeGcsClient())

    report = mod.ingest_file(mbox_path, SRC_INTUR, raw_object_id="raw-001", dry_run=False)
    assert report["righe_messaggi"] == 0
    assert report["dedup_bq"] == 1
    assert report["righe_allegati"] == 2  # scritte nonostante il msg sia dedup
    assert report["dedup_bq_allegati"] == 0
    assert mod.F_PEC_MESSAGES not in written  # nessun messaggio nuovo
    assert len(written[mod.F_PEC_ALLEGATI]) == 2


def test_main_accetta_source_valido(tmp_path, monkeypatch, capsys):
    """--source è sempre obbligatorio e risolve casella/entity dal registry
    (I-PEC-2): un source valido non solleva, uno che non è una sorgente PEC
    (o non nel registry) sì."""
    import mailbox
    import sys

    from ingest.flussi import ingest_pec_mbox as mod

    mbox_path = tmp_path / "t.mbox"
    mb = mailbox.mbox(str(mbox_path))
    mb.add(_busta_con_postacert())
    mb.flush()

    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--file", str(mbox_path), "--source", "PEC_MAILBOX_INTUR_APPEND", "--dry-run"],
    )
    mod.main()  # non deve sollevare

    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--file", str(mbox_path), "--source", "ESOLVER_MOVIMENTI_ORTI_APPEND", "--dry-run"],
    )
    with pytest.raises(ValueError):
        mod.main()

    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--file", str(mbox_path), "--dry-run"],  # --source mancante
    )
    with pytest.raises(SystemExit):
        mod.main()


def test_safe_object_name():
    from ingest.flussi.ingest_pec_mbox import _safe_object_name

    assert _safe_object_name("Documento\r\n finale.pdf") == "Documento__ finale.pdf"
    assert _safe_object_name("ok.pdf") == "ok.pdf"
    lungo = "a" * 300 + ".pdf"
    out = _safe_object_name(lungo)
    assert len(out) <= 180 and out.endswith(".pdf")


def test_allegati_store_sanitizza_object_name():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    client = _FakeGcsClient()
    s = AllegatiStore(
        bucket_name="hotelops-raw", prefix="PEC_MAILBOX_INTUR_APPEND", dry_run=False, client=client
    )
    _, uri = s.store("Documento\r\n finale.pdf", b"contenuto")
    assert "\r" not in uri and "\n" not in uri
    assert all("\r" not in k and "\n" not in k for k in client.store)
