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


def _busta_con_postacert() -> "email.message.Message":
    """RFC822 busta con postacert preservata attraverso mbox serialization."""
    import email as email_pkg

    raw = (
        b"From: Per conto di: avvocato <posta-certificata@pec.aruba.it>\r\n"
        b"To: in.tur@pec.it\r\n"
        b"Subject: POSTA CERTIFICATA: Diffida\r\n"
        b"Message-ID: <opec296.consegna.123@pec.aruba.it>\r\n"
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
    s = AllegatiStore(dry_run=False, client=client)
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

    s = AllegatiStore(dry_run=True, client=None)  # client None: se lo tocca, esplode
    sha, uri = s.store("x.pdf", b"abc")
    assert uri.startswith("gs://")


def _extract(msg):
    from datetime import datetime

    from ingest.flussi.ingest_pec_mbox import AllegatiStore, extract_message

    return extract_message(
        msg,
        raw_object_id="raw-001",
        store=AllegatiStore(dry_run=True),
        now=datetime(2026, 7, 8, 12, 0),
    )


def test_extract_busta_completa():
    riga, allegati = _extract(_busta_con_postacert())
    assert riga["source_folder"] == "RECEIVED"
    assert riga["tipo"] == "CONSEGNA"  # dal daticert (autoritativo), non dal subject
    assert riga["msgid"] == "opec296.consegna.123@pec.aruba.it"
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


def test_extract_idempotente_hash_stabile():
    r1, _ = _extract(_busta_con_postacert())
    r2, _ = _extract(_busta_con_postacert())
    assert r1["hash_riga"] == r2["hash_riga"]


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

    report = mod.ingest_file(mbox_path, raw_object_id="raw-001", dry_run=True)
    assert report["messaggi_letti"] == 2
    assert report["righe_messaggi"] == 1  # dedup in-file su msgid
    assert report["dedup_in_file"] == 1
    assert report["righe_allegati"] == 2
    assert report["con_warning"] == 0
    assert report["per_tipo"] == {"CONSEGNA": 1}
