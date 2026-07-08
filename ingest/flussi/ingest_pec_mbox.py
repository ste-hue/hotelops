#!/usr/bin/env python3
"""Ingest export mbox PEC → f_pec_messages + f_pec_allegati.

Due forme, distinte dal CONTENUTO (mai dal filename):
  - busta di trasporto (From=posta-certificata@...): daticert.xml è la verità
    certificata (msgid, mittente reale, timestamp opponibile, ref al messaggio
    originale per le ricevute); postacert.eml è il messaggio reale.
  - messaggio inviato (From=casella): raw, niente daticert; il timestamp
    certificato arriva dal link con la ricevuta di ACCETTAZIONE (ref_msgid).

Parser_module della source PEC_MAILBOX_INTUR_APPEND, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_pec_mbox --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_pec_mbox --file <mbox> --raw-object-id <id>
    python -m ingest.flussi.ingest_pec_mbox --file <mbox> --dry-run
"""

from __future__ import annotations

import email.message
import email.utils
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

log = logging.getLogger("ingest.pec_mbox")

CASELLA = "in.tur@pec.it"
SOCIETA = "INTUR"

# Nomi degli artefatti di busta: non sono allegati reali.
ARTEFATTI_BUSTA = {"daticert.xml", "postacert.eml", "smime.p7s"}

TIPO_MAP = {
    "posta-certificata": "POSTA_CERTIFICATA",
    "accettazione": "ACCETTAZIONE",
    "avvenuta-consegna": "CONSEGNA",
    "presa-in-carico": "ALTRO",
    "non-accettazione": "ANOMALIA",
    "errore-consegna": "ANOMALIA",
    "preavviso-errore-consegna": "ANOMALIA",
    "rilevazione-virus": "ANOMALIA",
}

SUBJECT_PREFIX_MAP = [
    ("POSTA CERTIFICATA", "POSTA_CERTIFICATA"),
    ("ACCETTAZIONE", "ACCETTAZIONE"),
    ("AVVENUTA CONSEGNA", "CONSEGNA"),
    ("CONSEGNA", "CONSEGNA"),
    ("ANOMALIA", "ANOMALIA"),
    ("MANCATA CONSEGNA", "ANOMALIA"),
]


def is_busta(msg: email.message.Message) -> bool:
    """Busta di trasporto PEC ⇔ From = posta-certificata@<provider>."""
    fr = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    return fr.startswith("posta-certificata@")


def parse_daticert(xml_bytes: bytes) -> dict | None:
    """daticert.xml → dict con la verità certificata. None se malformato."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    def _text(path: str) -> str | None:
        el = root.find(path)
        return el.text.strip() if el is not None and el.text else None

    giorno, ora = _text(".//data/giorno"), _text(".//data/ora")
    data_evento = None
    if giorno and ora:
        try:
            data_evento = datetime.strptime(f"{giorno} {ora}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass

    ref = _text(".//riferimento-messaggio") or _text(".//msgid")
    return {
        "tipo_raw": root.get("tipo"),
        "msgid": _text(".//identificativo"),
        "ref_msgid": ref.strip("<>") if ref else None,
        "mittente": _text(".//intestazione/mittente"),
        "destinatari": [
            el.text.strip()
            for el in root.findall(".//intestazione/destinatari")
            if el.text
        ],
        "data_evento": data_evento,
    }


def map_tipo(tipo_raw: str | None, subject: str, busta: bool) -> str:
    """Tipo canonico: daticert autoritativo, subject come fallback, ALTRO onesto."""
    if not busta:
        return "MESSAGGIO_INVIATO"
    if tipo_raw and tipo_raw in TIPO_MAP:
        return TIPO_MAP[tipo_raw]
    subj = (subject or "").upper()
    for prefix, tipo in SUBJECT_PREFIX_MAP:
        if subj.startswith(prefix):
            return tipo
    return "ALTRO"


def inner_message(
    msg: email.message.Message,
) -> tuple[email.message.Message, bool]:
    """Il messaggio reale: postacert.eml se presente, altrimenti la busta stessa.

    Le ricevute di accettazione spesso non hanno postacert: è normale (il
    contenuto informativo è nel daticert), non un errore.
    """
    import email as email_pkg

    for part in msg.walk():
        if (part.get_filename() or "").lower() == "postacert.eml":
            payload = part.get_payload(decode=True)
            if payload is None:  # message/rfc822: payload è già un Message
                sub = part.get_payload()
                if isinstance(sub, list) and sub:
                    return sub[0], True
            else:
                return email_pkg.message_from_bytes(payload), True
    return msg, False


def estrai_body_text(msg: email.message.Message) -> str | None:
    """text/plain preferito; niente HTML raw, niente binari."""
    for part in msg.walk():
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
    return None


def iter_allegati_reali(msg: email.message.Message) -> list[tuple[str, bytes, str]]:
    """(nome, bytes, mime) per ogni allegato reale — esclusi artefatti busta."""
    out: list[tuple[str, bytes, str]] = []
    for part in msg.walk():
        nome = part.get_filename()
        if not nome or nome.lower() in ARTEFATTI_BUSTA:
            continue
        if part.get_content_disposition() != "attachment":
            continue
        content = part.get_payload(decode=True)
        if content is None:
            continue
        out.append((nome, content, part.get_content_type()))
    return out


SOURCE_NAME = "PEC_MAILBOX_INTUR_APPEND"


class AllegatiStore:
    """Binari allegati su GCS, indirizzati per contenuto.

    Path: <SOURCE_NAME>/allegati/<sha256[:2]>/<sha256>/<nome> — lo stesso
    contenuto trasmesso N volte è un solo oggetto per nome; il fan-out sulle
    trasmissioni vive nelle righe f_pec_allegati.
    """

    def __init__(
        self, bucket_name: str = "hotelops-raw", dry_run: bool = False, client=None
    ):
        self.bucket_name = bucket_name
        self.dry_run = dry_run
        self._client = client
        self.n_uploaded = 0
        self.n_riusati = 0

    def _get_client(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client

    def store(self, nome: str, content: bytes) -> tuple[str, str]:
        sha = hashlib.sha256(content).hexdigest()
        path = f"{SOURCE_NAME}/allegati/{sha[:2]}/{sha}/{nome}"
        uri = f"gs://{self.bucket_name}/{path}"
        if self.dry_run:
            return sha, uri
        blob = self._get_client().bucket(self.bucket_name).blob(path)
        if blob.exists():
            self.n_riusati += 1
        else:
            blob.upload_from_string(content, content_type="application/octet-stream")
            self.n_uploaded += 1
        return sha, uri
